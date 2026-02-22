from __future__ import annotations

from littlehive.core.telemetry.logging import get_logger
from littlehive.core.telemetry.tracing import TraceContext, trace_event


def test_trace_event_emits_structured_fields(capsys):
    logger = get_logger("test.logger")
    ctx = TraceContext(
        request_id="req1",
        task_id="task1",
        session_id="sess1",
        agent_id="agent1",
        phase="phase0",
    )

    trace_event(logger, ctx, event="hello", status="ok", extra={"k": "v"})
    out = capsys.readouterr().out
    assert '"event": "hello"' in out
    assert '"request_id": "req1"' in out
    assert '"task_id": "task1"' in out
    assert '"status": "ok"' in out
