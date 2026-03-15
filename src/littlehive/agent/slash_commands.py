"""
Slash Command Pre-Processor
Pattern-matches structured commands and executes tools directly,
bypassing LLM inference for instant responses.

Supported:
  /email <name|addr> <subject>: <body>
  /remind <time> <task>
  /bill <amount> <vendor> due <date>
  /search <query>
  /cal [today|tomorrow|week]
  /bills
  /reminders
"""

import re
import json
import logging
from datetime import datetime, timedelta, timezone

from littlehive.agent.config import get_config

logger = logging.getLogger(__name__)


def _parse_relative_time(time_str):
    """
    Parse natural-language time like '5pm', '8:30am', 'tomorrow 9am',
    'monday 10am', 'in 2 hours' into an ISO 8601 string with timezone offset.
    Returns None if unparseable.
    """
    import time as _time
    text = time_str.strip().lower()
    now = datetime.now()

    utc_offset_sec = _time.altzone if _time.localtime().tm_isdst else _time.timezone
    offset_hours = int(-utc_offset_sec / 3600)
    offset_mins = int((abs(-utc_offset_sec) % 3600) / 60)
    sign = "+" if -utc_offset_sec >= 0 else "-"
    tz_suffix = f"{sign}{abs(offset_hours):02d}:{abs(offset_mins):02d}"

    def _make_iso(dt):
        return dt.strftime(f"%Y-%m-%dT%H:%M:%S{tz_suffix}")

    # "in N hours/minutes"
    m = re.match(r"in\s+(\d+)\s*(hours?|hrs?|minutes?|mins?)", text)
    if m:
        val = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("h"):
            return _make_iso(now + timedelta(hours=val))
        return _make_iso(now + timedelta(minutes=val))

    # Day prefix: "tomorrow", "monday", etc.
    target_date = now
    day_prefix = None

    if text.startswith("tomorrow"):
        target_date = now + timedelta(days=1)
        text = text.replace("tomorrow", "", 1).strip()
        day_prefix = True
    else:
        day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        for i, day_name in enumerate(day_names):
            if text.startswith(day_name):
                days_ahead = (i - now.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7
                target_date = now + timedelta(days=days_ahead)
                text = text.replace(day_name, "", 1).strip()
                day_prefix = True
                break

    # Parse time: "5pm", "5:30pm", "17:00", "8am"
    m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = m.group(3)
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        result = target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        # If no day prefix and time has passed today, assume tomorrow
        if not day_prefix and result <= now:
            result += timedelta(days=1)
        return _make_iso(result)

    return None


def _try_parse_date(date_str):
    """Parse date strings like 'March 20', '2026-03-20', 'march 20 2026'."""
    text = date_str.strip()
    for fmt in ("%B %d %Y", "%B %d", "%b %d %Y", "%b %d", "%Y-%m-%d", "%m/%d/%Y", "%m/%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            if parsed.year == 1900:
                parsed = parsed.replace(year=datetime.now().year)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Command Handlers — each returns (response_text, tool_log_info) or None
# ---------------------------------------------------------------------------

def _handle_email(args_text):
    """
    /email john about meeting: Let's sync at 3pm tomorrow
    /email john@x.com subject: body text here
    """
    # Pattern: /email <recipient> <subject_marker> <subject>: <body>
    m = re.match(
        r"(?P<recipient>\S+)\s+(?:about|re|subject|subj)[\s:]+(?P<subject>[^:]+):\s*(?P<body>.+)",
        args_text, re.IGNORECASE | re.DOTALL
    )
    if not m:
        # Simpler: /email <recipient> <everything as subject+body>
        m = re.match(r"(?P<recipient>\S+)\s+(?P<content>.+)", args_text, re.DOTALL)
        if not m:
            return None

        recipient = m.group("recipient")
        content = m.group("content").strip()
        # Try to split on first sentence boundary as subject
        split = re.split(r"[.!?]\s", content, maxsplit=1)
        subject = split[0].strip()[:80]
        body = content
    else:
        recipient = m.group("recipient")
        subject = m.group("subject").strip()
        body = m.group("body").strip()

    # Resolve name to email via stakeholder lookup
    email_addr = recipient
    contact_name = recipient
    if "@" not in recipient:
        try:
            from littlehive.tools.stakeholder_tools import lookup_stakeholder
            res = json.loads(lookup_stakeholder(recipient))
            if isinstance(res, list) and res:
                email_addr = res[0].get("email", recipient)
                contact_name = res[0].get("name", recipient)
            elif isinstance(res, dict) and res.get("email"):
                email_addr = res["email"]
                contact_name = res.get("name", recipient)
        except Exception:
            pass

    if "@" not in email_addr:
        return f"Could not find an email address for '{recipient}'. Please use the full email address or add them as a contact first.", None

    # Build signature
    config = get_config()
    agent_name = config.get("agent_name", "Roxy")
    agent_title = config.get("agent_title", "Executive Staff")
    user_name = config.get("user_name", "the user")
    signature = f"\n\nRegards,\n{agent_name},\n{agent_title},\n{user_name}'s Office"

    try:
        from littlehive.tools.email_tools import send_email
        result = send_email(to=email_addr, subject=subject, body=body + signature)
        parsed = json.loads(result)
        if parsed.get("error"):
            return f"Failed to send email: {parsed['error']}", None
        return (
            f"Email drafted to **{contact_name}** ({email_addr})\n"
            f"Subject: {subject}\n"
            f"Draft saved in Gmail for review.",
            {"tool": "send_email", "args": {"to": email_addr, "subject": subject}}
        )
    except Exception as e:
        return f"Email failed: {str(e)}", None


def _handle_remind(args_text):
    """
    /remind 5pm call mom
    /remind tomorrow 9am prepare presentation
    /remind in 2 hours check oven
    """
    # Try to extract time from the beginning
    time_patterns = [
        r"(in\s+\d+\s+(?:hours?|hrs?|minutes?|mins?))",
        r"((?:tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
        r"(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
        r"(\d{1,2}:\d{2})",
    ]

    time_str = None
    task_text = args_text

    for pattern in time_patterns:
        m = re.match(pattern, args_text, re.IGNORECASE)
        if m:
            time_str = m.group(1)
            task_text = args_text[m.end():].strip()
            break

    if not time_str:
        return None

    iso_time = _parse_relative_time(time_str)
    if not iso_time:
        return f"Could not parse time '{time_str}'. Try formats like '5pm', 'tomorrow 9am', or 'in 2 hours'.", None

    if not task_text:
        task_text = "Reminder"

    try:
        from littlehive.tools.reminder_tools import set_reminder
        result = json.loads(set_reminder(task=task_text, reminder_time=iso_time))
        if result.get("error"):
            return f"Could not set reminder: {result['error']}", None
        return (
            f"Reminder set for **{time_str}**: {task_text}",
            {"tool": "set_reminder", "args": {"task": task_text, "reminder_time": iso_time}}
        )
    except Exception as e:
        return f"Reminder failed: {str(e)}", None


def _handle_bill(args_text):
    """
    /bill $50 electric due March 20
    /bill 1200 rent due 2026-04-01
    """
    m = re.match(
        r"\$?\s*(\d+(?:\.\d{2})?)\s+(.+?)\s+due\s+(.+)",
        args_text, re.IGNORECASE
    )
    if not m:
        return None

    amount = float(m.group(1))
    vendor = m.group(2).strip()
    due_raw = m.group(3).strip()

    due_date = _try_parse_date(due_raw)
    if not due_date:
        return f"Could not parse due date '{due_raw}'. Try 'March 20' or '2026-03-20'.", None

    try:
        from littlehive.tools.finance_tools import add_bill
        result = json.loads(add_bill(vendor=vendor, amount=amount, due_date=due_date))
        if result.get("error"):
            return f"Could not add bill: {result['error']}", None

        # Auto-set reminder for 2 days before
        reminder_date = (datetime.strptime(due_date, "%Y-%m-%d") - timedelta(days=2))
        if reminder_date > datetime.now():
            from littlehive.tools.reminder_tools import set_reminder
            set_reminder(
                task=f"Bill due in 2 days: {vendor} ${amount:.2f}",
                reminder_time=reminder_date.replace(hour=9).strftime("%Y-%m-%dT09:00:00+05:30")
            )

        return (
            f"Bill recorded: **{vendor}** — ${amount:.2f} due {due_date}. Reminder set for 2 days before.",
            {"tool": "add_bill", "args": {"vendor": vendor, "amount": amount}}
        )
    except Exception as e:
        return f"Bill failed: {str(e)}", None


def _handle_search(args_text):
    """/search latest news on AI agents"""
    if not args_text.strip():
        return None

    try:
        from littlehive.tools.web_tools import execute_tool as web_execute
        result = web_execute("web_search", {"query": args_text.strip()})
        parsed = json.loads(result)
        if parsed.get("error"):
            return f"Search failed: {parsed['error']}", None

        # Format results concisely
        results = parsed.get("results", [])
        if not results:
            return f"No results found for: {args_text}", None

        lines = [f"**Search: {args_text.strip()}**\n"]
        for i, r in enumerate(results[:5], 1):
            title = r.get("title", "")
            snippet = r.get("body", r.get("snippet", ""))[:120]
            url = r.get("href", r.get("url", ""))
            lines.append(f"{i}. **{title}**\n   {snippet}\n   {url}")

        return (
            "\n".join(lines),
            {"tool": "web_search", "args": {"query": args_text.strip()}}
        )
    except Exception as e:
        return f"Search failed: {str(e)}", None


def _handle_cal(args_text):
    """/cal, /cal today, /cal tomorrow, /cal week"""
    scope = args_text.strip().lower() if args_text.strip() else "today"

    now = datetime.now()

    if scope == "tomorrow":
        start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0)
        end = start.replace(hour=23, minute=59, second=59)
        label = "Tomorrow"
    elif scope == "week":
        start = now
        end = now + timedelta(days=7)
        label = "This week"
    else:
        start = now
        end = now.replace(hour=23, minute=59, second=59)
        label = "Today"

    try:
        from littlehive.agent.local_cache import query_cached_events
        events_str = query_cached_events(time_min=start.isoformat(), time_max=end.isoformat())
        events = json.loads(events_str)

        if not events:
            return f"**{label}'s calendar:** No events scheduled.", None

        lines = [f"**{label}'s calendar:**\n"]
        seen = set()
        for e in events[:15]:
            summary = e.get("summary", "Untitled")
            if summary in seen:
                continue
            seen.add(summary)
            start_t = e.get("start", "")
            try:
                dt = datetime.fromisoformat(start_t)
                time_str = dt.strftime("%-I:%M %p").lstrip("0")
            except Exception:
                time_str = start_t
            lines.append(f"  - {summary} at {time_str}")

        return "\n".join(lines), {"tool": "get_events", "args": {"scope": scope}}
    except Exception as e:
        return f"Calendar check failed: {str(e)}", None


def _handle_bills_list(_args_text):
    """/bills — list pending bills"""
    try:
        from littlehive.tools.finance_tools import list_bills
        result = json.loads(list_bills())
        if isinstance(result, dict) and result.get("error"):
            return f"Could not fetch bills: {result['error']}", None

        bills = result if isinstance(result, list) else result.get("bills", [])
        if not bills:
            return "No pending bills.", None

        lines = ["**Pending bills:**\n"]
        for b in bills:
            lines.append(f"  - {b.get('vendor', '?')}: ${b.get('amount', '?')} due {b.get('due_date', '?')}")
        return "\n".join(lines), {"tool": "list_bills", "args": {}}
    except Exception as e:
        return f"Bills check failed: {str(e)}", None


def _handle_reminders_list(_args_text):
    """/reminders — list pending reminders"""
    try:
        from littlehive.tools.reminder_tools import get_pending_reminders
        result = json.loads(get_pending_reminders())
        if isinstance(result, dict) and result.get("message"):
            return result["message"], None

        if not isinstance(result, list) or not result:
            return "No pending reminders.", None

        lines = ["**Pending reminders:**\n"]
        for r in result:
            lines.append(f"  - (#{r.get('id', '?')}) {r.get('task', '?')} — due {r.get('deadline', '?')}")
        return "\n".join(lines), {"tool": "get_pending_reminders", "args": {}}
    except Exception as e:
        return f"Reminders check failed: {str(e)}", None


# ---------------------------------------------------------------------------
# Command Registry
# ---------------------------------------------------------------------------

SLASH_COMMANDS = {
    "/email": {
        "handler": _handle_email,
        "hint": "/email <name> about <subject>: <body>",
        "description": "Draft an email instantly",
    },
    "/remind": {
        "handler": _handle_remind,
        "hint": "/remind <time> <task>",
        "description": "Set a reminder instantly",
    },
    "/bill": {
        "handler": _handle_bill,
        "hint": "/bill <amount> <vendor> due <date>",
        "description": "Record a bill",
    },
    "/search": {
        "handler": _handle_search,
        "hint": "/search <query>",
        "description": "Quick web search",
    },
    "/cal": {
        "handler": _handle_cal,
        "hint": "/cal [today|tomorrow|week]",
        "description": "Check your calendar",
    },
    "/bills": {
        "handler": _handle_bills_list,
        "hint": "/bills",
        "description": "List pending bills",
    },
    "/reminders": {
        "handler": _handle_reminders_list,
        "hint": "/reminders",
        "description": "List pending reminders",
    },
}


def try_slash_command(user_input):
    """
    If user_input starts with a known slash command, execute it directly.

    Returns:
        (response_text, tool_log_info) if handled, or (None, None) if not a slash command.
        tool_log_info is a dict with {tool, args} for action logging, or None.
    """
    text = user_input.strip()
    if not text.startswith("/"):
        return None, None

    # Split into command + rest
    parts = text.split(None, 1)
    cmd = parts[0].lower()
    args_text = parts[1] if len(parts) > 1 else ""

    spec = SLASH_COMMANDS.get(cmd)
    if not spec:
        return None, None

    try:
        result = spec["handler"](args_text)
        if result is None:
            return None, None
        if isinstance(result, tuple):
            return result
        return result, None
    except Exception as e:
        logger.error(f"[SlashCommand] {cmd} failed: {e}")
        return f"Slash command error: {str(e)}", None


def get_slash_command_hints():
    """Return a list of hint strings for placeholder display."""
    return [spec["hint"] for spec in SLASH_COMMANDS.values()]
