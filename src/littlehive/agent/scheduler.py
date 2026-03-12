import json
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from littlehive.agent.config import get_config
from littlehive.agent.logger_setup import logger

logging.getLogger("apscheduler").setLevel(logging.ERROR)

# Wired once during start_proactive_scheduler() — avoids circular imports and
# keeps the dependency direction one-way (start_agent -> scheduler).
_inbox = None
_outbox_web = None
_outbox_telegram = None
_get_active_chat_id = None

notified_email_ids = set()
notified_event_ids = set()


def inject_proactive_update(updates_found):
    if not updates_found:
        return
    chat_id = _get_active_chat_id()
    combined_updates = "\n".join(updates_found)
    system_prompt_injection = (
        f"SYSTEM NOTIFICATION:\n"
        f"{combined_updates}\n\n"
        f"INSTRUCTION: Report these updates to the user in 1-2 sentences. "
        f"For emails that are newsletters or automated notifications, call manage_email to archive them and tell the user. "
        f"For emails requiring action, summarize them for the user. "
        f"For calendar events, state the event name and time."
    )

    _outbox_web.put({"type": "proactive_start"})

    if chat_id:
        _outbox_telegram.put({"type": "init", "chat_id": chat_id})

    _inbox.put(
        {
            "source": "proactive",
            "text": system_prompt_injection,
            "chat_id": chat_id,
        }
    )


def is_user_busy():
    from littlehive.tools.calendar_tools import get_events

    config = get_config()
    dnd_start = config.get("dnd_start", 23)
    dnd_end = config.get("dnd_end", 7)

    current_hour = datetime.now().hour

    # Handle overnight DND (e.g., 23 to 7)
    if dnd_start > dnd_end:
        if current_hour >= dnd_start or current_hour < dnd_end:
            return True
    else:
        if dnd_start <= current_hour < dnd_end:
            return True

    try:
        now = datetime.now(timezone.utc)
        res_str = get_events(
            time_min=(now - timedelta(minutes=1)).isoformat(),
            time_max=(now + timedelta(minutes=1)).isoformat(),
        )
        if isinstance(res_str, str):
            res = json.loads(res_str)
            if isinstance(res, list) and len(res) > 0:
                return True
    except Exception as e:
        logger.warning(f"[Proactive] Calendar busy-check failed: {e}")
    return False


def check_reminders_job():
    from littlehive.tools.reminder_tools import poll_due_reminders

    busy = is_user_busy()
    due_reminders = poll_due_reminders(skip_non_critical=busy)

    updates = []
    for r in due_reminders:
        priority = r.get("priority", "normal")
        updates.append(
            f"REMINDER DUE (ID {r['id']}, priority: {priority}): {r['task']}"
        )

    if updates:
        inject_proactive_update(updates)


def check_apis_job():
    global notified_email_ids, notified_event_ids
    from littlehive.tools.email_tools import _live_search_emails
    from littlehive.tools.calendar_tools import _live_get_events
    from littlehive.agent.local_cache import upsert_emails, cleanup_old_emails, replace_cached_events

    updates = []

    # 1. Sync Emails (Last 24h)
    try:
        email_res_str = _live_search_emails(query="newer_than:1d -in:sent", max_results=100)
        email_res = json.loads(email_res_str)
        if "emails" in email_res:
            emails = email_res["emails"]
            upsert_emails(emails)
            cleanup_old_emails()
            
            # Check for new unread emails for proactive notification
            for email in emails:
                if email["is_read"] == False and email["id"] not in notified_email_ids:
                    notified_email_ids.add(email["id"])
                    updates.append(
                        f"📧 New Email (ID: {email['id']}): '{email['subject']}' from {email['sender']}"
                    )
    except Exception as e:
        logger.warning(f"[Proactive] Email sync/check failed: {e}")

    # 2. Sync Events (Now to Now + 3 days)
    try:
        now = datetime.now(timezone.utc)
        sync_end = now + timedelta(days=3)
        
        event_res_str = _live_get_events(
            time_min=now.isoformat(), time_max=sync_end.isoformat(), max_results=50
        )
        event_res = json.loads(event_res_str)

        if isinstance(event_res, list):
            replace_cached_events(event_res)
            
            # Check for upcoming events in the next hour for proactive notification
            next_hour = now + timedelta(hours=1)
            for event in event_res:
                try:
                    event_start = datetime.fromisoformat(event["start"].replace('Z', '+00:00'))
                    if now <= event_start <= next_hour:
                        if event["id"] not in notified_event_ids:
                            notified_event_ids.add(event["id"])
                            attendees = event.get("attendees", [])
                            is_personal = len(attendees) <= 1
                            event_type = (
                                "Personal Block"
                                if is_personal
                                else f"Meeting with {len(attendees)} attendees"
                            )
                            updates.append(
                                f"📅 {event_type}: '{event['summary']}' at {event['start']}"
                            )
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"[Proactive] Calendar sync/check failed: {e}")

    # 3. Sync Google Tasks (All lists)
    try:
        from littlehive.tools.google_tasks import get_task_lists, _live_get_tasks
        from littlehive.agent.local_cache import replace_cached_tasks
        
        task_lists_str = get_task_lists()
        task_lists = json.loads(task_lists_str)
        
        all_tasks = []
        if isinstance(task_lists, list):
            for tlist in task_lists:
                list_id = tlist["id"]
                tasks_str = _live_get_tasks(tasklist_id=list_id)
                tasks = json.loads(tasks_str)
                if isinstance(tasks, list):
                    all_tasks.extend(tasks)
        
        if all_tasks:
            replace_cached_tasks(all_tasks)
    except Exception as e:
        logger.warning(f"[Proactive] Tasks sync failed: {e}")

    if updates:
        inject_proactive_update(updates)

    # Auto-respond: check new unread emails from auto-respond contacts
    _check_auto_respond_emails()


