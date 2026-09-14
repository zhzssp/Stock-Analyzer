from __future__ import annotations

from pathlib import Path

import yaml

from src.config import ROOT
from src.tools.base import ToolResult, ToolSpec
from src.tools.registry import registry

MANIFEST_DIR = ROOT / "src" / "tools" / "manifests"


def _disabled_run(spec: ToolSpec):
    def run(args: dict, ctx) -> ToolResult:
        return ToolResult(
            ok=False,
            error=spec.reason or f"Tool 未启用: {spec.id}",
            source=spec.id,
            cite=spec.name,
        )

    return run


def load_manifests(directory: Path | None = None) -> list[str]:
    folder = directory or MANIFEST_DIR
    if not folder.exists():
        return []
    loaded = []
    for path in sorted(folder.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        tool_id = data.get("id")
        if not tool_id:
            continue
        spec = ToolSpec(
            id=tool_id,
            name=data.get("name") or tool_id,
            kind=data.get("kind") or "web",
            description=data.get("description") or "",
            input_schema=data.get("input_schema") or {"type": "object", "properties": {}},
            enabled=bool(data.get("enabled", False)),
            reason=data.get("reason") or "",
        )
        if spec.id in {s.id for s in registry.all()}:
            continue
        registry.register(spec, _disabled_run(spec))
        loaded.append(spec.id)
    return loaded
