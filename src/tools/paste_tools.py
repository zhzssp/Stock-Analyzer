from __future__ import annotations

import base64

from src.platform.export_xlsx import write_table_xlsx
from src.platform.storage import record_artifact
from src.tools.base import ToolContext, ToolResult, ToolSpec
from src.tools.registry import registry
from src.tools.table_parse import looks_like_table, parse_table_text, parse_xlsx_bytes


def _pick_attachment(args: dict, ctx: ToolContext) -> dict | None:
    if args.get("text") or args.get("content_base64"):
        return {
            "kind": "file" if args.get("content_base64") else "text",
            "name": args.get("name") or "pasted",
            "text": args.get("text"),
            "content_base64": args.get("content_base64"),
        }
    attachments = list(ctx.attachments or [])
    if args.get("name"):
        hit = next((a for a in attachments if a.get("name") == args["name"]), None)
        if hit:
            return hit
    return attachments[0] if attachments else None


def excel_parse(args: dict, ctx: ToolContext) -> ToolResult:
    att = _pick_attachment(args, ctx)
    question = args.get("question") or args.get("text") or ""
    sheet = None
    name = (att or {}).get("name") or "pasted"
    if att and att.get("content_base64"):
        try:
            raw = base64.b64decode(att["content_base64"])
        except Exception:
            return ToolResult(ok=False, error="附件不是合法的 Base64", source="excel_parse", cite="粘贴表格")
        if len(raw) > 2_000_000:
            return ToolResult(ok=False, error="附件超过 2MB", source="excel_parse", cite="粘贴表格")
        lower = name.lower()
        try:
            if lower.endswith((".xlsx", ".xlsm")):
                sheet = parse_xlsx_bytes(raw)
            else:
                sheet = parse_table_text(raw.decode("utf-8-sig", errors="replace"))
        except Exception as exc:
            return ToolResult(ok=False, error=f"无法解析附件: {exc}", source="excel_parse", cite=name)
    else:
        text = (att or {}).get("text") or question
        if not looks_like_table(text):
            return ToolResult(
                ok=False,
                error="对话里没有可解析的表格。请从 Excel 复制单元格粘贴，或上传 .xlsx / .csv",
                source="excel_parse",
                cite="粘贴表格",
            )
        sheet = parse_table_text(text)
        name = (att or {}).get("name") or "pasted.tsv"

    if not sheet or not sheet.get("rows"):
        return ToolResult(ok=False, error="表格是空的", source="excel_parse", cite=name)

    path = write_table_xlsx(sheet["headers"], sheet["rows"], "pasted")
    rec = record_artifact(
        ctx.db,
        user_id=ctx.user_id,
        path=path,
        pool_name="pasted",
        field_keys=sheet["headers"],
        codes=sheet.get("codes") or [],
    )
    data = {
        **sheet,
        "id": rec.id,
        "filename": rec.filename,
        "path": rec.path,
        "name": name,
    }
    return ToolResult(ok=True, data=data, source="excel_parse", cite=f"粘贴表格 · {rec.filename}")


registry.register(
    ToolSpec(
        "excel_parse",
        "解析粘贴表格",
        "artifact",
        "解析用户粘贴或上传的 Excel/CSV/TSV/HTML 表，抽出代码并写入档案库",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "从 Excel 粘贴的文本"},
                "name": {"type": "string"},
                "content_base64": {"type": "string"},
                "question": {"type": "string"},
            },
        },
    ),
    excel_parse,
)
