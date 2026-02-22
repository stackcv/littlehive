from __future__ import annotations


class TokenEstimator:
    def estimate(self, text: str) -> int:
        return max(1, (len(text) + 3) // 4)