def _check_auto_respond_emails():
    """For contacts with auto_respond enabled, inject a draft-and-approve instruction
    for each new unread email from them."""
    try:
        from littlehive.tools.stakeholder_tools import get_auto_respond_contacts, pick_fun_fact
        from littlehive.agent.local_cache import _get_db

        contacts = get_auto_respond_contacts()
        if not contacts:
            return

        email_map = {}
        for c in contacts:
            addr = c["email"].strip().lower()
            if addr:
                email_map[addr] = c

        if not email_map:
            return

        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, sender, subject, snippet FROM cached_emails WHERE is_read = 0"
        )
        rows = cur.fetchall()
        conn.close()

        for row in rows:
            sender_raw = row["sender"] or ""
            sender_email = _extract_email(sender_raw)
            if sender_email not in email_map:
                continue
            email_id = row["id"]
            if email_id in notified_email_ids:
                continue

            contact = email_map[sender_email]
            fun_fact = pick_fun_fact()
            contact_name = contact.get("alias") or contact["name"]
            relationship = contact.get("relationship", "contact")
            prefs = contact.get("preferences", "")

            instruction = (
                f"AUTO-REPLY REQUEST:\n"
                f"Email ID: {email_id}\n"
                f"From: {contact_name} ({sender_email}), Relationship: {relationship}\n"
                f"Subject: {row['subject']}\n"
                f"Snippet: {row['snippet']}\n"
                f"Contact preferences: {prefs}\n\n"
                f"INSTRUCTIONS:\n"
                f"1. Read the full email using search_emails with this email ID.\n"
                f"2. Draft a warm, helpful reply appropriate for a {relationship}.\n"
                f"3. Include this fun fact at the end of the reply: \"{fun_fact}\"\n"
                f"4. Show the draft to the user and ask: \"Shall I send this reply to {contact_name}?\"\n"
                f"5. Wait for approval before sending. Use reply_to_email to send."
            )

            _outbox_web.put({"type": "proactive_start"})
            chat_id = _get_active_chat_id()
            if chat_id:
                _outbox_telegram.put({"type": "init", "chat_id": chat_id})

            _inbox.put({
                "source": "proactive",
                "text": instruction,
                "chat_id": chat_id,
            })

    except Exception as e:
        logger.warning(f"[Auto-Respond] Check failed: {e}")


def _extract_email(sender: str) -> str:
    """Extract bare email address from 'Name <email>' format."""
    import re
    match = re.search(r'<([^>]+)>', sender)
    if match:
        return match.group(1).strip().lower()
    if '@' in sender:
        return sender.strip().lower()
    return ""


def nightly_db_cleanup():
    import sqlite3
    from littlehive.agent.paths import DB_PATH

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM system_logs WHERE datetime(timestamp) <= datetime('now', '-7 days')"
        )
        cursor.execute(
            "DELETE FROM pending_tasks WHERE status IN ('completed', 'failed') AND datetime(created_at) <= datetime('now', '-2 days')"
        )
        cursor.execute(
            "DELETE FROM reminders WHERE status = 'completed' AND datetime(deadline) <= datetime('now', '-2 days')"
        )
        conn.commit()
        conn.close()
        logger.info("[Maintenance] Nightly DB cleanup completed.")
    except Exception as e:
        logger.error(f"[Maintenance Error] DB Cleanup: {e}")


