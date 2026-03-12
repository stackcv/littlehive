import json
import urllib.request
import urllib.parse
from littlehive.tools.task_queue import queue_task
from littlehive.agent.config import get_config


def _resolve_telegram_chat_id(recipient: str) -> str | None:
    """Resolve a recipient string to a Telegram chat ID.
    Matches aliases ('me', 'boss', 'owner', 'user') and the configured user_name."""
    config = get_config()
    owner_aliases = {"me", "boss", "owner", "user"}
    user_name = config.get("user_name", "").strip().lower()

    recipient_lower = recipient.strip().lower()

    if recipient_lower in owner_aliases or (user_name and recipient_lower == user_name):
        return str(config.get("telegram_chat_id", ""))

    # If it looks like a numeric chat ID already, use it directly
    if recipient.lstrip("-").isdigit():
        return recipient

    return None


def send_channel_message(channel: str, recipient: str, message: str) -> str:
    """Queue a message to be sent asynchronously."""
    return queue_task(
        "send_channel_message",
        {"channel": channel, "recipient": recipient, "message": message},
    )


def _actual_send_channel_message(channel: str, recipient: str, message: str) -> str:
    """Implementation for actually sending a message to a channel."""
    channel = channel.lower()

    if channel == "telegram":
        config = get_config()
        bot_token = config.get("telegram_bot_token")

        if not bot_token:
            return json.dumps({"error": "Telegram bot token is not configured."})

        chat_id = _resolve_telegram_chat_id(recipient)
        if not chat_id:
            return json.dumps({"error": f"Cannot resolve '{recipient}' to a Telegram chat ID. Use 'me' for the owner or provide a numeric chat ID."})

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode("utf-8")

        try:
            req = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode())
                if result.get("ok"):
                    return json.dumps({"status": "success", "message": "Message sent via Telegram."})
                else:
                    return json.dumps({"error": f"Telegram API error: {result.get('description')}"})
        except Exception as e:
            return json.dumps({"error": f"Failed to send Telegram message: {str(e)}"})

    return json.dumps({"error": f"Channel '{channel}' is not supported."})


MESSAGING_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "send_channel_message",
            "description": "Send an immediate message via Telegram. For reminders or scheduled notifications, use set_reminder instead. For emails, use send_email instead.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel": {
                        "type": "string",
                        "description": "The channel: 'telegram'.",
                    },
                    "recipient": {
                        "type": "string",
                        "description": "Use 'me' to send to the owner. Otherwise, provide a numeric Telegram chat ID.",
                    },
                    "message": {
                        "type": "string",
                        "description": "The message text.",
                    },
                },
                "required": ["channel", "recipient", "message"],
            },
        },
    }
]


def execute_tool(name: str, args: dict) -> str:
    funcs = {
        "send_channel_message": send_channel_message,
    }
    return (
        funcs[name](**args) if name in funcs else json.dumps({"error": "Unknown tool"})
    )
