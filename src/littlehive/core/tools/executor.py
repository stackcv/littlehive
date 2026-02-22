from __future__ import annotations

from collections.abc import Callable

from littlehive.core.telemetry.tracing import TraceContext, trace_event
from littlehive.core.tools.base import ToolCallContext
from littlehive.core.tools.registry import ToolRegistry


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        logger,
        call_logger: Callable[[ToolCallContext, str, str, str], None] | None = None,
    ) -> None:
        self.registry = registry
        self.logger = logger
        self.call_logger = call_logger

    def execute(self, tool_name: str, ctx: ToolCallContext, args: dict) -> dict:
        handler = self.registry.get_handler(tool_name)
        trace = TraceContext(
            request_id=ctx.trace_id,
            task_id=str(ctx.task_id or ""),
            session_id=str(ctx.session_db_id),
            agent_id="tool_executor",
            phase="phase1",
        )
        if handler is None:
            trace_event(self.logger, trace, event="tool_call", status="error", extra={"tool_name": tool_name})
            if self.call_logger:
                self.call_logger(ctx, tool_name, "error", "not_registered")
            raise ValueError(f"Tool not registered: {tool_name}")

        result = handler(ctx, args)
        trace_event(self.logger, trace, event="tool_call", status="ok", extra={"tool_name": tool_name})
        if self.call_logger:
            self.call_logger(ctx, tool_name, "ok", "")
        return result
