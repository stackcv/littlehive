import sqlite3
import json
import logging
from datetime import datetime, timedelta, timezone
import os

from littlehive.agent.paths import DB_PATH
from littlehive.agent.logger_setup import logger

def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_cache_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = _get_db()
    cursor = conn.cursor()
    
    # Cached Emails (Last 24 hours)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cached_emails (
            id TEXT PRIMARY KEY,
            thread_id TEXT,
            sender TEXT,
            subject TEXT,
            snippet TEXT,
            date TEXT,
            is_read BOOLEAN,
            timestamp_ms INTEGER
        )
    """)
    
    # Cached Events (Today + Next 3 Days)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cached_events (
            id TEXT PRIMARY KEY,
            summary TEXT,
            start_time TEXT,
            end_time TEXT,
            description TEXT,
            attendees TEXT,
            hangout_link TEXT
        )
    """)
    
    # Cached Google Tasks
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cached_tasks (
            id TEXT PRIMARY KEY,
            list_id TEXT,
            title TEXT,
            notes TEXT,
            status TEXT,
            due TEXT,
            updated TEXT
        )
    """)
    
    # Sync State
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sync_state (
            service TEXT PRIMARY KEY,
            last_sync_timestamp INTEGER,
            last_history_id TEXT
        )
    """)
    
    conn.commit()
    conn.close()

# --- Sync State ---
def get_sync_state(service: str):
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sync_state WHERE service = ?", (service,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_sync_state(service: str, timestamp_ms: int = None, history_id: str = None):
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO sync_state (service, last_sync_timestamp, last_history_id)
        VALUES (?, ?, ?)
        ON CONFLICT(service) DO UPDATE SET 
            last_sync_timestamp=coalesce(?, last_sync_timestamp),
            last_history_id=coalesce(?, last_history_id)
    """, (service, timestamp_ms, history_id, timestamp_ms, history_id))
    conn.commit()
    conn.close()

# --- Email Cache ---
def upsert_emails(emails: list):
    if not emails:
        return
    conn = _get_db()
    cursor = conn.cursor()
    for e in emails:
        cursor.execute("""
            INSERT INTO cached_emails (id, thread_id, sender, subject, snippet, date, is_read, timestamp_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET 
                is_read=excluded.is_read, 
                snippet=excluded.snippet
        """, (
            e['id'], 
            e.get('thread_id'), 
            e.get('sender'), 
            e.get('subject'), 
            e.get('snippet'), 
            e.get('date'), 
            e.get('is_read', False),
            e.get('timestamp_ms')
        ))
    conn.commit()
    conn.close()

def cleanup_old_emails():
    """Removes emails older than 24 hours."""
    conn = _get_db()
    cursor = conn.cursor()
    cutoff = int((datetime.now(timezone.utc) - timedelta(hours=24)).timestamp() * 1000)
    cursor.execute("DELETE FROM cached_emails WHERE timestamp_ms < ?", (cutoff,))
    conn.commit()
    conn.close()

def query_cached_emails(query: str = None, limit: int = 10) -> str:
    """Read tool replacement for emails."""
    conn = _get_db()
    cursor = conn.cursor()
    
    sql = "SELECT id, thread_id, sender, subject, snippet, date, is_read FROM cached_emails"
    params = []
    
    if query and "is:unread" in query:
        sql += " WHERE is_read = 0"
    
    sql += " ORDER BY timestamp_ms DESC LIMIT ?"
    params.append(limit)
    
    cursor.execute(sql, tuple(params))
    rows = cursor.fetchall()
    conn.close()
    
    emails = []
    for r in rows:
        emails.append({
            "id": r["id"],
            "thread_id": r["thread_id"],
            "sender": r["sender"],
            "subject": r["subject"],
            "snippet": r["snippet"],
            "date": r["date"],
            "is_read": bool(r["is_read"])
        })
    
    return json.dumps({"emails": emails, "source": "local_cache", "message": "Showing emails from the last 24 hours."})

# --- Event Cache ---
def replace_cached_events(events: list):
    """Since we just pull 'Today + 3 Days', we can safely clear and rewrite this window."""
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cached_events") # Clear all existing events in the window
    for evt in events:
        cursor.execute("""
            INSERT INTO cached_events (id, summary, start_time, end_time, description, attendees, hangout_link)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            evt['id'], 
            evt.get('summary'), 
            evt.get('start'), 
            evt.get('end'), 
            evt.get('description'), 
            json.dumps(evt.get('attendees', [])),
            evt.get('hangout_link')
        ))
    conn.commit()
    conn.close()

def query_cached_events(time_min: str = None, time_max: str = None) -> str:
    """Read tool replacement for events."""
    conn = _get_db()
    cursor = conn.cursor()
    
    sql = "SELECT * FROM cached_events"
    params = []
    
    if time_min or time_max:
        sql += " WHERE 1=1"
        if time_min:
            sql += " AND start_time >= ?"
            params.append(time_min)
        if time_max:
            sql += " AND start_time <= ?"
            params.append(time_max)
            
    sql += " ORDER BY start_time ASC"
    
    cursor.execute(sql, tuple(params))
    rows = cursor.fetchall()
    conn.close()
    
    events = []
    for r in rows:
        events.append({
            "id": r["id"],
            "summary": r["summary"],
            "start": r["start_time"],
            "end": r["end_time"],
            "description": r["description"],
            "attendees": json.loads(r["attendees"]) if r["attendees"] else [],
            "hangout_link": r["hangout_link"]
        })
    
    return json.dumps(events)

# --- Google Tasks Cache ---
def replace_cached_tasks(tasks: list):
    """Clears and rewrites cached tasks."""
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cached_tasks")
    for t in tasks:
        cursor.execute("""
            INSERT INTO cached_tasks (id, list_id, title, notes, status, due, updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            t['id'], 
            t.get('list_id'), 
            t.get('title'), 
            t.get('notes'), 
            t.get('status'), 
            t.get('due'),
            t.get('updated')
        ))
    conn.commit()
    conn.close()

def query_cached_tasks(list_id: str = None, status: str = None) -> str:
    """Read tool replacement for tasks."""
    conn = _get_db()
    cursor = conn.cursor()
    
    sql = "SELECT * FROM cached_tasks"
    params = []
    
    if list_id or status:
        sql += " WHERE 1=1"
        if list_id:
            sql += " AND list_id = ?"
            params.append(list_id)
        if status:
            sql += " AND status = ?"
            params.append(status)
            
    sql += " ORDER BY updated DESC"
    
    cursor.execute(sql, tuple(params))
    rows = cursor.fetchall()
    conn.close()
    
    tasks = []
    for r in rows:
        tasks.append({
            "id": r["id"],
            "list_id": r["list_id"],
            "title": r["title"],
            "notes": r["notes"],
            "status": r["status"],
            "due": r["due"],
            "updated": r["updated"]
        })
    
    return json.dumps(tasks)
