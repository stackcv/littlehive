from __future__ import annotations

from littlehive.core.orchestrator.task_loop import run_dummy_task_pipeline


def test_dummy_task_pipeline_returns_dummy_response():
    result = run_dummy_task_pipeline()
    assert result.status == "ok"
    assert result.response_text == "dummy-response"
