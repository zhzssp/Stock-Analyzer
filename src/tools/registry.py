from __future__ import annotations

from src.tools.base import ToolContext, ToolFn, ToolResult, ToolSpec


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._fns: dict[str, ToolFn] = {}

    def register(self, spec: ToolSpec, fn: ToolFn) -> None:
        self._specs[spec.id] = spec
        self._fns[spec.id] = fn

    def get(self, tool_id: str) -> ToolSpec:
        return self._specs[tool_id]

    def all(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def enabled(self) -> list[ToolSpec]:
        return [s for s in self._specs.values() if s.enabled]

    def schemas_for_llm(self) -> list[dict]:
        out = []
        for spec in self.enabled():
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": spec.id,
                        "description": spec.description,
                        "parameters": spec.input_schema,
                    },
                }
            )
        return out

    def run(self, tool_id: str, args: dict, ctx: ToolContext) -> ToolResult:
        spec = self._specs.get(tool_id)
        if not spec:
            return ToolResult(ok=False, error=f"未知 Tool: {tool_id}", source="registry")
        if not spec.enabled:
            return ToolResult(ok=False, error=f"Tool 未启用: {tool_id}", source=spec.id, cite=spec.name)
        try:
            return self._fns[tool_id](args or {}, ctx)
        except Exception as exc:
            return ToolResult(ok=False, error=str(exc), source=spec.id, cite=spec.name)


registry = ToolRegistry()
