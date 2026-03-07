import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sys
import os
import time
import json
import logging
import threading
import queue
from littlehive.agent.logger_setup import logger
import requests
from datetime import datetime

# Suppress noisy library logs
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)
logging.getLogger("google_auth_oauthlib.flow").setLevel(logging.ERROR)

from littlehive.agent.paths import CONFIG_PATH as CONFIG_FILE


def get_config():
    default_config = {
        "telegram_bot_token": "",
        "proactive_polling_minutes": 30,
        "fast_polling_seconds": 30,
        "agent_name": "Roxy",
        "agent_title": "Executive Staff",
        "user_name": "Anupam Bhatt",
        "temperature": 0.35,
        "model_path": "mlx-community/mistralai_Ministral-3-14B-Instruct-2512-MLX-MXFP4",  # Guidance: Use MLX converted models for best Apple Silicon performance
    }
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump(default_config, f, indent=4)
        return default_config

    try:
        with open(CONFIG_FILE, "r") as f:
            user_config = json.load(f)
            # merge defaults
            updated = False
            for k, v in default_config.items():
                if k not in user_config:
                    user_config[k] = v
                    updated = True
        if updated:
            with open(CONFIG_FILE, "w") as f:
                json.dump(user_config, f, indent=4)
        return user_config
    except Exception:
        return default_config


import mlx.core as mx
from mlx_lm import load, stream_generate
from mlx_lm.models.cache import make_prompt_cache
from mlx_lm.sample_utils import make_sampler
from littlehive.agent.tool_registry import dispatch_tool
from littlehive.agent.tool_router import get_active_tools

# --- QUEUE SETUP ---
# The Inbox where all UIs send user messages to the Brain
inbox_queue = queue.Queue()

# The Outboxes where the Brain sends responses back to specific UIs
outbox_telegram = queue.Queue()
outbox_web = queue.Queue()

# Global to store the latest Telegram chat ID for proactive notifications
config_init = get_config()
active_telegram_chat_id = config_init.get("telegram_chat_id")

# --- THE PROACTIVE THREAD ---
from apscheduler.schedulers.background import BackgroundScheduler
import logging

logging.getLogger("apscheduler").setLevel(logging.ERROR)


# --- THE PROACTIVE SCHEDULER ---
# Globals for Proactive State
notified_email_ids = set()
notified_event_ids = set()


def inject_proactive_update(updates_found):
    global active_telegram_chat_id
    if updates_found:
        combined_updates = "\n".join(updates_found)
        system_prompt_injection = f"SYSTEM NOTIFICATION: The following new events/emails just occurred in the background:\n{combined_updates}\n\nINSTRUCTION: Autonomously process these updates. For new emails, read them using your tools if needed. If an email is noise, FYI, or requires no action, autonomously mark it as read and archive it, and just briefly tell the user you handled it. If it requires action, handle it. For calendar events, give a quick heads up. Be extremely concise and fiercely independent."

        # Broadcast proactive start to web outbox as well
        outbox_web.put({"type": "proactive_start"})

        if active_telegram_chat_id:
            outbox_telegram.put({"type": "init", "chat_id": active_telegram_chat_id})

        inbox_queue.put(
            {
                "source": "proactive",
                "text": system_prompt_injection,
                "chat_id": active_telegram_chat_id,
            }
        )


def is_user_busy():
    from littlehive.tools.calendar_tools import get_events
    from datetime import datetime, timedelta, timezone

    config = get_config()
    dnd_start = config.get("dnd_start", 23)
    dnd_end = config.get("dnd_end", 7)

    # Check DND Hours (local time)
    current_hour = datetime.now().hour

    # Handle overnight DND (e.g., 23 to 7)
    if dnd_start > dnd_end:
        if current_hour >= dnd_start or current_hour < dnd_end:
            return True
    else:
        # Handle same-day DND (e.g., 9 to 17)
        if dnd_start <= current_hour < dnd_end:
            return True

    # Check Calendar for active meetings
    try:
        now = datetime.now(timezone.utc)
        # Check from 1 minute ago to 1 minute from now
        res_str = get_events(
            time_min=(now - timedelta(minutes=1)).isoformat(),
            time_max=(now + timedelta(minutes=1)).isoformat(),
        )
        if isinstance(res_str, str):
            res = json.loads(res_str)
            if isinstance(res, list) and len(res) > 0:
                return True
    except Exception:
        pass
    return False


