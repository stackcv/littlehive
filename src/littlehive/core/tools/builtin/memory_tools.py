from __future__ import annotations

from littlehive.core.memory.retrieval import search_memories
from littlehive.core.memory.store import MemoryStore
from littlehive.core.memory.summarizer import summarize_recent_messages, upsert_session_summary
from littlehive.core.tools.base import ToolCallContext, ToolMetadata


def register_memory_tools(registry, db_session_factory):
    def memory_search(ctx: ToolCallContext, args: dict) -> dict:
        query = (args.get("query") or "").strip()
        top_k = int(args.get("top_k", 3))
        with db_session_factory() as db:
            hits = search_memories(db, session_id=ctx.session_db_id, query=query, top_k=top_k)
            return {"items": [{"id": m.id, "content": m.content[:160]} for m in hits]}

    def memory_write(ctx: ToolCallContext, args: dict) -> dict:
        text = (args.get("content") or "").strip()
        if not text:
            return {"status": "ignored", "reason": "empty"}
        with db_session_factory() as db:
            row = MemoryStore(db).write(ctx.session_db_id, ctx.user_db_id, text, memory_type="note")
            db.commit()
            return {"status": "ok", "memory_id": row.id}

    def memory_summarize(ctx: ToolCallContext, args: dict) -> dict:
        _ = args
        with db_session_factory() as db:
            summary = summarize_recent_messages(db, ctx.session_db_id)
            row = upsert_session_summary(db, ctx.session_db_id, summary)
            db.commit()
            return {"status": "ok", "summary_id": row.id, "summary": row.summary}

    registry.register(
        ToolMetadata(
            name="memory.search",
            routing_summary="Search compact memories by keyword.",
            invocation_summary="memory.search(query, top_k)",
            full_schema={"type": "object", "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}}},
        ),
        memory_search,
    )
    registry.register(
        ToolMetadata(
            name="memory.write",
            routing_summary="Write a short memory record.",
            invocation_summary="memory.write(content)",
            full_schema={"type": "object", "properties": {"content": {"type": "string"}}},
        ),
        memory_write,
    )
    registry.register(
        ToolMetadata(
            name="memory.summarize",
            routing_summary="Update session summary from recent turns.",
            invocation_summary="memory.summarize()",
            full_schema={"type": "object", "properties": {}},
        ),
        memory_summarize,
    )
