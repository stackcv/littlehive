from __future__ import annotations

from littlehive.core.config.schema import TelegramChannelConfig


class TelegramAllowlistAuth:
    def __init__(self, cfg: TelegramChannelConfig, admin_service=None) -> None:
        allowed = set(cfg.allow_user_ids)
        if cfg.owner_user_id is not None:
            allowed.add(cfg.owner_user_id)
        self.allowed_user_ids = allowed
        self.owner_user_id = cfg.owner_user_id
        self.admin_service = admin_service

    def is_allowed(self, user_id: int) -> bool:
        if self.admin_service is not None:
            return self.admin_service.is_principal_chat_allowed(
                channel="telegram",
                external_id=str(int(user_id)),
                fallback_allowed_external_ids={str(int(x)) for x in self.allowed_user_ids},
            )
        if not self.allowed_user_ids:
            return False
        return user_id in self.allowed_user_ids

    def is_owner(self, user_id: int) -> bool:
        if self.admin_service is not None:
            fallback_owner = str(int(self.owner_user_id)) if self.owner_user_id is not None else None
            return self.admin_service.is_principal_owner(
                channel="telegram",
                external_id=str(int(user_id)),
                fallback_owner_external_id=fallback_owner,
            )
        return self.owner_user_id is not None and user_id == self.owner_user_id
