from __future__ import annotations


class TokenEstimator:
    def estimate(self, text: str) -> int:
        # Phase 0 placeholder estimator.
        return max(1, len(text) // 4)
