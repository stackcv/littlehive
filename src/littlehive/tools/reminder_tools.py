import os
from littlehive.agent.logger_setup import logger
import sqlite3
import json
from datetime import datetime, timedelta, timezone

from littlehive.agent.paths import DB_PATH

def _init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task TEXT NOT NULL,
            deadline TEXT NOT NULL,
            next_notification TEXT NOT NULL,
            status TEXT DEFAULT 'pending'
        )
    ''')
    try:
        c.execute('ALTER TABLE reminders ADD COLUMN priority TEXT DEFAULT "normal"')
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

_init_db()

def set_reminder(task: str, reminder_time: str, priority: str = "normal") -> str:
    """Creates a new reminder in the database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('INSERT INTO reminders (task, deadline, next_notification, status, priority) VALUES (?, ?, ?, ?, ?)',
                  (task, reminder_time, reminder_time, 'pending', priority))
        r_id = c.lastrowid
        conn.commit()
        conn.close()
        return json.dumps({"status": "success", "message": f"Reminder set successfully with {priority} priority.", "id": r_id})
    except Exception as e:
        return json.dumps({"error": str(e)})

def mark_reminder_completed(reminder_id: int) -> str:
    """Marks a reminder as done so it stops notifying the user."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE reminders SET status = 'completed' WHERE id = ?", (reminder_id,))
        if c.rowcount == 0:
            conn.close()
            return json.dumps({"error": f"No reminder found with ID {reminder_id}"})
        conn.commit()
        conn.close()
        return json.dumps({"status": "success", "message": f"Reminder #{reminder_id} marked as completed."})
    except Exception as e:
        return json.dumps({"error": str(e)})

def get_pending_reminders() -> str:
    """Gets all pending reminders."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT id, task, deadline, priority FROM reminders WHERE status = 'pending' ORDER BY datetime(deadline) ASC")
        rows = c.fetchall()
        conn.close()
        if not rows:
            return json.dumps({"message": "No pending reminders."})
        return json.dumps([dict(row) for row in rows])
    except Exception as e:
        return json.dumps({"error": str(e)})

def poll_due_reminders(skip_non_critical: bool = False) -> list:
    """Used strictly by the background worker to fetch due items."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        
        query = "SELECT * FROM reminders WHERE status = 'pending' AND datetime(next_notification) <= datetime(?)"
        if skip_non_critical:
            query += " AND priority = 'critical'"
            
        c.execute(query, (now,))
        rows = c.fetchall()
        
        due_reminders = []
        current_time = datetime.now(timezone.utc)
        for row in rows:
            row_dict = dict(row)
            due_reminders.append(row_dict)
            priority = row_dict.get('priority', 'normal')
            
            # SMART SNOOZE LOGIC based on priority
            if priority == 'critical':
                next_time = (current_time + timedelta(minutes=15)).isoformat()
            elif priority == 'low':
                next_time = (current_time + timedelta(hours=6)).isoformat()
            else: # normal
                next_time = (current_time + timedelta(hours=2)).isoformat()
                
            c.execute("UPDATE reminders SET next_notification = ? WHERE id = ?", (next_time, row_dict['id']))
            
        conn.commit()
        conn.close()
        return due_reminders
    except Exception as e:
        logger.error(f"[Reminders DB] Error: {e}")
        return []

REMINDER_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "Set a reminder for the user. Use this when the user asks to be reminded of a task or bill.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "The task or event to remember."},
                    "reminder_time": {"type": "string", "description": "ISO 8601 format WITH timezone offset (e.g. 2026-03-05T14:00:00+05:30) indicating when the reminder should fire."},
                    "priority": {"type": "string", "enum": ["low", "normal", "critical"], "description": "Priority of the reminder. Low/Normal are suppressed during meetings and sleeping hours. Critical will interrupt meetings."}
                },
                "required": ["task", "reminder_time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mark_reminder_completed",
            "description": "Mark a reminder as completed. Use this once the user confirms they have taken action on a reminder so it stops following up.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "integer", "description": "The ID of the reminder to mark done."}
                },
                "required": ["reminder_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_pending_reminders",
            "description": "Retrieve a list of all pending reminders and their IDs.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]

def execute_tool(name: str, args: dict) -> str:
    funcs = {
        "set_reminder": set_reminder,
        "mark_reminder_completed": mark_reminder_completed,
        "get_pending_reminders": get_pending_reminders
    }
    return funcs[name](**args) if name in funcs else json.dumps({"error": "Unknown tool"})
