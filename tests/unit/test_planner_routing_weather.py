from __future__ import annotations

from littlehive.core.agents.planner_agent import PlannerAgent


def test_planner_routes_weather_queries_to_execution_transfer():
    agent = PlannerAgent()
    out = agent.plan(
        user_text="What is the weather in Pune today?",
        session_id="1",
        task_id="1",
        request_id="r1",
        max_input_tokens=800,
        reserved_output_tokens=128,
    )
    assert out.transfer is not None
    assert "execute_tools" in out.plan_steps
