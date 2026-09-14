from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

from src.config import settings
from src.query.registry import registry


def _safe_token(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (name or "pool"))
    return cleaned.strip("_") or "pool"


def write_query_xlsx(rows: list[dict], field_keys: list[str], pool_name: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{stamp}_{_safe_token(pool_name)}.xlsx"
    path = settings.artifact_dir / filename
    wb = Workbook()
    ws = wb.active
    ws.title = "query"
    headers = [registry.get(k).label for k in field_keys]
    ws.append(headers)
    for row in rows:
        ws.append([row.get(k) for k in field_keys])
    meta = wb.create_sheet("meta")
    meta.append(["exported_at", datetime.now().isoformat(timespec="seconds")])
    meta.append(["pool", pool_name])
    meta.append(["fields", ",".join(field_keys)])
    wb.save(path)
    return path


def write_agent_xlsx(question: str, answer: str, cites: list, tools: list) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = settings.artifact_dir / f"{stamp}_agent.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "agent"
    ws.append(["question", question])
    ws.append(["answer", answer])
    ws.append([])
    ws.append(["cites"])
    for cite in cites or []:
        if isinstance(cite, dict):
            ws.append([cite.get("cite") or cite.get("source"), cite.get("source")])
        else:
            ws.append([str(cite)])
    ws.append([])
    ws.append(["tools"])
    for tool in tools or []:
        if isinstance(tool, dict):
            ws.append([tool.get("id"), tool.get("ok"), tool.get("cite")])
        else:
            ws.append([str(tool)])
    wb.save(path)
    return path
