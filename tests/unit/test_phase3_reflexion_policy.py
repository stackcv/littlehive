from __future__ import annotations

from littlehive.core.runtime.recovery import reflexion_lite_decide, should_trigger_reflexion


def test_reflexion_guardrails_max_attempts_and_trigger_conditions():
    assert should_trigger_reflexion(error_retryable=True, attempts_used=0, max_per_step=1, safe_mode=True) is True
    assert should_trigger_reflexion(error_retryable=True, attempts_used=1, max_per_step=1, safe_mode=True) is False
    assert should_trigger_reflexion(error_retryable=False, attempts_used=0, max_per_step=1, safe_mode=False) is False


def test_safe_mode_toggles_recovery_strategy():
    d1 = reflexion_lite_decide(error_summary="timeout while calling provider", has_fallback_provider=True, safe_mode=False)
    d2 = reflexion_lite_decide(error_summary="timeout while calling provider", has_fallback_provider=True, safe_mode=True)
    assert d1.strategy in {"switch_provider", "retry_same"}
    assert d2.strategy != "switch_provider"
