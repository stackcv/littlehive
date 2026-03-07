import logging
import sqlite3
import queue
from logging.handlers import QueueHandler, QueueListener
from datetime import datetime
import os
from littlehive.agent.paths import DB_PATH

class SQLiteHandler(logging.Handler):
    def __init__(self, db_path):
        super().__init__()
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        # Initialize the table synchronously when the handler is created
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                level TEXT,
                module TEXT,
                message TEXT,
                traceback TEXT
            )
        ''')
        conn.commit()
        conn.close()

    def emit(self, record):
        try:
            # We want isoformat strings for easier sorting
            timestamp = datetime.fromtimestamp(record.created).isoformat()
            level = record.levelname
            module = record.module
            message = self.format(record)
            traceback = record.exc_text if record.exc_text else ""
            
            # Open a short-lived connection per emit
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO system_logs (timestamp, level, module, message, traceback)
                VALUES (?, ?, ?, ?, ?)
            ''', (timestamp, level, module, message, traceback))
            conn.commit()
            conn.close()
        except Exception:
            self.handleError(record)

def setup_logger():
    # Set up the main logger
    logger = logging.getLogger("littlehive")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    
    # We only add handlers if they aren't already added (avoid duplicate logs)
    if not logger.handlers:
        # 1. Create the SQLite handler (writes to DB)
        sqlite_handler = SQLiteHandler(DB_PATH)
        formatter = logging.Formatter('%(message)s')
        sqlite_handler.setFormatter(formatter)
        
        # 2. We use a queue to decouple the calling thread from the DB write thread
        # This makes logging non-blocking.
        log_queue = queue.Queue(-1)
        queue_handler = QueueHandler(log_queue)
        
        # 3. Create a QueueListener that reads from the queue and writes via sqlite_handler
        # It runs in its own background thread automatically
        listener = QueueListener(log_queue, sqlite_handler)
        listener.start()
        
        # 4. Attach the queue_handler to the logger
        logger.addHandler(queue_handler)
        
        # 5. Also log to standard output for CLI (optional, but good for tracking locally)
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(module)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(logging.INFO) # Keep terminal less noisy
        logger.addHandler(console_handler)
        
        # Save the listener to the logger instance so we can stop it on exit if needed
        logger.listener = listener

    return logger

def prune_logs(days_to_keep=7, max_records=10000):
    """
    Background job to prune logs older than `days_to_keep` or keep only `max_records`.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Delete by count (keep only top N latest)
        cursor.execute('''
            DELETE FROM system_logs 
            WHERE id NOT IN (
                SELECT id FROM system_logs 
                ORDER BY id DESC 
                LIMIT ?
            )
        ''', (max_records,))
        
        conn.commit()
        conn.close()
    except Exception as e:
        # Fallback to standard print if DB pruning fails
        print(f"[Prune Error] Failed to prune logs: {e}")

# Provide a singleton-like logger
logger = setup_logger()
