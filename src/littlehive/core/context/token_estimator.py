from __future__ import annotations

try:
    import tiktoken
except Exception:  # noqa: BLE001
    tiktoken = None


class TokenEstimator:
    def __init__(self) -> None:
        self._encoding = None
        if tiktoken is not None:
            try:
                self._encoding = tiktoken.get_encoding("cl100k_base")
            except Exception:  # noqa: BLE001
                self._encoding = None

    def estimate(self, text: str) -> int:
        if self._encoding is not None:
            try:
                return max(1, len(self._encoding.encode(text or "")))
            except Exception:  # noqa: BLE001
                pass
        return max(1, (len(text) + 3) // 4)
