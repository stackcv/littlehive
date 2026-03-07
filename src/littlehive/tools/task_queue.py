import sqlite3
import os
import json
from datetime import datetime, timedelta

from littlehive.agent.paths import DB_PATH

def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_queue_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name TEXT NOT NULL,
            arguments TEXT NOT NULL,
            status TEXT DEFAULT 'queued',
            retry_count INTEGER DEFAULT 0,
            next_run_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            error_message TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_queue_db()

def queue_task(tool_name: str, arguments: dict) -> str:
    '''Inserts a task into the database queue for async execution.'''
    conn = _get_db()
    cursor = conn.cursor()
    now = datetime.now()
    cursor.execute('''
        INSERT INTO pending_tasks (tool_name, arguments, next_run_at) 
        VALUES (?, ?, ?)
    ''', (tool_name, json.dumps(arguments), now.strftime('%Y-%m-%d %H:%M:%S')))
    task_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return json.dumps({
        'status': 'queued', 
        'task_id': task_id,
        'message': f"Action '{tool_name}' has been successfully queued for background execution. Please inform the user that it will be done shortly."
    })

def check_task_status(query: str = None) -> str:
    '''
    Tool for LLM to check the status of queued asynchronous tasks (emails, calendar invites).
    '''
    conn = _get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, tool_name, status, retry_count, datetime(created_at, 'localtime') as created_at_local, error_message 
        FROM pending_tasks 
        ORDER BY created_at DESC LIMIT 10
    ''')
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return json.dumps({'status': 'empty', 'message': 'No tasks in the queue.'})
        
    tasks = []
    for r in rows:
        tasks.append({
            'id': r['id'],
            'tool': r['tool_name'],
            'status': r['status'],
            'retry_count': r['retry_count'],
            'created_at': r['created_at_local'],
            'error_message': r['error_message']
        })
        
    return json.dumps({'tasks': tasks})

QUEUE_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "check_task_status",
            "description": "Check the status of asynchronous background tasks (like sending emails, creating calendar events). Use this when the user asks 'did you send it?' or 'is it done?'",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional search query to filter tasks. Leave empty to get recent tasks."
                    }
                }
            }
        }
    }
]

def execute_queue_tool(name: str, args: dict) -> str:
    if name == 'check_task_status':
        return check_task_status(args.get('query'))
    return json.dumps({'error': 'Unknown queue tool'})
