from __future__ import annotations


class ContextCompiler:
    def compile(self, prompt: str, route_target: str) -> str:
        return f"route={route_target}\ninput={prompt}"
