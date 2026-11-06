from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter

from src.config import settings
from src.query.registry import registry

# 股东名单和屏幕一样用顿号连在一起。列宽按整段文字留，并允许换行，避免窄列把名字截掉。
_HOLDER_KEYS = frozenset({"holders", "top_holders"})
_HOLDER_WRAP = Alignment(wrap_text=True, vertical="top")
# 股本是股、市值是元。表上和 Excel 都改成亿，保留两位小数。
# 样例数据本身已经是亿（几十到几千），满 1 万才按原始单位换算，避免把样例再除一次。
_YI_KEYS = frozenset({"zgb", "ltgb", "mcap", "fcap"})
_YI = 100_000_000
# 和屏幕 fmt 一致：涨跌幅三类带正号，其余百分数只加 %。毛利率、净利率、短周期涨跌幅两边都不加。
_PLUS_PCT_KEYS = frozenset({"pct", "pct60", "pct_ytd"})
_PCT_KEYS = _PLUS_PCT_KEYS | frozenset({"off_low", "turnover", "vs_cost", "dist_buy", "dist_reduce"})


def as_yi(value):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if number != number or number in (float("inf"), float("-inf")):
        return value
    scaled = number / _YI if abs(number) >= 10_000 else number
    return round(scaled, 2)


def _safe_token(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (name or "pool"))
    return cleaned.strip("_") or "pool"


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def clean_concept(value) -> str:
    """和屏幕一样去掉栏目标题，顿号、中文逗号都当成分隔。"""
    parts = []
    for raw in str(value or "").replace("，", ",").replace("、", ",").split(","):
        name = raw.strip()
        if not name or name == "所属概念板块":
            continue
        parts.append(name)
    return ",".join(parts)


def format_like_screen(key: str, value):
    """把单元格写成屏幕上看到的那一串。空值留空，不写成破折号。"""
    if key == "concept":
        value = clean_concept(value)
    if value is None or value == "":
        return None
    if key in _YI_KEYS:
        return as_yi(value)
    if key in _PCT_KEYS and _is_number(value):
        sign = "+" if key in _PLUS_PCT_KEYS and value > 0 else ""
        return f"{sign}{float(value):.2f}%"
    return value


def _fit_holder_columns(ws, cols: list[int]) -> None:
    if not cols:
        return
    for col in cols:
        widest = 12
        for row_idx in range(2, ws.max_row + 1):
            cell = ws.cell(row_idx, col)
            cell.alignment = _HOLDER_WRAP
            text = "" if cell.value is None else str(cell.value)
            for line in text.split("\n"):
                widest = max(widest, len(line))
        ws.column_dimensions[get_column_letter(col)].width = min(widest * 2 + 4, 80)
    for row_idx in range(2, ws.max_row + 1):
        lines = 1
        for col in cols:
            text = ws.cell(row_idx, col).value
            if text:
                lines = max(lines, str(text).count("\n") + 1)
        if lines > 1:
            ws.row_dimensions[row_idx].height = min(16 * lines + 6, 220)


def _write_sheet(ws, rows: list[dict], field_keys: list[str]) -> None:
    headers = [registry.get(k).label for k in field_keys]
    ws.append(headers)
    holder_cols = [i for i, key in enumerate(field_keys, start=1) if key in _HOLDER_KEYS]
    yi_cols = [i for i, key in enumerate(field_keys, start=1) if key in _YI_KEYS]
    for row in rows:
        ws.append([format_like_screen(key, row.get(key)) for key in field_keys])
    for col in yi_cols:
        for row_idx in range(2, ws.max_row + 1):
            cell = ws.cell(row_idx, col)
            if isinstance(cell.value, float):
                cell.number_format = "0.00"
    _fit_holder_columns(ws, holder_cols)


def _workbook_path(pool_name: str, file_label: str) -> tuple[Workbook, Path]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    # 文件名 = 导出时间 + 用户确认的范围说明（如 沪市全部_看盘）。没传说明时仍用池名。
    filename = f"{stamp}_{_safe_token(file_label or pool_name)}.xlsx"
    path = settings.artifact_dir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    return Workbook(), path


def _write_meta(wb: Workbook, pool_name: str, file_label: str, field_keys: list[str], days: list[dict] | None = None) -> None:
    meta = wb.create_sheet("meta")
    meta.append(["exported_at", datetime.now().isoformat(timespec="seconds")])
    meta.append(["pool", pool_name])
    if file_label:
        meta.append(["export_label", file_label])
    meta.append(["fields", ",".join(field_keys)])
    if days:
        meta.append(["days", ",".join(str(item.get("date") or "") for item in days)])
        for item in days:
            meta.append(
                [
                    item.get("date") or "",
                    item.get("saved_at") or "",
                    item.get("taken_from") or "",
                    item.get("taken_to") or "",
                    item.get("count") or 0,
                ]
            )


def write_query_xlsx(
    rows: list[dict],
    field_keys: list[str],
    pool_name: str,
    file_label: str = "",
) -> Path:
    wb, path = _workbook_path(pool_name, file_label)
    ws = wb.active
    ws.title = "query"
    _write_sheet(ws, rows, field_keys)
    _write_meta(wb, pool_name, file_label, field_keys)
    wb.save(path)
    return path


def write_query_xlsx_days(
    sheets: list[dict],
    field_keys: list[str],
    pool_name: str,
    file_label: str = "",
) -> Path:
    """一天一个工作表，表名就是日期。调用方按从新到旧排好。"""
    wb, path = _workbook_path(pool_name, file_label)
    first = True
    for item in sheets:
        ws = wb.active if first else wb.create_sheet()
        first = False
        ws.title = str(item.get("date") or "day")[:31]
        _write_sheet(ws, list(item.get("rows") or []), field_keys)
    _write_meta(wb, pool_name, file_label, field_keys, sheets)
    wb.save(path)
    return path


def write_table_xlsx(headers: list, rows: list[dict], pool_name: str = "pasted") -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{stamp}_{_safe_token(pool_name)}.xlsx"
    path = settings.artifact_dir / filename
    wb = Workbook()
    ws = wb.active
    ws.title = "query"
    labels = [str(h) for h in (headers or [])]
    if not labels and rows:
        labels = [str(k) for k in rows[0].keys()]
    ws.append(labels)
    for row in rows:
        ws.append([row.get(h) for h in labels])
    meta = wb.create_sheet("meta")
    meta.append(["exported_at", datetime.now().isoformat(timespec="seconds")])
    meta.append(["pool", pool_name])
    meta.append(["source", "pasted"])
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
