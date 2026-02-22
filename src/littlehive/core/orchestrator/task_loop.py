from __future__ import annotations

from dataclasses import dataclass

from littlehive.core.context.budget import TokenBudget, TokenBudgetPreflight
from littlehive.core.context.compiler import ContextCompiler
from littlehive.core.orchestrator.router import TaskRouter
from littlehive.core.telemetry.logging import get_logger
from littlehive.core.telemetry.tracing import TraceContext, trace_event


@dataclass(slots=True)
class DummyTaskRequest:
    request_id: str
    session_id: str
    task_id: str
    prompt: str


@dataclass(slots=True)
class DummyTaskResult:
    task_id: str
    status: str
    response_text: str


class DummyTaskPipeline:
    def __init__(self) -> None:
        self.logger = get_logger("littlehive.pipeline")
        self.router = TaskRouter()
        self.compiler = ContextCompiler()
        self.preflight = TokenBudgetPreflight()

    def run(self, request: DummyTaskRequest) -> DummyTaskResult:
        trace = TraceContext(
            request_id=request.request_id,
            task_id=request.task_id,
            session_id=request.session_id,
            agent_id="orchestrator_agent",
            phase="phase0",
        )
        trace_event(self.logger, trace, event="pipeline_start", status="ok")

        route = self.router.route(intent="dummy")
        compiled = self.compiler.compile(prompt=request.prompt, route_target=route.target_agent)
        budget = TokenBudget(max_input_tokens=2048, reserved_output_tokens=256)
        preflight = self.preflight.check(compiled_text=compiled, budget=budget)

        trace_event(
            self.logger,
            trace,
            event="preflight_complete",
            status="ok" if preflight.allowed else "blocked",
            extra={"estimated_input_tokens": preflight.estimated_input_tokens},
        )

        return DummyTaskResult(
            task_id=request.task_id,
            status="ok" if preflight.allowed else "blocked",
            response_text="dummy-response",
        )


def run_dummy_task_pipeline() -> DummyTaskResult:
    pipeline = DummyTaskPipeline()
    request = DummyTaskRequest(
        request_id="req-phase0",
        session_id="sess-phase0",
        task_id="task-phase0",
        prompt="hello from phase0",
    )
    return pipeline.run(request)
