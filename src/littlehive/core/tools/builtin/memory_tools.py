from __future__ import annotations

from littlehive.core.memory.cards import (
    compact_memory_cards_from_turns,
    make_failure_fix_card,
    should_persist_memory,
)
from littlehive.core.memory.retrieval import retrieve_memory_cards
from littlehive.core.memory.store import MemoryStore
from littlehive.core.memory.summarizer import persist_summary_card, summarize_recent_messages, upsert_session_summary
from littlehive.core.tools.base import ToolCallContext, ToolMetadata


def register_memory_tools(registry, db_session_factory):
    def memory_search(ctx: ToolCallContext, args: dict) -> dict:
        query = (args.get("query") or "").strip()
        top_k = int(args.get("top_k", 4))
        with db_session_factory() as db:
            hits = retrieve_memory_cards(db, session_id=ctx.session_db_id, query=query, top_k=top_k)
            return {"items": hits}

    def memory_write(ctx: ToolCallContext, args: dict) -> dict:
        text = (args.get("content") or "").strip()
        if not text:
            return {"status": "ignored", "reason": "empty"}
        if not should_persist_memory(text):
            return {"status": "ignored", "reason": "not_reusable"}

        with db_session_factory() as db:
            store = MemoryStore(db)
            cards = compact_memory_cards_from_turns([text], max_cards=1)
            if not cards:
                return {"status": "ignored", "reason": "no_card"}
            row = store.write_card(ctx.session_db_id, ctx.user_db_id, cards[0])
            db.commit()
            return {"status": "ok", "memory_id": row.id, "card_type": row.card_type}

    def memory_summarize(ctx: ToolCallContext, args: dict) -> dict:
        _ = args
        with db_session_factory() as db:
            summary = summarize_recent_messages(db, ctx.session_db_id)
            row = upsert_session_summary(db, ctx.session_db_id, summary)
            card_id = persist_summary_card(db, ctx.session_db_id, ctx.user_db_id, summary)
            db.commit()
            return {"status": "ok", "summary_id": row.id, "summary_card_id": card_id, "summary": row.summary}

    def memory_failure_fix(ctx: ToolCallContext, args: dict) -> dict:
        signature = (args.get("error_signature") or "").strip()
        fix = (args.get("fix") or "").strip()
        source = (args.get("source") or "runtime").strip()
        if not signature or not fix:
            return {"status": "ignored", "reason": "missing_fields"}
        with db_session_factory() as db:
            row = MemoryStore(db).write_card(
                ctx.session_db_id,
                ctx.user_db_id,
                make_failure_fix_card(signature, fix, source=source),
            )
            db.commit()
            return {"status": "ok", "memory_id": row.id, "card_type": row.card_type}

    registry.register(
        ToolMetadata(
            name="memory.search",
            version="2.0",
            risk_level="low",
            tags=["memory", "search", "retrieval"],
            routing_summary="Find top compact memory cards relevant to a query.",
            invocation_summary="memory.search(query, top_k=4) returns compact snippets.",
            full_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}, "top_k": {"type": "integer", "minimum": 1, "maximum": 8}},
                "required": ["query"],
            },
            examples=["memory.search(query='user preferences', top_k=3)"],
            timeout_sec=8,
            idempotent=True,
            permission_required="none",
        ),
        memory_search,
    )
    registry.register(
        ToolMetadata(
            name="memory.write",
            version="2.0",
            risk_level="low",
            tags=["memory", "write", "card"],
            routing_summary="Write reusable info as typed compact memory card.",
            invocation_summary="memory.write(content) stores fact/decision/preference/open_loop.",
            full_schema={
                "type": "object",
                "properties": {"content": {"type": "string", "maxLength": 1000}},
                "required": ["content"],
            },
            examples=["memory.write(content='Remember my timezone is Asia/Kolkata')"],
            timeout_sec=8,
            idempotent=False,
            permission_required="none",
        ),
        memory_write,
    )
    registry.register(
        ToolMetadata(
            name="memory.summarize",
            version="2.0",
            risk_level="low",
            tags=["memory", "summary", "compaction"],
            routing_summary="Refresh session summary and write a session_summary card.",
            invocation_summary="memory.summarize() updates summary state from recent turns.",
            full_schema={"type": "object", "properties": {}},
            examples=["memory.summarize()"],
            timeout_sec=8,
            idempotent=False,
            permission_required="none",
        ),
        memory_summarize,
    )
    registry.register(
        ToolMetadata(
            name="memory.failure_fix",
            version="2.0",
            risk_level="low",
            tags=["memory", "failure_fix", "recovery"],
            routing_summary="Store compact error->fix learning card for future recovery.",
            invocation_summary="memory.failure_fix(error_signature, fix, source='tool|provider|agent').",
            full_schema={
                "type": "object",
                "properties": {
                    "error_signature": {"type": "string"},
                    "fix": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["error_signature", "fix"],
            },
            examples=["memory.failure_fix(error_signature='timeout:x', fix='retry with lower top_k', source='provider')"],
            timeout_sec=8,
            idempotent=False,
            permission_required="none",
        ),
        memory_failure_fix,
    )
