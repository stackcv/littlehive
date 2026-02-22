from __future__ import annotations

from littlehive.channels.telegram.adapter import TelegramRuntime


class TelegramHandlers:
    def __init__(self, runtime: TelegramRuntime) -> None:
        self.runtime = runtime

    async def handle_update(self, update, context) -> None:
        _ = context
        if update.effective_user is None or update.effective_chat is None or update.effective_message is None:
            return

        user_id = int(update.effective_user.id)
        chat_id = int(update.effective_chat.id)
        text = update.effective_message.text or ""
        response = await self.runtime.handle_user_text(user_id=user_id, chat_id=chat_id, text=text)
        await update.effective_message.reply_text(response)
