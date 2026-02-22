from __future__ import annotations

import pytest

from littlehive.core.runtime.recovery import reflexion_lite_decide


def test_tool_failure_reflexion_lite_strategy_selection():
    d = reflexion_lite_decide(error_summary="tool timeout while running memory.search", has_fallback_provider=False, safe_mode=False)
    assert d.strategy in {"retry_same", "reduce_context", "skip_tool"}


@pytest.mark.asyncio
async def test_safe_mode_prefers_conservative_recovery():
    d = reflexion_lite_decide(error_summary="timeout provider", has_fallback_provider=True, safe_mode=True)
    assert d.strategy != "switch_provider"
