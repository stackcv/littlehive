from __future__ import annotations

from pydantic import BaseModel, Field


CARD_TYPES = {"fact", "decision", "preference", "open_loop", "session_summary", "failure_fix"}


class MemoryCard(BaseModel):
    card_type: str
    content: str
    pinned: bool = False
    error_signature: str | None = None
    fix_text: str | None = None
    source: str = "runtime"
    confidence: float = 0.5
    success_count: int = 0
    tags: list[str] = Field(default_factory=list)


def classify_card_type(text: str) -> str:
    t = text.lower()
    if "prefer" in t or "favorite" in t:
        return "preference"
    if "decide" in t or "decided" in t or "decision" in t:
        return "decision"
    if "todo" in t or "later" in t or "follow up" in t:
        return "open_loop"
    return "fact"


def should_persist_memory(text: str) -> bool:
    t = text.lower().strip()
    if len(t) < 10:
        return False
    if any(k in t for k in ["remember", "prefer", "decision", "decide", "decided", "todo", "follow up", "favorite", "my "]):
        return True
    return False


def compact_memory_cards_from_turns(turns: list[str], max_cards: int = 3) -> list[MemoryCard]:
    cards: list[MemoryCard] = []
    seen: set[str] = set()
    for turn in turns:
        if not should_persist_memory(turn):
            continue
        normalized = " ".join(turn.lower().split())
        if normalized in seen:
            continue
        seen.add(normalized)
        card_type = classify_card_type(turn)
        compact = turn.strip()[:300]
        cards.append(MemoryCard(card_type=card_type, content=compact, tags=[card_type]))
        if len(cards) >= max_cards:
            break
    return cards


def make_session_summary_card(summary: str) -> MemoryCard:
    return MemoryCard(card_type="session_summary", content=summary[:900], tags=["summary"], confidence=0.7)


def make_failure_fix_card(error_signature: str, fix_text: str, source: str, success_count: int = 1) -> MemoryCard:
    return MemoryCard(
        card_type="failure_fix",
        content=f"error={error_signature}; fix={fix_text}"[:900],
        error_signature=error_signature[:256],
        fix_text=fix_text[:500],
        source=source[:64],
        confidence=0.8,
        success_count=success_count,
        tags=["failure_fix", source[:32]],
    )


def should_compact(turn_count: int, token_estimate: int, every_n_turns: int = 5, token_threshold: int = 1200) -> bool:
    return turn_count % every_n_turns == 0 or token_estimate >= token_threshold
