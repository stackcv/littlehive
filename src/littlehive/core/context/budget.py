from __future__ import annotations

from dataclasses import dataclass

from littlehive.core.context.token_estimator import TokenEstimator


@dataclass(slots=True)
class TokenBudget:
    max_input_tokens: int
    reserved_output_tokens: int


@dataclass(slots=True)
class PreflightResult:
    allowed: bool
    estimated_input_tokens: int


class TokenBudgetPreflight:
    def __init__(self) -> None:
        self.estimator = TokenEstimator()

    def check(self, compiled_text: str, budget: TokenBudget) -> PreflightResult:
        est = self.estimator.estimate(compiled_text)
        return PreflightResult(allowed=est <= budget.max_input_tokens, estimated_input_tokens=est)
