import queue

# The Inbox where all UIs send user messages to the Brain
inbox_queue = queue.Queue()

# The Outboxes where the Brain sends responses back to specific UIs
outbox_telegram = queue.Queue()
outbox_web = queue.Queue()

# Shared runtime stats updated by the brain, read by the dashboard API
context_stats = {"tokens_used": 0, "max_tokens": 131072, "messages": 0}

class MultiOutbox:
    def __init__(self, source, active_telegram_chat_id=None):
        self.source = source
        self.active_telegram_chat_id = active_telegram_chat_id
        
    def put(self, msg):
        if self.source == "proactive" or self.source == "web":
            outbox_web.put(msg)
        if self.source == "telegram" or (
            self.source == "proactive" and self.active_telegram_chat_id
        ):
            outbox_telegram.put(msg)
