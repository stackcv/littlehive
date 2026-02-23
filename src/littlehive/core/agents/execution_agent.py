from __future__ import annotations

from dataclasses import dataclass
import re
from collections import Counter
from collections.abc import Callable

from littlehive.core.orchestrator.handoff import Transfer
from littlehive.core.tools.base import ToolCallContext
from littlehive.core.tools.executor import ToolExecutor
from littlehive.core.tools.injection import build_tool_docs_bundle
from littlehive.core.tools.registry import ToolRegistry, ToolShortlistItem


@dataclass(slots=True)
class ExecutionResult:
    selected_tools: list[str]
    outputs: list[dict]
    injection_log: dict
    confidence: float
    needs_clarification: bool
    clarification_question: str


class ExecutionAgent:
    agent_id = "execution_agent"

    def __init__(
        self,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        history_loader: Callable[[int, int], list[str]] | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.history_loader = history_loader
        self._low_confidence_threshold = 0.58

    @staticmethod
    def _is_remember_intent(text: str) -> bool:
        return any(k in text for k in ["remember that", "remember ", "my timezone is", "my time zone is", "note that"])

    @staticmethod
    def _is_recall_intent(text: str) -> bool:
        return any(
            k in text
            for k in [
                "what is my",
                "what's my",
                "do you remember",
                "recall",
                "what did i",
                "did i tell you",
            ]
        )

    @staticmethod
    def _is_weather_intent(text: str) -> bool:
        return any(
            k in text
            for k in [
                "weather",
                "forecast",
                "temperature",
                "rain",
                "humidity",
                "wind speed",
            ]
        )

    @staticmethod
    def _extract_weather_location(text: str) -> str:
        lowered = text.lower()
        markers = [
            "weather in ",
            "forecast for ",
            "temperature in ",
            "rain in ",
            "humidity in ",
        ]
        for marker in markers:
            idx = lowered.find(marker)
            if idx >= 0:
                value = text[idx + len(marker) :].strip(" ?.,!")
                if value:
                    return value[:120]
        return text.strip(" ?.,!")[:120]

    @staticmethod
    def _is_followup_intent(text: str) -> bool:
        hints = [
            "also",
            "again",
            "same",
            "that one",
            "do it",
            "do that",
            "continue",
            "as before",
            "it too",
        ]
        return any(h in text for h in hints)

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return {tok for tok in re.findall(r"[a-z0-9]+", text.lower()) if tok}

    @classmethod
    def _expanded_query_tokens(cls, text: str) -> set[str]:
        tokens = cls._tokenize(text)
        if "umbrella" in tokens:
            tokens.update({"rain", "forecast", "weather"})
        if "temperature" in tokens:
            tokens.update({"weather", "forecast"})
        if "remember" in tokens:
            tokens.update({"memory", "write"})
        if "recall" in tokens:
            tokens.update({"memory", "search"})
        return tokens

    def _semantic_score(self, query: str, tool_name: str) -> float:
        meta = self.tool_registry.get_metadata(tool_name)
        if meta is None:
            return 0.0
        query_tokens = self._expanded_query_tokens(query)
        if not query_tokens:
            return 0.0
        tool_text = " ".join(
            [
                meta.name,
                " ".join(meta.tags),
                meta.routing_summary,
                meta.invocation_summary,
                " ".join(meta.examples),
            ]
        )
        tool_tokens = self._tokenize(tool_text)
        if not tool_tokens:
            return 0.0
        inter = len(query_tokens.intersection(tool_tokens))
        union = len(query_tokens.union(tool_tokens))
        return float(inter / union) if union > 0 else 0.0

    @staticmethod
    def _normalize_scores(raw: dict[str, float]) -> dict[str, float]:
        if not raw:
            return {}
        max_score = max(raw.values())
        min_score = min(raw.values())
        if max_score <= min_score:
            return {k: 1.0 for k in raw}
        span = max_score - min_score
        return {k: (v - min_score) / span for k, v in raw.items()}

    def _history_scores(self, tools: list[str], history: list[str], followup: bool) -> dict[str, float]:
        if not tools:
            return {}
        if not history:
            return {name: 0.0 for name in tools}
        counts = Counter(history)
        max_freq = max(counts.values()) if counts else 1
        last_tool = history[-1] if history else ""
        out: dict[str, float] = {}
        for name in tools:
            freq_score = float(counts.get(name, 0) / max_freq)
            recency = 1.0 if name == last_tool else 0.0
            namespace_boost = 0.0
            if "." in name and "." in last_tool:
                namespace_boost = 0.3 if name.split(".", 1)[0] == last_tool.split(".", 1)[0] else 0.0
            out[name] = freq_score * 0.5 + recency * 0.4 + namespace_boost
            if followup and name == last_tool:
                out[name] += 0.35
        return out

    def _hybrid_rank(
        self,
        *,
        query: str,
        shortlist: list[ToolShortlistItem],
        ctx: ToolCallContext,
        followup: bool,
    ) -> tuple[list[str], float]:
        if not shortlist:
            return [], 0.0
        names = [item.name for item in shortlist]
        lexical_raw = {item.name: float(item.score) for item in shortlist}
        lexical = self._normalize_scores(lexical_raw)
        semantic = self._normalize_scores({name: self._semantic_score(query, name) for name in names})

        history: list[str] = []
        if self.history_loader is not None:
            history = self.history_loader(ctx.session_db_id, 8)
        history_norm = self._normalize_scores(self._history_scores(names, history, followup))

        if followup:
            w_lex, w_sem, w_hist = 0.35, 0.25, 0.40
        else:
            w_lex, w_sem, w_hist = 0.45, 0.40, 0.15

        combined: dict[str, float] = {}
        for name in names:
            combined[name] = (
                w_lex * lexical.get(name, 0.0)
                + w_sem * semantic.get(name, 0.0)
                + w_hist * history_norm.get(name, 0.0)
            )

        ranked = sorted(names, key=lambda n: combined[n], reverse=True)
        top = combined.get(ranked[0], 0.0)
        second = combined.get(ranked[1], 0.0) if len(ranked) > 1 else 0.0
        margin = max(0.0, top - second)
        confidence = min(0.99, max(0.05, 0.65 * top + 0.35 * margin))
        return ranked, confidence

    def _candidate_shortlist(self, query: str, allowed_tool_names: set[str], k: int = 6) -> list[ToolShortlistItem]:
        lexical = [item for item in self.tool_registry.find_tools(query=query, k=k) if item.name in allowed_tool_names]
        if lexical:
            return lexical
        # If lexical retrieval is empty (indirect phrasing), rerank across all allowed tools.
        out: list[ToolShortlistItem] = []
        for meta in sorted(self.tool_registry.list_tools(), key=lambda m: m.name):
            if meta.name not in allowed_tool_names:
                continue
            out.append(
                ToolShortlistItem(
                    name=meta.name,
                    tags=meta.tags,
                    routing_summary=meta.routing_summary,
                    invocation_summary=meta.invocation_summary,
                    score=0.0,
                )
            )
            if len(out) >= k:
                break
        return out

    def execute_from_transfer(self, transfer: Transfer, ctx: ToolCallContext) -> ExecutionResult:
        allowed_tool_names = (
            self.tool_executor.list_allowed_tool_names()
            if hasattr(self.tool_executor, "list_allowed_tool_names")
            else {meta.name for meta in self.tool_registry.list_tools()}
        )
        routing_bundle = build_tool_docs_bundle(
            registry=self.tool_registry,
            query=transfer.input_summary,
            mode="routing",
            selected_tool_names=None,
            allowed_tool_names=allowed_tool_names,
            k=4,
        )

        selected: list[str] = []
        text = transfer.input_summary.lower()
        followup = self._is_followup_intent(text)
        explicit_intent = False

        # Intent-first routing: avoid noisy memory.search on write-intent turns.
        if self._is_weather_intent(text):
            selected = ["weather.get"]
            explicit_intent = True
        elif self._is_remember_intent(text):
            selected = ["memory.write"]
            explicit_intent = True
        elif self._is_recall_intent(text):
            selected = ["memory.search"]
            explicit_intent = True

        for item in routing_bundle.routing:
            n = item["name"]
            if n.startswith("memory") and any(k in text for k in ["remember", "preference", "memory", "fix"]):
                if n not in selected:
                    selected.append(n)
            if n == "status.get" and "status" in text:
                if n not in selected:
                    selected.append(n)
            if n.startswith("task.") and "task" in text:
                if n not in selected:
                    selected.append(n)

        selected = [name for name in selected if name in allowed_tool_names]

        ranked_names, hybrid_confidence = self._hybrid_rank(
            query=transfer.input_summary,
            shortlist=self._candidate_shortlist(transfer.input_summary, allowed_tool_names, k=6),
            ctx=ctx,
            followup=followup,
        )
        if not explicit_intent and ranked_names:
            selected = ranked_names[:2]

        # If we are writing memory, keep tool path focused to reduce wrong-context replies.
        if selected and selected[0] == "memory.write":
            selected = ["memory.write"]
        if selected and selected[0] == "memory.search":
            selected = ["memory.search"]

        if not selected and routing_bundle.routing:
            options = [item["name"] for item in routing_bundle.routing[:2]]
            option_text = " or ".join(options) if options else "a tool"
            return ExecutionResult(
                selected_tools=[],
                outputs=[],
                injection_log={
                    "routing_count": len(routing_bundle.routing),
                    "invocation_count": 0,
                    "full_schema_count": 0,
                },
                confidence=0.35,
                needs_clarification=True,
                clarification_question=f"I can use {option_text}. Which one do you want me to run?",
            )
        if not selected:
            return ExecutionResult(
                selected_tools=[],
                outputs=[],
                injection_log={
                    "routing_count": len(routing_bundle.routing),
                    "invocation_count": 0,
                    "full_schema_count": 0,
                },
                confidence=0.2,
                needs_clarification=True,
                clarification_question="I need a bit more detail before choosing a tool. What exactly should I do?",
            )
        if not explicit_intent and hybrid_confidence < self._low_confidence_threshold:
            options = selected[:2]
            option_text = " or ".join(options) if options else "a tool"
            return ExecutionResult(
                selected_tools=[],
                outputs=[],
                injection_log={
                    "routing_count": len(routing_bundle.routing),
                    "invocation_count": 0,
                    "full_schema_count": 0,
                },
                confidence=hybrid_confidence,
                needs_clarification=True,
                clarification_question=f"I am not fully sure. Should I use {option_text}?",
            )

        invocation_bundle = build_tool_docs_bundle(
            registry=self.tool_registry,
            query=transfer.input_summary,
            mode="invocation",
            selected_tool_names=selected,
            allowed_tool_names=allowed_tool_names,
            k=4,
        )

        outputs: list[dict] = []
        for tool_name in selected[:2]:
            full_bundle = build_tool_docs_bundle(
                registry=self.tool_registry,
                query=transfer.input_summary,
                mode="full_for_selected",
                selected_tool_names=[tool_name],
                allowed_tool_names=allowed_tool_names,
                k=4,
            )
            # Full schema only enters context at actual invocation step.
            _ = full_bundle
            if tool_name == "memory.search":
                outputs.append(self.tool_executor.execute(tool_name, ctx, {"query": transfer.input_summary, "top_k": 3}))
            elif tool_name == "memory.write":
                outputs.append(self.tool_executor.execute(tool_name, ctx, {"content": transfer.input_summary}))
            elif tool_name == "memory.failure_fix":
                outputs.append(
                    self.tool_executor.execute(
                        tool_name,
                        ctx,
                        {
                            "error_signature": "generic",
                            "fix": transfer.input_summary[:120],
                            "source": "execution_agent",
                        },
                    )
                )
            elif tool_name == "status.get":
                outputs.append(self.tool_executor.execute(tool_name, ctx, {}))
            elif tool_name == "task.update" and ctx.task_id is not None:
                outputs.append(
                    self.tool_executor.execute(
                        tool_name,
                        ctx,
                        {
                            "task_id": ctx.task_id,
                            "status": "running",
                            "step_index": 0,
                            "agent_id": self.agent_id,
                            "detail": "execution agent tool phase",
                        },
                    )
                )
            elif tool_name == "weather.get":
                location = self._extract_weather_location(transfer.input_summary)
                try:
                    outputs.append(self.tool_executor.execute(tool_name, ctx, {"location": location, "days": 1}))
                except Exception as exc:  # noqa: BLE001
                    # Keep weather failure explicit for reply synthesis and observability.
                    outputs.append(
                        {
                            "status": "error",
                            "tool_name": "weather.get",
                            "reason": str(exc)[:240],
                            "location": location,
                        }
                    )

        confidence = 0.9 if explicit_intent else hybrid_confidence
        return ExecutionResult(
            selected_tools=selected,
            outputs=outputs,
            injection_log={
                "routing_count": len(routing_bundle.routing),
                "invocation_count": len(invocation_bundle.invocation),
                "full_schema_count": len(selected[:2]),
            },
            confidence=confidence,
            needs_clarification=False,
            clarification_question="",
        )

    def run(self, payload: dict) -> dict:
        return payload
