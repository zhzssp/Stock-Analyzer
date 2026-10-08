from __future__ import annotations

import logging
from pathlib import Path

import yaml

from src.config import ROOT
from src.tools.base import ToolResult, ToolSpec
from src.tools.registry import registry

logger = logging.getLogger(__name__)

MANIFEST_DIR = ROOT / "src" / "tools" / "manifests"


def _disabled_run(spec: ToolSpec):
    def run(args: dict, ctx) -> ToolResult:
        return ToolResult(
            ok=False,
            error=spec.reason or f"Tool 未启用: {spec.id}",
            source=spec.id,
            cite=spec.name,
        )

    # 打标记：后面要能分辨「这个工具是空壳」，避免 enabled=true 却没有实现
    run.is_disabled_placeholder = True
    return run


def _warn_enabled_without_impl() -> None:
    """enabled=true 却没有实现 = 大模型看得到、调了必然失败。启动就要喊出来。"""
    for spec in registry.all():
        fn = registry.fn_of(spec.id)
        if spec.enabled and getattr(fn, "is_disabled_placeholder", False):
            logger.warning(
                "工具 %s 声明 enabled=true 但没有实现，调用必然失败（%s）",
                spec.id,
                spec.reason or "未找到实现",
            )


def load_manifests(directory: Path | None = None) -> list[str]:
    """加载工具清单。

    两种情况要分开：
    - 代码里已有实现的工具：yaml 只用来更新说明 / 开关，**绝不替换实现函数**
      （以前这里直接 continue，导致改 yaml 完全无效、`/agent/tools/reload` 对工具是空操作）
    - 清单里有、代码里没有的：注册进来并挂空壳，明确告诉调用方「还没实现」
    """
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
        if any(s.id == tool_id for s in registry.all()):
            # 已注册：只更新说明与开关，保留真实现，支持热重载
            registry.update_spec(spec)
        else:
            registry.register(spec, _disabled_run(spec))
        loaded.append(tool_id)
    _warn_enabled_without_impl()
    return loaded