def check_reminders_job():
    from littlehive.tools.reminder_tools import poll_due_reminders

    busy = is_user_busy()

    # If busy, skip non-critical reminders
    due_reminders = poll_due_reminders(skip_non_critical=busy)

    updates = []
    for r in due_reminders:
        priority = r.get("priority", "normal")
        updates.append(
            f"⏰ REMINDER DUE: '{r['task']}'. Priority: {priority}. Internal ID {r['id']}. You must ask the user if they completed it."
        )

    if updates:
        inject_proactive_update(updates)


def check_apis_job():
    global notified_email_ids, notified_event_ids
    from littlehive.tools.email_tools import search_emails
    from littlehive.tools.calendar_tools import get_events
    from datetime import datetime, timedelta, timezone

    updates = []

    # Check emails
    try:
        email_res_str = search_emails(query="is:unread", max_results=5)
        email_res = json.loads(email_res_str)
        if "emails" in email_res:
            for email in email_res["emails"]:
                if email["id"] not in notified_email_ids:
                    notified_email_ids.add(email["id"])
                    updates.append(
                        f"📧 New Email (ID: {email['id']}): '{email['subject']}' from {email['sender']}"
                    )
    except Exception:
        pass

    # Check calendar for upcoming meetings (next 1 hour)
    try:
        now = datetime.now(timezone.utc)
        next_hour = now + timedelta(hours=1)
        event_res_str = get_events(
            time_min=now.isoformat(), time_max=next_hour.isoformat()
        )
        event_res = json.loads(event_res_str)

        if isinstance(event_res, list):
            for event in event_res:
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

    if updates:
        inject_proactive_update(updates)


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
    inbox_queue.put(
        {
            "source": "system_maintenance",
            "text": "EXTRACT_NIGHTLY_MEMORIES",
            "chat_id": active_telegram_chat_id,
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
    from datetime import datetime, timedelta

    executors = {
        "send_email": _actual_send_email,
        "manage_email": _actual_manage_email,
        "reply_to_email": _actual_reply_to_email,
        "create_event": _actual_create_event,
        "update_event": _actual_update_event,
        "delete_event": _actual_delete_event,
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

            # Mark processing
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
                # Execute
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
                    injection = f"SYSTEM NOTIFICATION: The background task '{tool_name}' failed permanently after 3 attempts. Error: {error_msg}. Please notify the user."
                    inbox_queue.put(
                        {
                            "source": "proactive",
                            "text": injection,
                            "chat_id": active_telegram_chat_id,
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


def start_proactive_scheduler():
    global notified_email_ids, notified_event_ids
    from littlehive.tools.email_tools import search_emails
    from littlehive.tools.calendar_tools import get_events
    from datetime import datetime, timedelta, timezone

    logger.info("[Proactive] Initializing background scheduler...")

    # Pre-fetch state to prevent startup spam
    try:
        email_res_str = search_emails(query="is:unread", max_results=10)
        email_res = json.loads(email_res_str)
        if "emails" in email_res:
            for email in email_res["emails"]:
                notified_email_ids.add(email["id"])

        now = datetime.now(timezone.utc)
        next_hour = now + timedelta(hours=1)
        event_res_str = get_events(
            time_min=now.isoformat(), time_max=next_hour.isoformat()
        )
        event_res = json.loads(event_res_str)
        if isinstance(event_res, list):
            for event in event_res:
                notified_event_ids.add(event["id"])
    except Exception:
        pass

    scheduler = BackgroundScheduler()
    config = get_config()

    # 1. Reminders (Fast Poll)
    if config.get("poll_reminders_enabled", True):
        fast_secs = config.get(
            "poll_reminders_interval", config.get("fast_polling_seconds", 30)
        )
        scheduler.add_job(
            check_reminders_job,
            "interval",
            seconds=fast_secs,
            next_run_time=datetime.now(),
        )

    # 2. Pending Tasks (Email/Calendar background queue)
    if config.get("poll_tasks_enabled", True):
        tasks_mins = config.get("poll_tasks_interval", 5)
        scheduler.add_job(
            process_pending_tasks_job,
            "interval",
            minutes=tasks_mins,
            next_run_time=datetime.now(),
        )

    # 3. External APIs (Google Calendar, Gmail lookahead)
    if config.get("poll_apis_enabled", True):
        api_minutes = config.get(
            "poll_apis_interval", config.get("proactive_polling_minutes", 20)
        )
        scheduler.add_job(
            check_apis_job,
            "interval",
            minutes=api_minutes,
            next_run_time=datetime.now() + timedelta(seconds=10),
        )

    # 4. Nightly DB Cleanup
    if config.get("nightly_cleanup_enabled", True):
        time_str = config.get("nightly_cleanup_time", "03:00")
        try:
            h, m = map(int, time_str.split(":"))
            scheduler.add_job(nightly_db_cleanup, "cron", hour=h, minute=m)
        except Exception:
            scheduler.add_job(nightly_db_cleanup, "cron", hour=3, minute=0)

    # 5. Nightly Memory Extraction
    if config.get("nightly_memory_enabled", True):
        time_str = config.get("nightly_memory_time", "03:15")
        try:
            h, m = map(int, time_str.split(":"))
            scheduler.add_job(trigger_nightly_memory, "cron", hour=h, minute=m)
        except Exception:
            scheduler.add_job(trigger_nightly_memory, "cron", hour=3, minute=15)

    scheduler.start()
    logger.info("[Proactive] Scheduler active with advanced configuration.")


# --- THE TELEGRAM THREAD ---
def telegram_worker():
    config = get_config()
    BOT_TOKEN = config.get("telegram_bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not BOT_TOKEN:
        logger.warning(
            "\n[Warning] telegram_bot_token not set in config.json or env. Telegram bot will NOT run."
        )
        return

    BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

    def send_message(chat_id, text):
        if not text.strip():
            return
        requests.post(
            f"{BASE_URL}/sendMessage", json={"chat_id": chat_id, "text": text}
        )

    def edit_message(chat_id, message_id, text):
        if not text.strip():
            return
        requests.post(
            f"{BASE_URL}/editMessageText",
            json={"chat_id": chat_id, "message_id": message_id, "text": text},
        )

    update_offset = None
    logger.info("[Telegram] Thread started. Waiting for messages...")

    # A tiny inner-thread purely to pull generated tokens from the outbox queue
    # so we don't block the long-polling requests.get() loop below.
    def telegram_sender():
        active_chat_id = None
        active_msg_id = None
        buffer = ""

        while True:
            msg = outbox_telegram.get()
            if msg.get("type") == "init":
                active_chat_id = msg["chat_id"]
                resp = requests.post(
                    f"{BASE_URL}/sendMessage",
                    json={"chat_id": active_chat_id, "text": "⚙️ Processing..."},
                )
                if resp.status_code == 200:
                    active_msg_id = resp.json().get("result", {}).get("message_id")
            elif msg.get("type") == "tool_start":
                if active_chat_id and active_msg_id:
                    edit_message(active_chat_id, active_msg_id, "⚙️ Working on it...")
            elif msg.get("type") == "chunk":
                # We buffer chunks. Telegram doesn't support true character streaming.
                buffer += msg["content"]
            elif msg.get("type") == "done":
                if buffer.strip() and active_chat_id:
                    if active_msg_id:
                        edit_message(active_chat_id, active_msg_id, buffer.strip())
                    else:
                        send_message(active_chat_id, buffer.strip())
                buffer = ""  # Reset
                active_chat_id = None
                active_msg_id = None
            elif msg.get("type") == "error":
                if active_chat_id:
                    send_message(active_chat_id, f"Error: {msg['content']}")
                buffer = ""

    t_sender = threading.Thread(target=telegram_sender, daemon=True)
    t_sender.start()

    # The main Telegram Long-Polling Loop
    while True:
        try:
            resp = requests.get(
                f"{BASE_URL}/getUpdates",
                params={"timeout": 30, "offset": update_offset},
                timeout=35,
            )
            updates = resp.json()
        except Exception:
            time.sleep(1)
            continue

        if not updates or "result" not in updates:
            continue

        for update in updates["result"]:
            update_offset = update["update_id"] + 1
            if "message" not in update or "text" not in update["message"]:
                continue

            # Telegram API structure: update["message"]["chat"]["id"]
            if "chat" not in update["message"] or "id" not in update["message"]["chat"]:
                continue

            chat_id = update["message"]["chat"]["id"]
            user_input = update["message"]["text"]

            global active_telegram_chat_id
            if active_telegram_chat_id != chat_id:
                active_telegram_chat_id = chat_id
                try:
                    with open(CONFIG_FILE, "r+") as f:
                        c = json.load(f)
                        c["telegram_chat_id"] = chat_id
                        f.seek(0)
                        json.dump(c, f, indent=4)
                        f.truncate()
                except Exception as e:
                    logger.error(f"Failed to save telegram_chat_id: {e}")

            if user_input.strip() == "/start":
                send_message(chat_id, "Hello! I am your Senior Executive Assistant.")
                continue

            # Drop into the master queue, including the chat_id so we know where to reply
            outbox_telegram.put({"type": "init", "chat_id": chat_id})
            inbox_queue.put(
                {"source": "telegram", "text": user_input, "chat_id": chat_id}
            )


# --- THE CORE BRAIN (Main Thread) ---
def parse_mistral_tool_calls(response_text):
    if "[TOOL_CALLS]" not in response_text:
        return []

    import re

    def repair_json(s):
        s = s.replace("\n", "\\n").replace("\r", "\\r")
        return s

    clean_text = response_text.replace("</s>", "").strip()
    blocks = clean_text.split("[TOOL_CALLS]")
    calls = []

    for block in blocks[1:]:
        block = block.strip()
        if not block:
            continue

        try:
            if "[ARGS]" in block:
                func_name, args_str = block.split("[ARGS]")
                func_name = func_name.strip()
                args_str = args_str.strip()

                if not args_str:
                    args = {}
                else:
                    try:
                        args = json.loads(args_str)
                    except json.JSONDecodeError:
                        args = json.loads(
                            args_str.replace("\n", "\\n").replace("\r", "\\r")
                        )

                calls.append({"name": func_name, "arguments": args})

            elif block.startswith("[") and block.endswith("]"):
                try:
                    json_calls = json.loads(block)
                except json.JSONDecodeError:
                    json_calls = json.loads(
                        block.replace("\n", "\\n").replace("\r", "\\r")
                    )

                for jc in json_calls:
                    calls.append({"name": jc["name"], "arguments": jc["arguments"]})
            else:
                match = re.search(r"\{.*\}", block, re.DOTALL)
                if match:
                    args_str = match.group(0)
                    func_name = block[: match.start()].strip()
                    try:
                        args = json.loads(args_str)
                    except json.JSONDecodeError:
                        args = json.loads(
                            args_str.replace("\n", "\\n").replace("\r", "\\r")
                        )
                    calls.append({"name": func_name, "arguments": args})
                else:
                    # Assume it's just the function name with no arguments
                    func_name = block.strip()
                    if func_name:
                        calls.append({"name": func_name, "arguments": {}})
                    else:
                        raise ValueError(f"Unknown tool format: {block}")
        except Exception as e:
            logger.warning(
                f"Warning: Failed to parse tool call block: {block[:100]}... Error: {str(e)}"
            )
            continue

    return calls


def get_system_prompt():
    config = get_config()
    location_str = config.get("home_location", "Unknown Location")
    utc_offset_sec = time.altzone if time.localtime().tm_isdst else time.timezone
    offset_hours = int(-utc_offset_sec / 3600)
    offset_mins = int((abs(-utc_offset_sec) % 3600) / 60)
    sign = "+" if -utc_offset_sec >= 0 else "-"
    offset_str = f"{sign}{abs(offset_hours):02d}:{abs(offset_mins):02d}"
    default_tz = f"{time.tzname[time.localtime().tm_isdst]} (UTC{offset_str})"

    from littlehive.agent.paths import SYSTEM_PROMPT_PATH

    if not os.path.exists(SYSTEM_PROMPT_PATH):
        default_prompt = """# Layer 1 — Identity Prompt

## Role & Mission
You are {agent_name}, a highly efficient, hyper-competent, and fiercely decisive Senior Executive Assistant ({agent_title}) working for {user_name}. Your primary goal is to **minimize the user's cognitive load**. You do not just read data; you Triage, Summarize, and Execute autonomously.

## Personality & Tone
- **Natural & Human:** Speak like a trusted assistant texting their boss of many years.
- **Fiercely Independent:** Act with extreme confidence. NEVER end a message with "Should I do X?" or "Would you like me to do Y?" unless it is a massive, highly sensitive decision.
- **Concise:** Be extremely brief and practical. Just state what you handled. No hand-holding.
- **Plain Text Only:** Use plain text ONLY. DO NOT use markdown formatting (bold, italics, bulleted lists) as it breaks the messaging client.

## Signature Rules
Whenever you send an email or create a calendar invite using your tools, you MUST append this signature exactly at the end of the email body or event description:
\"\"\"Regards,
{agent_name},
{agent_title},
{user_name}'s Office
\"\"\"
*CRITICAL NOTE: DO NOT append this signature to your direct chat messages to me (whether in Telegram, Web, or Terminal). Only use it INSIDE the tools when composing emails or invites.*

---

# Layer 2 — Execution Rules

## Information Integrity
- **Tool-First:** If information may exist in a tool, query it before responding. Do not rely on memory.
- **Accuracy:** Respond ONLY based on data retrieved from littlehive.tools. NEVER assume, guess, or hallucinate.
- **Transparency:** If a tool returns no results or is unavailable, state it clearly and upfront.

## Verify Before Acting
- **Identifier Retrieval:** Before modifying or deleting any record (email, event, bill), you MUST query the system first to retrieve the exact internal ID. Never act on guessed identifiers.

## Action & Execution
- **Execute First, Ask Later:** If a user's request clearly implies an action and sufficient information is available, execute the action immediately and report the result. Do not ask for confirmation unless the request is ambiguous, risky, or missing required information.
- **Autonomous Follow-through:** Do not propose next steps for trivial matters. Take the next logical step autonomously (e.g., if a task is done, resolve it).
- **State Management:** Once a loop is closed (e.g., an email is replied to), autonomously mark it as READ and ARCHIVE it without asking the user. Keep their plate completely clean.

---

# Layer 3 — Operational Playbook

## 1. Inbox Triage (Email Management)
1. **Search:** Look up stakeholder email addresses in the map first. Search Gmail ONLY using email addresses.
2. **Deep Read:** Analyze the full content of the top 3 most urgent/actionable threads.
3. **The Briefing:** Categorize findings:
   - *Action Required:* If the user\\'s intent is clear, execute it. Otherwise, summarize the request and prepare the draft.
   - *FYI:* High-value updates requiring no action.
   - *Noise:* Autonomously archive or trash newsletters/promotions without asking.
4. **Inbox Zero:** Once a task is handled (reply sent, meeting booked), autonomously mark the email as READ and ARCHIVE it. Simply inform the user it was handled.

## 2. Calendar Management
- **Format:** Use ISO 8601 with exact timezone offsets (e.g., 2026-03-05T08:00:00+05:30).
- **Scheduling:** Autonomously suggest time slots based on current availability for incoming requests.
- **Personal Blocks:** Prefix self-only events with "Personal: ", "Self: ", or "Block: ".

## 3. Financial & Bill Management
- **Recording:** Extract vendor, amount, due date, and invoice number from emails. Record in liabilities, then READ and ARCHIVE the email.
- **Matching:** Match payment receipts to pending bills to mark them as paid.
- **Strict Rule:** ONLY mark a bill as paid if you see a receipt email or the user explicitly confirms payment.
- **Reporting:** Group pending bills by due date and calculate total outstanding amounts.

## 4. Smart Reminders
- **Setting:** Create reminders immediately when requested.
- **Firing:** When a reminder triggers, notify the user practically.
- **Follow-up:** If the user implies completion, autonomously mark it as completed without asking for explicit confirmation.

---

# Layer 4 — Runtime Context

- **Current Date:** {date}
- **Timezone:** {timezone}
- **Location:** {location}
"""
        with open(SYSTEM_PROMPT_PATH, "w") as f:
            f.write(default_prompt)

    with open(SYSTEM_PROMPT_PATH, "r") as f:
        template = f.read()

    return template.format(
        date=datetime.now().strftime("%A, %B %d, %Y"),
        timezone=os.environ.get("AGENT_TIMEZONE", default_tz),
        location=location_str,
        agent_name=config.get("agent_name", "Roxy"),
        agent_title=config.get("agent_title", "Executive Staff"),
        user_name=config.get("user_name", "Anupam Bhatt"),
    )


def main():
    config = get_config()
    model_path = config.get(
        "model_path", "mlx-community/mistralai_Ministral-3-14B-Instruct-2512-MLX-MXFP4"
    )

    logger.info(
        f"Initializing Core Brain & loading model ({model_path.split('/')[-1]})..."
    )

    try:
        model, tokenizer = load(model_path)
        prompt_cache = make_prompt_cache(model)

        messages = [{"role": "system", "content": get_system_prompt()}]
        historically_active_tools = []
        # VERY IMPORTANT: Mistral's chat template radically alters the string if `tools` are passed.
        # To maintain mathematically perfect string diffs for KV Caching, we must prime the cache
        # with the EXACT structure it will use later. We proactively load all potential tools now.
        from littlehive.agent.tool_registry import ROUTE_SCHEMAS

        all_possible_tools = ROUTE_SCHEMAS[
            "email"
        ]  # As per our Tiered Persona strategy, load all core tools

        # We start with empty previous_prompt_text.
        # This guarantees the FIRST turn encodes the ENTIRE system prompt and populates the cache!
        historically_active_tools = list(all_possible_tools)

        logger.info("Pre-warming prompt cache with System Prompt + Tool Schemas...")
        chat_kwargs_warmup = {
            "tokenize": False,
            "add_generation_prompt": False,
            "tools": historically_active_tools,
        }
        warmup_text = tokenizer.apply_chat_template(messages, **chat_kwargs_warmup)
        previous_prompt_tokens = tokenizer.encode(warmup_text)

        tokens_tensor = mx.array(previous_prompt_tokens)[None]
        _ = model(tokens_tensor, cache=prompt_cache)

        eval_list = []
        for c in prompt_cache:
            eval_list.append(c.keys)
            eval_list.append(c.values)
        mx.eval(eval_list)
        logger.info(
            f"✅ [Brain] Cache warmed with {len(previous_prompt_tokens)} tokens! Agent is ready and fast."
        )

    except Exception as e:
        logger.error(f"❌ [Error] Model Initialization Failed: {e}")
        sys.exit(1)

    # Start the Peripheral Senses AFTER Model and Cache are ready
    logger.info("🚀 Starting Web Dashboard and Telegram Bot...")
    from littlehive.dashboard.server import start_dashboard_server

    start_dashboard_server(port=8080, inbox=inbox_queue, outbox=outbox_web)

    t_telegram = threading.Thread(target=telegram_worker, daemon=True)
    t_telegram.start()

    start_proactive_scheduler()

    logger.info("✨ [Brain] All senses active. Listening to Inbox Queue...")

    while True:
        # Block until a message arrives from ANY interface
        task = inbox_queue.get()

        if task.get("source") == "system" and task.get("command") == "shutdown":
            logger.info("\nShutting down master brain...")
            sys.exit(0)

        source = task["source"]
        user_input = task["text"]

        if source == "system_maintenance" and user_input == "EXTRACT_NIGHTLY_MEMORIES":
            try:
                import sqlite3
                from mlx_lm import generate
                from littlehive.agent.paths import DB_PATH

                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT role, content FROM chat_archive WHERE datetime(timestamp) >= datetime('now', '-1 day')"
                )
                chats = cursor.fetchall()
                conn.close()

                chat_text = "\n".join(
                    [
                        f"{r[0]}: {r[1]}"
                        for r in chats
                        if r[1] and r[0] in ("user", "assistant")
                    ]
                )
                if chat_text.strip():
                    prompt = f"Analyze the following conversation from the last 24 hours. Extract any new, persistent facts about the user (e.g., preferences, relationships, names). Return ONLY a JSON list of strings representing the facts. If none, return [].\n\nChat:\n{chat_text}"
                    temp_messages = [
                        {
                            "role": "system",
                            "content": "You are a data extraction assistant. Output only a raw JSON list of strings.",
                        },
                        {"role": "user", "content": prompt},
                    ]
                    temp_prompt_str = tokenizer.apply_chat_template(
                        temp_messages, tokenize=False, add_generation_prompt=True
                    )

                    # Run without using the main prompt_cache to keep conversation context pure
                    response = generate(
                        model,
                        tokenizer,
                        prompt=temp_prompt_str,
                        verbose=False,
                        max_tokens=300,
                    )
                    try:
                        from littlehive.tools.memory_tools import save_core_fact

                        # Try to extract json list
                        start = response.find("[")
                        end = response.rfind("]")
                        if start != -1 and end != -1 and end > start:
                            facts = json.loads(response[start : end + 1])
                            if isinstance(facts, list):
                                for f in facts:
                                    if isinstance(f, str):
                                        save_core_fact(f)
                    except Exception as parse_e:
                        logger.error(f"Failed to parse nightly memories: {parse_e}")
            except Exception as e:
                logger.error(f"[Maintenance Error] Memory extraction failed: {e}")
            continue

        class MultiOutbox:
            def put(self, msg):
                if source == "proactive" or source == "web":
                    outbox_web.put(msg)
                if source == "telegram" or (
                    source == "proactive" and active_telegram_chat_id
                ):
                    outbox_telegram.put(msg)

        outbox = MultiOutbox()

        cmd = user_input.strip().lower()
        if cmd in ["/reset", "/new"]:
            messages = [{"role": "system", "content": get_system_prompt()}]
            previous_prompt_tokens = []
            # Must recreate cache when context shrinks
            prompt_cache = make_prompt_cache(model)
            outbox.put(
                {
                    "type": "chunk",
                    "content": "🧠 Memory wiped. Starting a fresh conversation.",
                }
            )
            outbox.put({"type": "done"})
            continue

        elif cmd in ["/context", "/status"]:
            chat_kwargs = {"tokenize": False, "add_generation_prompt": True}
            if historically_active_tools:
                chat_kwargs["tools"] = historically_active_tools
            temp_prompt = tokenizer.apply_chat_template(messages, **chat_kwargs)
            tokens = tokenizer.encode(temp_prompt)
            tok_len = len(tokens)
            max_ctx = 32768  # Standard for Ministral 3B
            perc = (tok_len / max_ctx) * 100

            reply = f"📊 **Context Status:**\nTokens Used: {tok_len} / {max_ctx} ({perc:.1f}%)\nMessages in memory: {len(messages)}"
            outbox.put({"type": "chunk", "content": reply})
            outbox.put({"type": "done"})
            continue

        elif cmd == "/help":
            reply = "🛠️ **Available Commands:**\n`/clear` - Clear the UI window (keeps memory)\n`/reset` or `/new` - Wipe agent's memory/context for a fresh start\n`/context` or `/status` - Check current token usage\n`/help` - Show this message"
            outbox.put({"type": "chunk", "content": reply})
            outbox.put({"type": "done"})
            continue

        current_time_str = datetime.now().strftime("%A, %b %d, %I:%M %p")
        # Removing "Source: Telegram" from the user input string.
        # It confuses the LLM into thinking the user is asking ABOUT Telegram.
        context_input = f"[Current Time: {current_time_str}] {user_input}"
        messages.append({"role": "user", "content": context_input})

        has_fired_callback = False
        message_start_time = time.time()

        try:
            while True:  # Tool Chaining Loop
                current_route_tools = get_active_tools(user_input)

                all_required_tools = list(historically_active_tools)
                for tool in current_route_tools:
                    if tool not in all_required_tools:
                        all_required_tools.append(tool)
                        historically_active_tools.append(tool)

                chat_kwargs = {"tokenize": False, "add_generation_prompt": True}
                if all_required_tools:
                    chat_kwargs["tools"] = all_required_tools

                full_prompt_text = tokenizer.apply_chat_template(
                    messages, **chat_kwargs
                )
                full_prompt_tokens = tokenizer.encode(full_prompt_text)

                # Token Diffing instead of String Diffing
                prompt_tokens = full_prompt_tokens[len(previous_prompt_tokens) :]

                is_tool_call = False
                full_response = ""

                temp = get_config().get("temperature", 0.35)
                sampler = make_sampler(temp=temp)

                for response in stream_generate(
                    model,
                    tokenizer,
                    prompt=prompt_tokens,
                    prompt_cache=prompt_cache,
                    max_tokens=2048,
                    sampler=sampler,
                ):
                    full_response += response.text
                    if "[TOOL_CALLS]" in full_response:
                        is_tool_call = True

                    if not is_tool_call:
                        if full_response.startswith("[") and len(full_response) < 15:
                            pass

                # --- CACHE ROLLBACK ---
                # MLX generation appends sampled tokens to the cache.
                # To prevent KV cache drift over multiple turns, we throw away the generated tokens
                # from the cache and let the strict Chat Template re-evaluate them on the next turn.
                for c in prompt_cache:
                    c.offset = len(full_prompt_tokens)
                previous_prompt_tokens = full_prompt_tokens

                if not is_tool_call:
                    final_text = full_response.strip()
                    messages.append({"role": "assistant", "content": final_text})
                    chat_kwargs["add_generation_prompt"] = False

                    time_taken = time.time() - message_start_time
                    if source == "web":
                        display_text = (
                            final_text
                            + f'\n\n<div style="font-size: 0.7em; color: gray; margin-top: 5px;">⏱️ {time_taken:.1f}s</div>'
                        )
                    else:
                        display_text = final_text + f"\n\n_⏱️ {time_taken:.1f}s_"

                    outbox.put({"type": "chunk", "content": display_text})
                    outbox.put({"type": "done"})
                    break  # Finished processing this user input entirely

                # --- Tools Triggered ---
                if not has_fired_callback:
                    outbox.put({"type": "tool_start"})
                    has_fired_callback = True

                tool_calls_list = parse_mistral_tool_calls(full_response)

                if is_tool_call and not tool_calls_list:
                    err_msg = "Error: Model generated a malformed tool call that could not be parsed."
                    outbox.put({"type": "error", "content": err_msg})
                    messages.append(
                        {"role": "assistant", "content": f"System Error: {err_msg}"}
                    )
                    break

                formatted_tool_calls = []
                for tc in tool_calls_list:
                    formatted_tool_calls.append(
                        {
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["arguments"])
                                if isinstance(tc["arguments"], dict)
                                else tc["arguments"],
                            },
                        }
                    )

                messages.append(
                    {
                        "role": "assistant",
                        "tool_calls": formatted_tool_calls,
                        "content": "",
                    }
                )
                chat_kwargs["add_generation_prompt"] = False

                for tc in tool_calls_list:
                    func_name = tc["name"]
                    func_args = tc["arguments"]
                    tool_result = dispatch_tool(func_name, func_args)
                    messages.append(
                        {"role": "tool", "name": func_name, "content": tool_result}
                    )

                # We DO NOT update previous_prompt_text here.
                # This ensures that on the next iteration of the loop, new_string contains the tool results
                # and Mistral evaluates them to generate the final assistant response!
                # Loop restarts naturally...

        except Exception as e:
            err_msg = str(e)
            outbox.put({"type": "error", "content": err_msg})
            messages.append(
                {"role": "assistant", "content": f"Internal Error: {err_msg}"}
            )
            # On exception, we might have partial cache. Safest to wipe and rebuild on next turn.
            prompt_cache = make_prompt_cache(model)
            previous_prompt_tokens = []


if __name__ == "__main__":
    main()
