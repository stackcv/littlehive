from __future__ import annotations

from littlehive.core.memory.cards import compact_memory_cards_from_turns, make_failure_fix_card


def test_memory_card_compaction_typed_outputs():
    turns = [
        "remember my favorite editor is vim",
        "we decided to ship on friday",
        "todo: follow up with qa",
        "ok",
    ]
    cards = compact_memory_cards_from_turns(turns, max_cards=5)
    types = {c.card_type for c in cards}
    assert "preference" in types
    assert "decision" in types
    assert "open_loop" in types


def test_failure_fix_card_support():
    card = make_failure_fix_card("timeout/provider", "reduce timeout and retry once", source="provider")
    assert card.card_type == "failure_fix"
    assert "timeout/provider" in (card.error_signature or "")
