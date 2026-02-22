from __future__ import annotations

from littlehive.channels.telegram.auth import TelegramAllowlistAuth
from littlehive.core.config.schema import TelegramChannelConfig


def test_allowlist_auth_owner_and_allowed_ids():
    auth = TelegramAllowlistAuth(
        TelegramChannelConfig(enabled=True, owner_user_id=100, allow_user_ids=[101, 102])
    )
    assert auth.is_allowed(100)
    assert auth.is_allowed(101)
    assert not auth.is_allowed(999)
    assert auth.is_owner(100)
    assert not auth.is_owner(101)


def test_allowlist_auth_prefers_admin_service():
    class _Svc:
        def is_principal_chat_allowed(self, **kwargs):
            return kwargs["external_id"] == "42"

        def is_principal_owner(self, **kwargs):
            return kwargs["external_id"] == "42"

    auth = TelegramAllowlistAuth(
        TelegramChannelConfig(enabled=True, owner_user_id=100, allow_user_ids=[101, 102]),
        admin_service=_Svc(),
    )
    assert auth.is_allowed(42)
    assert auth.is_owner(42)
    assert not auth.is_allowed(100)
