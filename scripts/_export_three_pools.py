# -*- coding: utf-8 -*-
"""Export three pools from the live API.

深市全部 is every Shenzhen listing, including ChiNext.
沪市全部 is every Shanghai listing, including STAR.
创业板全部 is the 300-prefix board and overlaps 深市全部 on purpose.
Already written rows are kept. Price and change are the 2026-10-23 daily bar.
PE and PB stay on the pre-open quote; once the live price leaves Friday's close
they are scaled back by Friday close / live price.
"""

from __future__ import annotations

import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openpyxl import load_workbook

from src.market.client import MarketClient
from src.platform.export_xlsx import write_query_xlsx
from src.platform.pools import resolve_pool
from src.query.engine import QueryEngine
from src.query.presets import PRESET_RESEARCH, keys_for_preset
from src.query.registry import registry

FIELDS = keys_for_preset(PRESET_RESEARCH)
OUT = Path(r"c:\Users\zhzss\Desktop\股票池导出")
LOG = Path("data/logs/export_three.log")
STATUS = OUT / "导出进度.txt"
BACKUP = OUT / "深市全部_重启前备份.xlsx"
CHUNK = 200
FRIDAY = "2026-10-23"
LABEL_TO_KEY = {registry.get(key).label: key for key in FIELDS}


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def write_status(text: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(text, encoding="utf-8")


class StopExport(RuntimeError):
    pass


def before_nine() -> bool:
    now = datetime.now()
    return now.date().isoformat() == "2026-10-26" and now.hour < 9


def as_float(value):
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def install_keep_consumable(market: MarketClient) -> None:
    """限频被误判成额度用尽时，不要把长期证从池里删掉。"""
    registry = market._registry
    if registry is None:
        return
    original = registry.mark_quota_exhausted

    def wrapped(licence: str) -> str:
        token = (licence or "").strip()
        if token and token in registry._consumable:
            log(f"长期证被判额度用尽，仍保留在池中 {token[:8]}")
            return token
        return original(licence)

    registry.mark_quota_exhausted = wrapped


class _RequestPace:
    """全部请求共用一条队列。限频时只把间隔拉长，不再让每条请求各自睡满一分钟。"""

    def __init__(self) -> None:
        self._cv = threading.Condition()
        self._next_at = 0.0
        self._gap = 0.2
        self._ok = 0
        self._quiet_until = 0.0

    def wait_turn(self) -> None:
        with self._cv:
            while True:
                now = time.monotonic()
                if now >= self._next_at:
                    self._next_at = now + self._gap
                    return
                self._cv.wait(timeout=self._next_at - now)

    def ok(self) -> None:
        with self._cv:
            self._ok += 1
            if self._ok >= 50 and self._gap > 0.12:
                self._gap = max(0.12, self._gap * 0.8)
                self._ok = 0
                log(f"请求间隔收紧到 {self._gap:.2f} 秒")
                self._cv.notify_all()

    def limited(self, retry_after: float | None) -> None:
        with self._cv:
            now = time.monotonic()
            if now < self._quiet_until:
                self._next_at = max(self._next_at, self._quiet_until)
                return
            pause = retry_after if retry_after and retry_after > 0 else None
            self._gap = min(8.0, max(self._gap * 1.7, pause or 0.5))
            self._next_at = max(self._next_at, now + (pause or self._gap))
            self._quiet_until = self._next_at
            self._ok = 0
            log(f"限频，全队列改为每 {self._gap:.1f} 秒一条")
            self._cv.notify_all()


def install_rate_retry(market: MarketClient) -> None:
    original = market._http_get
    pace = _RequestPace()

    def wrapped(url: str):
        response = None
        for _attempt in range(12):
            pace.wait_turn()
            response = original(url)
            code = getattr(response, "status_code", None)
            if code != 429:
                pace.ok()
                return response
            retry_after = None
            try:
                raw = response.headers.get("Retry-After")
                if raw:
                    retry_after = float(raw)
            except (TypeError, ValueError, AttributeError):
                retry_after = None
            pace.limited(retry_after)
        return response

    market._http_get = wrapped


def friday_bar(market: MarketClient, code_full: str) -> dict | None:
    try:
        url = market._url(f"/hsstock/history/{code_full}/d/n") + "?lt=8"
        response = market._http_get(url)
        if getattr(response, "status_code", None) != 200:
            return None
        data = response.json()
    except Exception as exc:  # noqa: BLE001 - one missing bar should not stop the pool
        log(f"friday bar fail {code_full.split('.')[0]} {type(exc).__name__}")
        return None
    if not isinstance(data, list):
        return None
    best = None
    best_day = ""
    for row in data:
        if not isinstance(row, dict):
            continue
        day = str(row.get("t") or "")[:10]
        if day and day <= FRIDAY and day >= best_day:
            best_day = day
            best = row
    return best


def friday_pct(bar: dict):
    close = as_float(bar.get("c"))
    prev = as_float(bar.get("pc"))
    if close is None or prev in (None, 0):
        return None
    return round((close - prev) / prev * 100, 2)


def apply_friday(live: dict | None, bar: dict | None, allow_live: bool) -> tuple[dict, bool]:
    """Return (quote, scaled). Without a Friday bar after 09:00, drop the live quote."""
    base = dict(live or {})
    if not bar:
        if allow_live:
            base["source"] = base.get("source") or "live"
            return base, False
        base.update({"p": None, "pc": None, "pe": None, "sjl": None, "source": "friday-missing"})
        return base, False
    close = as_float(bar.get("c"))
    live_price = as_float(base.get("p"))
    scaled = False
    if close not in (None, 0) and live_price not in (None, 0):
        if abs(live_price - close) / max(abs(close), 1e-9) > 0.0001:
            ratio = close / live_price
            for key in ("pe", "sjl"):
                number = as_float(base.get(key))
                if number is not None:
                    base[key] = round(number * ratio, 2)
            scaled = True
    base["p"] = close
    base["pc"] = friday_pct(bar)
    base["source"] = f"friday-{str(bar.get('t') or '')[:10]}"
    return base, scaled


def install_friday_quotes(market: MarketClient) -> None:
    original = market.quotes_many

    def quotes_many(insts):
        live = original(insts) or {}
        allow_live = before_nine()

        def one(inst):
            return inst.code6, friday_bar(market, inst.code_full)

        bars: dict[str, dict | None] = {}
        workers = min(2, max(1, len(insts)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for code6, bar in pool.map(one, insts):
                bars[code6] = bar
        out = {}
        scaled = 0
        found = 0
        for inst in insts:
            bar = bars.get(inst.code6)
            if bar:
                found += 1
            quote, did = apply_friday(live.get(inst.code6), bar, allow_live)
            if did:
                scaled += 1
            out[inst.code6] = quote
        log(f"friday quotes n={len(insts)} bars={found} scaled={scaled} before9={allow_live}")
        return out

    market.quotes_many = quotes_many


def load_rows(path: Path) -> dict[str, dict]:
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = book["query"]
        iterator = sheet.iter_rows(values_only=True)
        headers = ["" if cell is None else str(cell).strip() for cell in next(iterator)]
        found: dict[str, dict] = {}
        for values in iterator:
            row: dict = {}
            for header, value in zip(headers, values):
                key = LABEL_TO_KEY.get(header)
                if key:
                    row[key] = value
            code = str(row.get("code") or "").strip()
            code6 = code.split(".")[0]
            if len(code6) != 6 or not code6.isdigit():
                continue
            row["code6"] = code6
            row["code"] = code
            found[code6] = row
        return found
    finally:
        book.close()


def load_best(paths: list[Path]) -> tuple[dict[str, dict], str]:
    best: dict[str, dict] = {}
    origin = ""
    for path in paths:
        if not path.exists():
            continue
        try:
            rows = load_rows(path)
        except Exception as exc:  # noqa: BLE001 - a torn xlsx must not wipe the other copy
            log(f"skip unreadable {path.name}: {type(exc).__name__}")
            continue
        log(f"readable {path.name} rows={len(rows)}")
        if len(rows) > len(best):
            best = rows
            origin = str(path)
    return best, origin


def publish(rows: list[dict], pool_name: str, dest: Path, keep_artifact: bool) -> Path:
    path = write_query_xlsx(rows, FIELDS, pool_name, file_label=f"{pool_name}_截至{FRIDAY}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    if not keep_artifact:
        try:
            path.unlink()
        except OSError:
            pass
    return dest


def filled(rows: list[dict], key: str) -> int:
    return sum(1 for row in rows if row.get(key) not in (None, ""))


def ordered_rows(instruments, kept: dict[str, dict], fetched: dict[str, dict]) -> list[dict]:
    rows = []
    for inst in instruments:
        if inst.code6 in fetched:
            rows.append(fetched[inst.code6])
        elif inst.code6 in kept:
            rows.append(kept[inst.code6])
    return rows


def run_pool(engine: QueryEngine, market: MarketClient, pool_id: str, label: str, kept: dict[str, dict]) -> tuple[list[dict], bool]:
    instruments, meta = resolve_pool(pool_id, market)
    total = len(instruments)
    todo = [inst for inst in instruments if inst.code6 not in kept]
    log(f"EXPORT START {label} id={pool_id} n={total} kept={len(kept)} todo={len(todo)} note={meta.get('note') or ''}")
    publish(ordered_rows(instruments, kept, {}), label, OUT / f"{label}_进行中.xlsx", keep_artifact=False)
    write_status(
        f"{label}：已保留 {len(kept)} 行（周五 10-23 收盘前已导出的部分）\n"
        f"剩余 {len(todo)} 只继续向接口取，现价和涨跌幅锁定 {FRIDAY} 日线。\n"
    )
    fetched: dict[str, dict] = {}
    started = time.time()
    for offset in range(0, len(todo), CHUNK):
        batch = todo[offset : offset + CHUNK]
        got = engine.run(batch, FIELDS, refresh_mode="full", force_live=True)
        for row in got:
            code6 = str(row.get("code6") or "")
            if code6:
                fetched[code6] = row
        done_rows = ordered_rows(instruments, kept, fetched)
        priced = filled(got, "price")
        sample = got[0] if got else {}
        issues = engine.last_issues or []
        log(
            "EXPORT CHUNK "
            f"{label} {len(done_rows)}/{total} "
            f"new={len(fetched)} kept={len(kept)} "
            f"batch_price={priced}/{len(got)} "
            f"elapsed={time.time() - started:.0f}s "
            f"source={sample.get('quote_source') or ''} "
            f"issues={len(issues)}"
        )
        if issues:
            message = str(issues[0].get("message") or issues[0])
            log("issue " + message.split(" for url ")[0])
        publish(done_rows, label, OUT / f"{label}_进行中.xlsx", keep_artifact=False)
        write_status(
            f"{label}：{len(done_rows)}/{total}\n"
            f"其中原样保留 {len(kept)} 行，新接口补入 {len(fetched)} 行。\n"
            f"行情截止 {FRIDAY}。现价有值 {filled(done_rows, 'price')}/{len(done_rows)}。\n"
        )
        quota_note = any("额度" in str(item.get("message") or "") for item in issues)
        slow_ok = filled(got, "industry")
        quota_dead = market.status == "quota-exhausted" and not (market._registry and market._registry.iteration_plan())
        fields_empty = quota_note and len(got) >= 30 and slow_ok < len(got) * 0.5
        too_empty = len(got) >= 30 and priced < len(got) * 0.5
        if quota_dead or fields_empty or too_empty:
            failed = OUT / f"{label}_未完成.xlsx"
            publish(done_rows, label, failed, keep_artifact=True)
            log(
                f"EXPORT FAIL {label} saved={failed} quota={quota_dead} "
                f"fields_empty={fields_empty} empty={too_empty} status={market.status}"
            )
            raise StopExport(label)
    final_rows = ordered_rows(instruments, kept, fetched)
    missing = [inst.code6 for inst in instruments if inst.code6 not in kept and inst.code6 not in fetched]
    publish(final_rows, label, OUT / f"{label}.xlsx", keep_artifact=True)
    partial = OUT / f"{label}_进行中.xlsx"
    if partial.exists() and not missing:
        partial.unlink()
    log(
        "EXPORT DONE "
        f"{label} rows={len(final_rows)} missing={len(missing)} "
        f"price={filled(final_rows, 'price')} industry={filled(final_rows, 'industry')} "
        f"holders={filled(final_rows, 'holders')} eps={filled(final_rows, 'eps')} "
        f"file={OUT / (label + '.xlsx')}"
    )
    return final_rows, not missing


def export_cy(sz_rows: list[dict], cy_codes: list[str], complete_source: bool) -> None:
    by_code = {str(row.get("code6") or ""): row for row in sz_rows}
    picked = [by_code[code] for code in cy_codes if code in by_code]
    missing = [code for code in cy_codes if code not in by_code]
    name = "创业板全部" if complete_source and not missing else "创业板全部_未完成"
    dest = OUT / f"{name}.xlsx"
    publish(picked, "创业板全部", dest, keep_artifact=True)
    log(
        "EXPORT DONE "
        f"创业板全部 rows={len(picked)} missing={len(missing)} "
        f"price={filled(picked, 'price')} file={dest}"
    )


def load_kept(label: str) -> dict[str, dict]:
    rows, origin = load_best(
        [
            OUT / f"{label}_含创业板.xlsx",
            OUT / f"{label}_含科创板.xlsx",
            OUT / f"{label}_进行中.xlsx",
            OUT / f"{label}_未完成.xlsx",
            OUT / f"{label}_重启前备份.xlsx",
            OUT / f"{label}.xlsx",
        ]
    )
    log(f"RESUME {label} kept={len(rows)} origin={origin}")
    return rows


def export_three() -> None:
    """深市、沪市按交易所全名单导出。创业板从深市结果里按 300 前缀另存一份。"""
    market = MarketClient()
    log(
        "RESUME market "
        f"status={market.status} offline={market.offline} sample={market.sample_only} "
        f"friday={FRIDAY} before9={before_nine()}"
    )
    if market.offline or market.sample_only or market.status != "live":
        raise SystemExit(f"接口不可用：{market.status}")
    install_rate_retry(market)
    install_keep_consumable(market)
    install_friday_quotes(market)
    engine = QueryEngine(market)
    sz_rows, sz_ok = run_pool(engine, market, "exchange:sz", "深市全部", load_kept("深市全部"))
    cy_codes = [inst.code6 for inst in resolve_pool("board:cy", market)[0]]
    export_cy(sz_rows, cy_codes, sz_ok)
    run_pool(engine, market, "exchange:sh", "沪市全部", load_kept("沪市全部"))
    write_status(f"三池已导出，行情截止 {FRIDAY}。\n目录：{OUT}\n")
    log("EXPORT ALL DONE")


def resume_shanghai() -> None:
    """继续向接口补沪市。名单是上交所全部，含科创板。"""
    market = MarketClient()
    log(
        "RESUME market "
        f"status={market.status} offline={market.offline} sample={market.sample_only} "
        f"friday={FRIDAY} before9={before_nine()}"
    )
    if market.offline or market.sample_only or market.status != "live":
        raise SystemExit(f"接口不可用：{market.status}")
    install_rate_retry(market)
    install_keep_consumable(market)
    install_friday_quotes(market)
    sh_kept = load_kept("沪市全部")
    if len(sh_kept) < 800:
        raise SystemExit(f"已导出沪市行数只有 {len(sh_kept)}，停止，避免覆盖已有文件")
    engine = QueryEngine(market)
    try:
        run_pool(engine, market, "exchange:sh", "沪市全部", sh_kept)
        write_status(f"沪市全部已导出，行情截止 {FRIDAY}。\n目录：{OUT}\n")
        log("EXPORT ALL DONE")
    except StopExport as exc:
        write_status(f"导出中断：{exc}\n已保留的行仍在 {OUT}\n行情截止 {FRIDAY}\n")
        log(f"EXPORT STOPPED {exc}")
        raise


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if len(FIELDS) != 17:
        raise SystemExit(f"默认字段不是 17 个：{len(FIELDS)}")
    try:
        export_three()
    except StopExport as exc:
        write_status(f"导出中断：{exc}\n已保留的行仍在 {OUT}\n行情截止 {FRIDAY}\n")
        log(f"EXPORT STOPPED {exc}")
        raise


if __name__ == "__main__":
    main()
