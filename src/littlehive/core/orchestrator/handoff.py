from __future__ import annotations

from pydantic import BaseModel, Field


class TransferTraceContext(BaseModel):
    request_id: str
    task_id: str
    session_id: str


class TransferBudget(BaseModel):
    max_input_tokens: int
    reserved_output_tokens: int


class Transfer(BaseModel):
    target_agent: str
    subtask: str
    input_summary: str
    constraints: list[str] = Field(default_factory=list)
    expected_output_format: str = "json"
    budget: TransferBudget
    relevant_memory_ids: list[int] = Field(default_factory=list)
    fallback_policy: str = "return_partial"
    trace_context: TransferTraceContext


class TransferSummary(BaseModel):
    from_agent: str
    to_agent: str
    summary: str