def trigger_nightly_memory():
    logger.info("[Maintenance] Triggering nightly memory extraction.")
    _inbox.put(
        {
            "source": "system_maintenance",
            "text": "EXTRACT_NIGHTLY_MEMORIES",
            "chat_id": _get_active_chat_id(),
        }
    )

def trigger_morning_brief():
    logger.info("[Maintenance] Triggering morning intelligence brief.")
    _inbox.put(
        {
            "source": "system_maintenance",
            "text": "GENERATE_MORNING_BRIEF",
            "chat_id": _get_active_chat_id(),
        }
    )


def process_pending_tasks_job():
    from littlehive.tools.task_queue import _get_db
    from littlehive.tools.email_tools import (
        _actual_send_email,
        _actual_manage_email,
        _actual_reply_to_email,
    )
    from littlehive.tools.calendar_tools import (
        _actual_create_event,
        _actual_update_event,
        _actual_delete_event,
    )
    from littlehive.tools.messaging_tools import _actual_send_channel_message
    from littlehive.tools.google_tasks import (
        _actual_create_task,
        _actual_update_task,
        _actual_delete_task,
    )

    executors = {
        "send_email": _actual_send_email,
        "manage_email": _actual_manage_email,
        "reply_to_email": _actual_reply_to_email,
        "create_event": _actual_create_event,
        "update_event": _actual_update_event,
        "delete_event": _actual_delete_event,
        "send_channel_message": _actual_send_channel_message,
        "create_task": _actual_create_task,
        "update_task": _actual_update_task,
        "delete_task": _actual_delete_task,
    }

    conn = None
    try:
        conn = _get_db()
        cursor = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute(
            """
            SELECT id, tool_name, arguments, retry_count 
            FROM pending_tasks 
            WHERE status IN ('queued', 'failed_retry') 
            AND next_run_at <= ?
        """,
            (now,),
        )

        tasks = cursor.fetchall()

        for task in tasks:
            task_id = task["id"]
            tool_name = task["tool_name"]
            args = json.loads(task["arguments"])
            retry_count = task["retry_count"]

            cursor.execute(
                "UPDATE pending_tasks SET status='processing' WHERE id=?", (task_id,)
            )
            conn.commit()

            func = executors.get(tool_name)
            if not func:
                cursor.execute(
                    "UPDATE pending_tasks SET status='failed', error_message='Unknown tool' WHERE id=?",
                    (task_id,),
                )
                conn.commit()
                continue

            try:
                result = func(**args)

                if isinstance(result, str):
                    try:
                        res_dict = json.loads(result)
                        if res_dict.get("error"):
                            raise Exception(res_dict.get("error"))
                    except json.JSONDecodeError:
                        pass

                cursor.execute(
                    "UPDATE pending_tasks SET status='completed', error_message=NULL WHERE id=?",
                    (task_id,),
                )
                conn.commit()
            except Exception as e:
                error_msg = str(e)
                new_retry = retry_count + 1
                if new_retry >= 3:
                    cursor.execute(
                        "UPDATE pending_tasks SET status='failed', error_message=? WHERE id=?",
                        (error_msg, task_id),
                    )
                    conn.commit()
                    injection = (
                        f"SYSTEM NOTIFICATION: Background task '{tool_name}' failed after 3 attempts. "
                        f"Error: {error_msg}. Tell the user about this failure in chat. "
                        f"Do not attempt to resend via messaging tools."
                    )
                    _inbox.put(
                        {
                            "source": "proactive",
                            "text": injection,
                            "chat_id": _get_active_chat_id(),
                        }
                    )
                else:
                    next_run = (datetime.now() + timedelta(minutes=2)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    cursor.execute(
                        "UPDATE pending_tasks SET status='failed_retry', retry_count=?, next_run_at=?, error_message=? WHERE id=?",
                        (new_retry, next_run, error_msg, task_id),
                    )
                    conn.commit()

    except Exception as e:
        logger.error(f"[Async Worker Error] {e}")
    finally:
        if conn:
            conn.close()


def start_proactive_scheduler(inbox, outbox_web, outbox_telegram, get_active_chat_id):
    """Wire up queue references and start the background scheduler."""
    global _inbox, _outbox_web, _outbox_telegram, _get_active_chat_id
    global notified_email_ids, notified_event_ids
    from littlehive.tools.email_tools import search_emails
    from littlehive.tools.calendar_tools import get_events

    _inbox = inbox
    _outbox_web = outbox_web
    _outbox_telegram = outbox_telegram
    _get_active_chat_id = get_active_chat_id

    logger.info("[Proactive] Initializing background scheduler...")

    # Initialize local cache database
    from littlehive.agent.local_cache import (
        init_cache_db, 
        upsert_emails, 
        replace_cached_events, 
        cleanup_old_emails, 
        replace_cached_tasks
    )
    try:
        init_cache_db()
    except Exception as e:
        logger.error(f"[Proactive] DB Init Failed: {e}")

    # Pre-fetch current state to prevent notification spam on startup & seed cache
    try:
        from littlehive.tools.email_tools import _live_search_emails
        from littlehive.tools.calendar_tools import _live_get_events
        from littlehive.tools.google_tasks import get_task_lists, _live_get_tasks
        
        # Emails
        email_res_str = _live_search_emails(query="newer_than:1d -in:sent", max_results=100)
        email_res = json.loads(email_res_str)
        if "emails" in email_res:
            upsert_emails(email_res["emails"])
            cleanup_old_emails()
            for email in email_res["emails"]:
                if not email["is_read"]:
                    notified_email_ids.add(email["id"])

        # Calendar
        now = datetime.now(timezone.utc)
        sync_end = now + timedelta(days=3)
        event_res_str = _live_get_events(
            time_min=now.isoformat(), time_max=sync_end.isoformat(), max_results=50
        )
        event_res = json.loads(event_res_str)
        if isinstance(event_res, list):
            replace_cached_events(event_res)
            next_hour = now + timedelta(hours=1)
            for event in event_res:
                try:
                    event_start = datetime.fromisoformat(event["start"].replace('Z', '+00:00'))
                    if now <= event_start <= next_hour:
                        notified_event_ids.add(event["id"])
                except Exception:
                    pass
        
        # Google Tasks
        task_lists_str = get_task_lists()
        task_lists = json.loads(task_lists_str)
        all_tasks = []
        if isinstance(task_lists, list):
            for tlist in task_lists:
                list_id = tlist["id"]
                tasks_str = _live_get_tasks(tasklist_id=list_id)
                tasks = json.loads(tasks_str)
                if isinstance(tasks, list):
                    all_tasks.extend(tasks)
        if all_tasks:
            replace_cached_tasks(all_tasks)

    except Exception as e:
        logger.warning(f"[Proactive] Scheduler pre-fetch failed: {e}")


    scheduler = BackgroundScheduler()
    config = get_config()

    if config.get("poll_reminders_enabled", True):
        fast_secs = config.get(
            "poll_reminders_interval", config.get("fast_polling_seconds", 30)
        )
        scheduler.add_job(
            check_reminders_job,
            "interval",
            seconds=fast_secs,
            next_run_time=datetime.now() + timedelta(seconds=30),
        )

    if config.get("poll_tasks_enabled", True):
        tasks_mins = config.get("poll_tasks_interval", 5)
        scheduler.add_job(
            process_pending_tasks_job,
            "interval",
            minutes=tasks_mins,
            next_run_time=datetime.now() + timedelta(seconds=30),
        )

    if config.get("poll_apis_enabled", True):
        api_minutes = config.get(
            "poll_apis_interval", config.get("proactive_polling_minutes", 20)
        )
        scheduler.add_job(
            check_apis_job,
            "interval",
            minutes=api_minutes,
            next_run_time=datetime.now() + timedelta(seconds=45),
        )

    if config.get("nightly_cleanup_enabled", True):
        time_str = config.get("nightly_cleanup_time", "03:00")
        try:
            h, m = map(int, time_str.split(":"))
            scheduler.add_job(nightly_db_cleanup, "cron", hour=h, minute=m)
        except Exception:
            scheduler.add_job(nightly_db_cleanup, "cron", hour=3, minute=0)

    if config.get("nightly_memory_enabled", True):
        time_str = config.get("nightly_memory_time", "03:15")
        try:
            h, m = map(int, time_str.split(":"))
            scheduler.add_job(trigger_nightly_memory, "cron", hour=h, minute=m)
        except Exception:
            scheduler.add_job(trigger_nightly_memory, "cron", hour=3, minute=15)

    if config.get("morning_brief_enabled", True):
        time_str = config.get("morning_brief_time", "08:00")
        try:
            h, m = map(int, time_str.split(":"))
            scheduler.add_job(trigger_morning_brief, "cron", hour=h, minute=m)
        except Exception:
            scheduler.add_job(trigger_morning_brief, "cron", hour=8, minute=0)

    scheduler.start()
    logger.info("[Proactive] Scheduler active with advanced configuration.")
