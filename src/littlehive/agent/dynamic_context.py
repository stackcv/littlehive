"""
Dynamic Time-Aware Context Generator
Enriches the system prompt with situational awareness:
time period, energy cues, recent activity, calendar busyness,
and pending high-priority items.
"""

import json
import sqlite3
import logging
from datetime import datetime, timedelta

from littlehive.agent.paths import DB_PATH

logger = logging.getLogger(__name__)

TIME_PERIODS = {
    (5, 8): ("early_morning", "It's early morning. The user may be starting their day. Keep energy up, be proactive with the daily brief."),
    (8, 12): ("morning", "It's morning — peak productivity time. Be efficient, direct, and action-oriented."),
    (12, 14): ("midday", "It's around midday. The user may be taking a lunch break or winding down from a busy morning. Keep it balanced."),
    (14, 17): ("afternoon", "It's afternoon. Good time for follow-ups, reviews, and planning tomorrow."),
    (17, 20): ("evening", "It's evening. The user is likely winding down. Be lighter in tone, avoid creating urgency unless critical."),
    (20, 23): ("night", "It's night. Keep interactions brief and low-pressure. Only surface critical items."),
    (23, 24): ("late_night", "It's late night. Be minimal. Only respond to what's asked — no proactive suggestions."),
    (0, 5): ("late_night", "It's very late. Be minimal. Only respond to what's asked — no proactive suggestions."),
}


def _get_time_period():
    """Return (period_name, guidance_text) for the current hour."""
    hour = datetime.now().hour
    for (lo, hi), (name, guidance) in TIME_PERIODS.items():
        if lo <= hour < hi:
            return name, guidance
    return "unknown", ""


def _get_calendar_busyness():
    """Return a busyness score and summary of today's calendar."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='cached_events'"
        )
        if not cursor.fetchone():
            conn.close()
            return 0, "No calendar data available."

        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0).isoformat()
        today_end = now.replace(hour=23, minute=59, second=59).isoformat()

        cursor.execute(
            "SELECT COUNT(*) as cnt FROM cached_events WHERE start_time >= ? AND start_time <= ?",
            (today_start, today_end),
        )
        total_today = cursor.fetchone()["cnt"]

        # Count events already passed vs upcoming
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM cached_events WHERE start_time >= ? AND start_time <= ?",
            (now.isoformat(), today_end),
        )
        remaining = cursor.fetchone()["cnt"]

        conn.close()

        if total_today == 0:
            return 0, "Calendar is clear today."
        elif total_today <= 2:
            return 1, f"Light day: {total_today} event(s) today, {remaining} remaining."
        elif total_today <= 5:
            return 2, f"Moderate day: {total_today} events today, {remaining} remaining."
        else:
            return 3, f"Busy day: {total_today} events today, {remaining} still ahead."

    except Exception:
        return 0, "Calendar data unavailable."


def _get_pending_urgents():
    """Count high-priority pending items (critical reminders, overdue bills)."""
    items = []
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Critical reminders
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='reminders'"
        )
        if cursor.fetchone():
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM reminders WHERE status = 'pending' AND priority = 'critical'"
            )
            crit = cursor.fetchone()["cnt"]
            if crit > 0:
                items.append(f"{crit} critical reminder(s) pending")

        # Overdue bills
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='bills'"
        )
        if cursor.fetchone():
            today = datetime.now().strftime("%Y-%m-%d")
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM bills WHERE status != 'paid' AND due_date < ?",
                (today,),
            )
            overdue = cursor.fetchone()["cnt"]
            if overdue > 0:
                items.append(f"{overdue} overdue bill(s)")

        conn.close()
    except Exception:
        pass

    return items


def _get_hours_since_last_interaction():
    """How many hours since the user's last chat message."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_archive'"
        )
        if not cursor.fetchone():
            conn.close()
            return None

        cursor.execute(
            "SELECT MAX(timestamp) FROM chat_archive WHERE role = 'user'"
        )
        row = cursor.fetchone()
        conn.close()

        if row and row[0]:
            last_ts = datetime.fromisoformat(row[0])
            delta = datetime.now() - last_ts
            return round(delta.total_seconds() / 3600, 1)
    except Exception:
        pass
    return None


def _get_recent_activity_summary():
    """Summarize last 3 tool categories used (from user_actions)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='user_actions'"
        )
        if not cursor.fetchone():
            conn.close()
            return None

        cursor.execute(
            """SELECT DISTINCT action_category 
               FROM user_actions 
               WHERE timestamp >= datetime('now', 'localtime', '-4 hours')
                 AND action_category != 'other'
               ORDER BY timestamp DESC 
               LIMIT 3"""
        )
        rows = cursor.fetchall()
        conn.close()

        if rows:
            categories = [r["action_category"] for r in rows]
            return categories
    except Exception:
        pass
    return None


def build_dynamic_context():
    """
    Build the dynamic context string to inject into the system prompt.
    Returns a string of bullet points.
    """
    lines = []

    # Time period + tone guidance
    period_name, guidance = _get_time_period()
    lines.append(f"- Time of day: {period_name}. {guidance}")

    # Calendar busyness
    busyness_score, busyness_text = _get_calendar_busyness()
    lines.append(f"- Calendar: {busyness_text}")

    # Hours since last interaction
    hours_since = _get_hours_since_last_interaction()
    if hours_since is not None:
        if hours_since < 0.1:
            pass  # Active conversation, no need to note
        elif hours_since < 1:
            lines.append(f"- Last interaction: {int(hours_since * 60)} minutes ago (active session).")
        elif hours_since < 8:
            lines.append(f"- Last interaction: {hours_since:.0f} hours ago.")
        else:
            lines.append(f"- Last interaction: {hours_since:.0f} hours ago. The user is returning after a break — consider a brief welcome back.")

    # Recent activity
    recent = _get_recent_activity_summary()
    if recent:
        lines.append(f"- Recent activity: user worked with {', '.join(recent)} in the last few hours.")

    # Urgent items
    urgents = _get_pending_urgents()
    if urgents:
        lines.append(f"- Urgent items: {'; '.join(urgents)}.")

    return "\n".join(lines)
