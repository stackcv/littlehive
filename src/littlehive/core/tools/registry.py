from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from littlehive.core.tools.base import ToolHandler, ToolMetadata


@dataclass(slots=True)
class ToolShortlistItem:
    name: str
    tags: list[str]
    routing_summary: str
    invocation_summary: str
    score: float


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, tuple[ToolMetadata, ToolHandler]] = {}
        self._conn = sqlite3.connect(":memory:")
        self._conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS tool_docs_fts "
            "USING fts5(name, tags, routing_summary, invocation_summary)"
        )
        self._conn.execute("CREATE TABLE IF NOT EXISTS tool_docs_meta(name TEXT PRIMARY KEY, tags_json TEXT)")
        self._conn.commit()

    def register(self, metadata: ToolMetadata, handler: ToolHandler) -> None:
        self._tools[metadata.name] = (metadata, handler)
        tags_str = " ".join(metadata.tags)
        self._conn.execute("DELETE FROM tool_docs_fts WHERE name = ?", (metadata.name,))
        self._conn.execute("INSERT INTO tool_docs_fts(name, tags, routing_summary, invocation_summary) VALUES (?, ?, ?, ?)",
                           (metadata.name, tags_str, metadata.routing_summary, metadata.invocation_summary))
        self._conn.execute(
            "INSERT OR REPLACE INTO tool_docs_meta(name, tags_json) VALUES (?, ?)",
            (metadata.name, json.dumps(metadata.tags)),
        )
        self._conn.commit()

    def get_handler(self, name: str) -> ToolHandler | None:
        item = self._tools.get(name)
        return item[1] if item else None

    def get_metadata(self, name: str) -> ToolMetadata | None:
        item = self._tools.get(name)
        return item[0] if item else None

    def list_tools(self) -> list[ToolMetadata]:
        return [item[0] for item in self._tools.values()]

    def find_tools(self, query: str, k: int = 4) -> list[ToolShortlistItem]:
        q = (query or "").strip()
        if not q:
            metas = sorted(self.list_tools(), key=lambda m: m.name)
            return [
                ToolShortlistItem(
                    name=m.name,
                    tags=m.tags,
                    routing_summary=m.routing_summary,
                    invocation_summary=m.invocation_summary,
                    score=0.0,
                )
                for m in metas[:k]
            ]

        try:
            cursor = self._conn.execute(
                "SELECT name, bm25(tool_docs_fts, 1.0, 1.2, 1.5, 1.1) AS rank FROM tool_docs_fts "
                "WHERE tool_docs_fts MATCH ? ORDER BY rank LIMIT ?",
                (q, k),
            )
            rows = list(cursor.fetchall())
        except sqlite3.OperationalError:
            rows = []
        if not rows:
            # deterministic fallback if FTS query has syntax/user token edge-cases.
            metas = []
            query_lower = q.lower()
            for m in self.list_tools():
                text = f"{m.name} {' '.join(m.tags)} {m.routing_summary} {m.invocation_summary}".lower()
                score = float(text.count(query_lower))
                if score > 0:
                    metas.append((m, -score))
            metas.sort(key=lambda x: (x[1], x[0].name))
            rows = [(m.name, s) for m, s in metas[:k]]

        out: list[ToolShortlistItem] = []
        for name, rank in rows:
            meta = self.get_metadata(name)
            if meta is None:
                continue
            out.append(
                ToolShortlistItem(
                    name=meta.name,
                    tags=meta.tags,
                    routing_summary=meta.routing_summary,
                    invocation_summary=meta.invocation_summary,
                    score=float(-rank),
                )
            )
        return out
