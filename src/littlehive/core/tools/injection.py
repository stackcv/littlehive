from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from littlehive.core.tools.registry import ToolRegistry


@dataclass(slots=True)
class ToolDocsBundle:
    mode: str
    routing: list[dict] = field(default_factory=list)
    invocation: list[dict] = field(default_factory=list)
    full: list[dict] = field(default_factory=list)
    estimated_tokens: int = 0


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def build_tool_docs_bundle(
    *,
    registry: ToolRegistry,
    query: str,
    mode: str,
    selected_tool_names: list[str] | None = None,
    allowed_tool_names: Iterable[str] | None = None,
    k: int = 4,
) -> ToolDocsBundle:
    selected = set(selected_tool_names or [])
    allowed = set(allowed_tool_names or [])
    enforce_allowed = bool(allowed)
    bundle = ToolDocsBundle(mode=mode)
    shortlist = registry.find_tools(query=query, k=k)
    if enforce_allowed:
        shortlist = [item for item in shortlist if item.name in allowed]

    for item in shortlist:
        bundle.routing.append({"name": item.name, "routing_summary": item.routing_summary, "tags": item.tags})

    if mode in {"invocation", "full_for_selected"}:
        invocation_targets = selected if selected else {s.name for s in shortlist}
        if enforce_allowed:
            invocation_targets = {name for name in invocation_targets if name in allowed}
        for name in sorted(invocation_targets):
            meta = registry.get_metadata(name)
            if meta is None:
                continue
            bundle.invocation.append({"name": meta.name, "invocation_summary": meta.invocation_summary, "examples": meta.examples})

    if mode == "full_for_selected":
        full_targets = selected
        if enforce_allowed:
            full_targets = {name for name in full_targets if name in allowed}
        for name in sorted(full_targets):
            meta = registry.get_metadata(name)
            if meta is None:
                continue
            bundle.full.append({"name": meta.name, "full_schema": meta.full_schema})

    text_parts = [str(bundle.routing), str(bundle.invocation), str(bundle.full)]
    bundle.estimated_tokens = _estimate_tokens("\n".join(text_parts))
    return bundle
