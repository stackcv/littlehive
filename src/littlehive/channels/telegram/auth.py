from __future__ import annotations

from littlehive.core.config.schema import TelegramChannelConfig


class TelegramAllowlistAuth:
    def __init__(self, cfg: TelegramChannelConfig) -> None:
        allowed = set(cfg.allow_user_ids)
        if cfg.owner_user_id is not None:
            allowed.add(cfg.owner_user_id)
        self.allowed_user_ids = allowed
        self.owner_user_id = cfg.owner_user_id

    def is_allowed(self, user_id: int) -> bool:
        if not self.allowed_user_ids:
            return False
        return user_id in self.allowed_user_ids

    def is_owner(self, user_id: int) -> bool:
        return self.owner_user_id is not None and user_id == self.owner_user_id
