from __future__ import annotations


def reduce_context(items: list[str], max_items: int) -> list[str]:
    return items[-max_items:]
