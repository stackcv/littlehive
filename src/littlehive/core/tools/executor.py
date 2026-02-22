from __future__ import annotations

from collections.abc import Callable
from time import perf_counter

from littlehive.core.permissions.policy_engine import PolicyEngine, RiskLevel
from littlehive.core.runtime.circuit_breaker import BreakerRegistry
from littlehive.core.runtime.errors import ErrorInfo, compact_error_summary
from littlehive.core.runtime.retries import RetryPolicy, run_with_retry_sync
from littlehive.core.runtime.timeouts import run_with_timeout_sync
from littlehive.core.telemetry.tracing import TraceContext, trace_event
from littlehive.core.tools.base import ToolCallContext
from littlehive.core.tools.registry import ToolRegistry


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        logger,
        call_logger: Callable[[ToolCallContext, str, str, str], None] | None = None,
        retry_policy: RetryPolicy | None = None,
        breaker_registry: BreakerRegistry | None = None,
        policy_engine: PolicyEngine | None = None,
        safe_mode_getter: Callable[[], bool] | None = None,
        create_confirmation: Callable[[ToolCallContext, str, dict], int] | None = None,
    ) -> None:
        self.registry = registry
        self.logger = logger
        self.call_logger = call_logger
        self.retry_policy = retry_policy or RetryPolicy(max_attempts=2, base_backoff_seconds=0.05, jitter_seconds=0.03)
        self.breakers = breaker_registry or BreakerRegistry(failure_threshold=4, cool_down_seconds=20)
        self.policy_engine = policy_engine or PolicyEngine()
        self.safe_mode_getter = safe_mode_getter or (lambda: True)
        self.create_confirmation = create_confirmation

    def execute(self, tool_name: str, ctx: ToolCallContext, args: dict) -> dict:
        handler = self.registry.get_handler(tool_name)
        meta = self.registry.get_metadata(tool_name)
        trace = TraceContext(
            request_id=ctx.trace_id,
            task_id=str(ctx.task_id or ""),
            session_id=str(ctx.session_db_id),
            agent_id="tool_executor",
            phase="phase3",
        )
        if handler is None or meta is None:
            trace_event(self.logger, trace, event="tool_call", status="error", extra={"tool_name": tool_name})
            if self.call_logger:
                self.call_logger(ctx, tool_name, "error", "not_registered")
            raise ValueError(f"Tool not registered: {tool_name}")

        try:
            risk = RiskLevel(meta.risk_level)
        except ValueError:
            risk = RiskLevel.MEDIUM
        decision = self.policy_engine.evaluate_tool_risk(risk_level=risk.value, safe_mode=self.safe_mode_getter())
        if not decision.allowed:
            trace_event(
                self.logger,
                trace,
                event="tool_call",
                status="blocked",
                extra={"tool_name": tool_name, "detail": decision.reason},
            )
            if self.call_logger:
                self.call_logger(ctx, tool_name, "blocked", decision.reason)
            raise PermissionError(f"tool blocked by permission policy: {decision.reason}")
        if decision.requires_confirmation:
            if self.create_confirmation is None:
                raise PermissionError("confirmation required but no confirmation backend configured")
            confirmation_id = self.create_confirmation(ctx, tool_name, args)
            trace_event(
                self.logger,
                trace,
                event="tool_call",
                status="waiting_confirmation",
                extra={"tool_name": tool_name, "confirmation_id": confirmation_id},
            )
            if self.call_logger:
                self.call_logger(ctx, tool_name, "waiting_confirmation", f"id={confirmation_id}")
            return {
                "status": "waiting_confirmation",
                "confirmation_id": confirmation_id,
                "tool_name": tool_name,
            }

        breaker = self.breakers.for_key(f"tool:{tool_name}")
        if not breaker.allow():
            detail = "blocked_by_circuit_breaker"
            trace_event(self.logger, trace, event="tool_call", status="blocked", extra={"tool_name": tool_name, "detail": detail})
            if self.call_logger:
                self.call_logger(ctx, tool_name, "blocked", detail)
            raise RuntimeError(f"tool blocked by circuit breaker: {tool_name}")

        def _invoke() -> dict:
            return run_with_timeout_sync(lambda: handler(ctx, args), timeout_seconds=meta.timeout_sec)

        policy = self.retry_policy if meta.idempotent else RetryPolicy(max_attempts=1, base_backoff_seconds=0.0, jitter_seconds=0.0)

        started = perf_counter()

        def _on_attempt(attempt: int, status: str, info: ErrorInfo | None) -> None:
            if attempt > 1:
                trace_event(
                    self.logger,
                    trace,
                    event="tool_retry",
                    status=status,
                    extra={"tool_name": tool_name, "attempt": attempt, "error_type": info.error_type if info else ""},
                )

        try:
            result = run_with_retry_sync(
                _invoke,
                policy=policy,
                category="tool",
                component=tool_name,
                on_attempt=_on_attempt,
            )
            elapsed_ms = round((perf_counter() - started) * 1000, 3)
            trace_event(self.logger, trace, event="tool_call", status="ok", extra={"tool_name": tool_name, "latency_ms": elapsed_ms})
            breaker.record_success()
            if self.call_logger:
                self.call_logger(ctx, tool_name, "ok", "")
            return result
        except Exception as exc:  # noqa: BLE001
            detail = compact_error_summary(exc)
            elapsed_ms = round((perf_counter() - started) * 1000, 3)
            trace_event(
                self.logger,
                trace,
                event="tool_call",
                status="error",
                extra={"tool_name": tool_name, "detail": detail, "latency_ms": elapsed_ms},
            )
            breaker.record_failure()
            if self.call_logger:
                self.call_logger(ctx, tool_name, "error", detail)
            raise
