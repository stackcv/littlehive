from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TransferSummary:
    from_agent: str
    to_agent: str
    summary: str
