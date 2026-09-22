from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from src.config import settings
from src.market import fixtures
from src.platform.storage import read_cache_json, trim_bars, write_cache_json
from src.market.holders_diff import normalize_holders, summarize
from src.market.normalize import Instrument, code6_of, normalize_instrument
from src.market.licence_pool import LicencePool, is_quota_error
from src.market.taxonomy import classify, search_needles


class MarketError(RuntimeError):
    pass


class MarketClient:
    """Only module allowed to talk to Mairui.

    Demo licence responses are never persisted as live cache.
    """

    def __init__(self) -> None:
        chain = settings.licence_chain
        self.offline = not settings.use_live_market
        self._pool: LicencePool | None = LicencePool.shared(chain) if chain and not self.offline else None
        self.licence = self._pool.active() if self._pool else ""
        self.sample_only = False
        self.status = "offline" if self.offline else "unchecked"
        if not self.offline:
            self._probe()

    def _url(self, path: str, licence: str | None = None) -> str:
        key = (licence or self.licence or (self._pool.active() if self._pool else "")).strip()
        return f"{settings.mairui_base}{path}/{key}"

    def refresh_pool(self) -> None:
        if self.offline or not self._pool:
            return
        if self._pool.repair():
            self.licence = self._pool.active()
            if self.status in ("unchecked", "offline"):
                self._probe()

    def _get(self, path: str) -> Any:
        if self.offline:
            raise MarketError("offline mode: live API disabled")
        pool = self._pool
        if pool and not pool.active():
            self.refresh_pool()
        attempts = len(pool.available()) if pool else 1
        last_error = "麦蕊证书池今日已全部用尽"
        for _ in range(max(attempts, 1)):
            lic = pool.active() if pool else self.licence
            if not lic:
                raise MarketError(last_error)
            url = self._url(path, lic)
            try:
                resp = httpx.get(url, timeout=30.0)
                if pool and is_quota_error(resp.status_code, resp.text):
                    last_error = f"Licence 当日额度已用尽: {lic[:8]}…"
                    pool.mark_exhausted(lic)
                    self.licence = pool.active()
                    continue
                resp.raise_for_status()
                self.licence = lic
                return resp.json()
            except httpx.HTTPStatusError as exc:
                body = exc.response.text if exc.response is not None else ""
                if pool and is_quota_error(exc.response.status_code if exc.response else 0, body):
                    last_error = f"Licence 当日额度已用尽: {lic[:8]}…"
                    pool.mark_exhausted(lic)
                    self.licence = pool.active()
                    continue
                raise MarketError(str(exc)) from exc
            except Exception as exc:
                raise MarketError(str(exc)) from exc
        raise MarketError(last_error)

    def _try_get(self, path: str) -> Any | None:
        try:
            return self._get(path)
        except MarketError:
            return None

    def _probe(self) -> None:
        from src.market.clock import configured_clock_dir, latest_payload, parse_as_of, slot_start

        root = configured_clock_dir()
        if root is not None:
            latest = latest_payload(root)
            stamp = parse_as_of((latest or {}).get("as_of") or "")
            if stamp is not None and slot_start() == slot_start(stamp):
                self.status = "live"
                return
        if self.licence == settings.demo_licence:
            self.sample_only = True
            self.status = "demo-licence"
            return
        prices = []
        for code in ("000001", "600038", "002230"):
            try:
                data = self._get(f"/hsrl/ssjy/{code}")
                row = data[0] if isinstance(data, list) else data
                prices.append(row.get("p"))
            except Exception:
                prices.append("ERR")
        distinct = {p for p in prices if p not in (None, "ERR")}
        if len(distinct) <= 1:
            self.sample_only = True
            self.status = "sample-only"
        else:
            self.status = "live"

    def _cache_get(self, key: str) -> Any | None:
        if self.sample_only:
            return None
        return read_cache_json(key)

    def _cache_put(self, key: str, payload: Any) -> None:
        if self.sample_only or self.offline:
            return
        write_cache_json(key, payload)

    def health(self) -> dict:
        pool = self._pool.status() if self._pool else None
        return {
            "offline": self.offline,
            "offline_reason": settings.offline_reason if self.offline else "",
            "mairui_offline": settings.mairui_offline,
            "licence_configured": bool(settings.licence_chain),
            "sample_only": self.sample_only,
            "status": self.status,
            "has_licence": bool(self.licence),
            "licence_active": self.licence,
            "licence_pool": pool,
        }

    def index_quotes(self) -> list[dict]:
        from src.market.indices import BOARD_INDICES

        return [self._index_quote_item(spec) for spec in BOARD_INDICES]

    def _index_quote_item(self, spec: dict) -> dict:
        code = spec["code"]
        row = self._index_quote(code)
        return {
            "code": code,
            "short": spec["short"],
            "label": spec["label"],
            "p": row.get("p"),
            "pc": row.get("pc"),
            "source": row.get("source") or "",
        }

    def _index_quote(self, code: str) -> dict:
        if self.offline:
            data = fixtures.INDEX_QUOTE.get(code) or {}
            return {"p": data.get("p"), "pc": data.get("pc"), "source": data.get("source") or "offline"}
        code6 = code.split(".")[0]
        for path in (
            f"/hsindex/real/time/{code}",
            f"/hsindex/real/time/{code6}",
            f"/hsindex/latest/{code}",
            f"/hsindex/latest/{code6}",
        ):
            parsed = _parse_index_quote(self._try_get(path))
            if parsed:
                parsed["source"] = "live"
                return parsed
        return {"p": None, "pc": None, "source": "unavailable"}

    def list_hs(self) -> list[Instrument]:
        if self.offline:
            return list(fixtures.UNIVERSE_HS)
        cached = self._cache_get("list_hs")
        if cached:
            return [normalize_instrument(x["dm"], x.get("mc", ""), x.get("jys", "")) for x in cached]
        data = self._get("/hslt/list")
        if isinstance(data, list) and not self.sample_only:
            self._cache_put("list_hs", data)
        return [normalize_instrument(x.get("dm", ""), x.get("mc", ""), x.get("jys", "")) for x in data]

    def search(
        self,
        q: str = "",
        market: str = "all",
        limit: int = 50,
        extra: dict | None = None,
        official_concept: str | None = None,
    ) -> list[dict]:
        items = self.list_hs() + self.list_bj()
        market = (market or "all").lower()
        official_set: set[str] | None = None
        official_source = ""
        if official_concept:
            official_set, official_source = self.concept_constituents(official_concept)
            if not official_set:
                official_set = None
        if market == "hs":
            items = [i for i in items if i.market == "hs"]
        elif market == "kc":
            items = [i for i in items if i.market == "kc"]
        elif market == "bj":
            items = [i for i in items if i.market == "bj"]
        elif market == "sh":
            items = [i for i in items if i.exchange == "SH"]
        elif market == "sz":
            items = [i for i in items if i.exchange == "SZ"]
        elif market == "cy":
            items = [i for i in items if i.code6.startswith("300")]
        needle = (q or "").strip()
        extra_needles = search_needles(needle, extra)
        out = []
        for inst in items:
            if official_set is not None and inst.code6 not in official_set:
                continue
            industry = fixtures.INDUSTRY.get(inst.code6, "")
            profile = fixtures.PROFILE.get(inst.code6) or {}
            concept = profile.get("concept") or ""
            tax = classify(industry, concept, extra)
            hay = " ".join(
                [
                    inst.name,
                    inst.code6,
                    inst.code_full,
                    industry,
                    concept,
                    tax.get("sector") or "",
                    tax.get("sw_l1") or "",
                    tax.get("hot_concepts") or "",
                ]
            ).lower()
            if needle:
                hit = needle.lower() in hay
                if not hit and extra_needles:
                    hit = any(token.lower() in hay for token in extra_needles)
                if not hit:
                    continue
            row = {
                "code6": inst.code6,
                "code_full": inst.code_full,
                "name": inst.name,
                "market": inst.market,
                "industry": industry,
                "sector": tax.get("sector") or "",
                "sw_l1": tax.get("sw_l1") or "",
                "hot_concepts": tax.get("hot_concepts") or "",
            }
            if official_source:
                row["concept_source"] = official_source
            out.append(row)
            if len(out) >= limit:
                break
        return out

    def list_exchange(self, exchange: str) -> list[Instrument]:
        key = (exchange or "").lower()
        if key == "bj":
            return self.list_bj()
        items = self.list_hs()
        if key == "sh":
            return [i for i in items if i.exchange == "SH"]
        if key == "sz":
            return [i for i in items if i.exchange == "SZ"]
        raise MarketError(f"未知交易所: {exchange}")

    def list_board(self, board: str) -> list[Instrument]:
        key = (board or "").lower()
        items = self.list_hs()
        if key == "cy":
            return [i for i in items if i.code6.startswith("300")]
        if key == "kc":
            return [i for i in items if i.market == "kc"]
        raise MarketError(f"未知板块: {board}")

    def list_bj(self) -> list[Instrument]:
        if self.offline:
            return list(fixtures.UNIVERSE_BJ)
        cached = self._cache_get("list_bj")
        if cached:
            return [normalize_instrument(x["dm"], x.get("mc", ""), x.get("jys", "")) for x in cached]
        try:
            data = self._get("/bj/list/all")
        except MarketError:
            return []
        if isinstance(data, list) and not self.sample_only:
            self._cache_put("list_bj", data)
        return [normalize_instrument(x.get("dm", ""), x.get("mc", ""), x.get("jys", "")) for x in data]

    def quote(self, inst: Instrument) -> dict:
        if self.offline:
            return fixtures.QUOTE.get(inst.code6, {"source": "offline"})
        data = self._get(f"/hsrl/ssjy/{inst.code6}")
        row = data[0] if isinstance(data, list) else data
        return _ssjy_quote(row, "live")

    def profile(self, inst: Instrument, extra: dict | None = None) -> dict:
        if self.offline:
            return _with_taxonomy(dict(fixtures.PROFILE.get(inst.code6, {"source": "offline"})), extra)
        out = {"industry": "", "concept": "", "business": "", "source": "live"}
        try:
            zg = self._get(f"/hszg/zg/{inst.code6}")
            names = [x.get("name", "") for x in zg if isinstance(x, dict)]
            industries = [n for n in names if "申万" in n or "行业" in n]
            concepts = [n.split("-")[-1] for n in names if n]
            out["industry"] = industries[0].split("-")[-1] if industries else (concepts[0] if concepts else "")
            out["concept"] = ",".join(concepts[:6])
        except MarketError:
            pass
        try:
            info = self._get(f"/hscp/gsjj/{inst.code6}")
            row = info[0] if isinstance(info, list) else info
            out["business"] = row.get("bscope") or row.get("desc") or ""
            if row.get("idea"):
                out["concept"] = row["idea"]
        except MarketError:
            pass
        return _with_taxonomy(out, extra)

    def holders(self, inst: Instrument) -> dict:
        if self.offline:
            raw = fixtures.HOLDERS.get(inst.code6)
            if not raw:
                return {"holders": None, "holders_detail": [], "top_holders": None, "top_holders_detail": [], "source": "offline"}
            return _pack_holders(raw.get("holders_detail") or [], raw.get("top_holders_detail") or [], "offline")
        flow = _holder_rows(self._try_get(f"/hsstock/financial/flowholder/{inst.code_full}") or self._try_get(f"/hscp/ltgd/{inst.code6}"))
        top = _holder_rows(self._try_get(f"/hsstock/financial/topholder/{inst.code_full}") or self._try_get(f"/hscp/sdgd/{inst.code6}"))
        return _pack_holders(flow, top, "live")

    def hszg_tree(self) -> list[dict]:
        if self.offline:
            return []
        cached = self._cache_get("hszg_list")
        if isinstance(cached, list) and cached:
            return cached
        data = self._try_get("/hszg/list") or []
        rows = data if isinstance(data, list) else []
        if rows and not self.sample_only:
            self._cache_put("hszg_list", rows)
        return rows

    def concept_constituents(self, label: str) -> tuple[set[str], str]:
        from src.market.hszg import constituent_codes, match_concept_nodes

        if self.offline:
            codes = set(fixtures.CONCEPT_OFFICIAL.get(label) or [])
            return codes, "offline-fixture" if codes else ""
        nodes = self.hszg_tree()
        tree_codes = match_concept_nodes(label, nodes)
        if not tree_codes:
            return set(), ""
        all_codes: set[str] = set()
        source = ""
        for tc in tree_codes[:4]:
            key = f"hszg_gg_{tc}"
            cached = self._cache_get(key)
            if isinstance(cached, list) and cached:
                rows = cached
            else:
                rows = self._try_get(f"/hszg/gg/{tc}") or []
                if isinstance(rows, list) and rows and not self.sample_only:
                    self._cache_put(key, rows)
            for code in constituent_codes(rows if isinstance(rows, list) else []):
                all_codes.add(code)
            if not source:
                source = f"hszg/gg/{tc}"
        return all_codes, source

    def indicators(self, inst: Instrument) -> dict:
        if self.offline:
            return dict(fixtures.INDICATORS.get(inst.code6) or {"source": "offline"})
        if inst.market == "bj":
            return {"source": "unavailable"}
        data = self._try_get(f"/hsstock/indicators/{inst.code_full}")
        rows = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
        row = rows[-1] if rows else {}
        return {
            "pct3": row.get("3d"),
            "pct5": row.get("5d"),
            "pct10": row.get("10d"),
            "source": "live",
        }

    def close_on_date(self, inst: Instrument, target: str) -> float | None:
        from src.market.calendar import nearest_trading_day_on_or_before

        day = nearest_trading_day_on_or_before(_norm_day(target), self) or _norm_day(target)
        if not day:
            return None
        bars = self.history(inst, end=day, limit=12)
        if not bars:
            bars = self.history(inst, limit=30)
        target_int = int(day)
        best_day = 0
        best_close = None
        for row in bars:
            bd = int(_bar_day(row) or "0")
            if bd <= target_int and bd >= best_day:
                best_day = bd
                best_close = row.get("c")
        return best_close

    def limit_pool_codes(self, kind: str = "up", day: str | None = None) -> set[str]:
        key = (kind or "up").lower()
        if key not in {"up", "down"}:
            key = "up"
        if self.offline:
            pool = fixtures.LIMIT_UP if key == "up" else fixtures.LIMIT_DOWN
            return set(pool)
        d = day or date.today().isoformat()
        path = "/hslt/ztgc" if key == "up" else "/hslt/dtgc"
        data = self._try_get(f"{path}/{d}") or []
        codes: set[str] = set()
        for row in data if isinstance(data, list) else []:
            if not isinstance(row, dict):
                continue
            dm = str(row.get("dm") or row.get("code") or "")
            c6 = code6_of(dm) if dm else ""
            if c6:
                codes.add(c6)
        return codes

    def finance(self, inst: Instrument) -> dict:
        if self.offline:
            return fixtures.FINANCE.get(inst.code6, {"source": "offline"})
        if inst.market == "bj":
            return self._finance_bj(inst)
        out = {"source": "live"}
        try:
            psi = self._get(f"/hsstock/financial/pershareindex/{inst.code_full}")
            row = psi[0] if isinstance(psi, list) else psi
            for key in ("mgwfplr", "mgjzc", "jbmgsy", "xsmlv", "jlv"):
                out[key] = row.get(key)
        except MarketError:
            pass
        try:
            income = self._get(f"/hsstock/financial/income/{inst.code_full}")
            row = income[0] if isinstance(income, list) else income
            yffy = row.get("yffy")
            out["yffy"] = None if yffy in (None, "", "-", 0, "0") else yffy
        except MarketError:
            pass
        try:
            cap = self._get(f"/hsstock/financial/capital/{inst.code_full}")
            row = cap[0] if isinstance(cap, list) else cap
            out["zgb"] = row.get("zgb")
            out["ysltag"] = row.get("ysltag")
        except MarketError:
            try:
                inst_info = self._get(f"/hsstock/instrument/{inst.code_full}")
                row = inst_info[0] if isinstance(inst_info, list) else inst_info
                out["zgb"] = row.get("tv")
                out["ysltag"] = row.get("fv")
            except MarketError:
                pass
        return out

    def _finance_bj(self, inst: Instrument) -> dict:
        out: dict[str, Any] = {"source": "live"}
        psi = self._try_get(f"/bj/financial/pershareindex/{inst.code_full}")
        if isinstance(psi, list) and psi:
            row = psi[0]
        elif isinstance(psi, dict):
            row = psi
        else:
            row = {}
        for key in ("mgwfplr", "mgjzc", "jbmgsy", "xsmlv", "jlv"):
            if key in row:
                out[key] = row.get(key)
        income = self._try_get(f"/bj/financial/income/{inst.code_full}")
        if isinstance(income, list) and income:
            irow = income[0]
            yffy = irow.get("yffy")
            out["yffy"] = None if yffy in (None, "", "-", 0, "0") else yffy
        cap = self._try_get(f"/bj/financial/capital/{inst.code_full}")
        if isinstance(cap, list) and cap:
            crow = cap[0]
            out["zgb"] = crow.get("zgb")
            out["ysltag"] = crow.get("ysltag")
        return out

    def quotes_many(self, insts: list[Instrument]) -> dict[str, dict]:
        if self.offline:
            return {i.code6: self.quote(i) for i in insts}
        out: dict[str, dict] = {}
        batch: list[Instrument] = []
        for inst in insts:
            batch.append(inst)
            if len(batch) == 20:
                out.update(self._quotes_batch(batch))
                batch = []
        if batch:
            out.update(self._quotes_batch(batch))
        return out

    def _quotes_batch(self, insts: list[Instrument]) -> dict[str, dict]:
        codes = ",".join(i.code6 for i in insts)
        try:
            data = self._get(f"/hsrl/ssjy_more/{codes}")
            rows = data if isinstance(data, list) else [data]
            mapped = {}
            by_code = {str(r.get("dm") or r.get("code") or "").split(".")[0]: r for r in rows if isinstance(r, dict)}
            for inst in insts:
                row = by_code.get(inst.code6)
                if row:
                    mapped[inst.code6] = _ssjy_quote(row, "live")
                else:
                    mapped[inst.code6] = self.quote(inst)
            return mapped
        except MarketError:
            return {i.code6: self.quote(i) for i in insts}

    def history(
        self,
        inst: Instrument,
        adjust: str = "n",
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        if self.offline:
            out = list(fixtures.BARS.get(inst.code6) or [])
            return _filter_bars(out, start=start, end=end, limit=limit)
        if inst.market == "bj":
            if self.offline:
                out = list(fixtures.BARS.get(inst.code6) or [])
                return _filter_bars(out, start=start, end=end, limit=limit)
            key = f"bars_bj_{inst.code6}_{adjust}"
            cached = self._cache_get(key)
            if isinstance(cached, list) and cached:
                raw = [row for row in cached if isinstance(row, dict)]
                out = trim_bars(raw, settings.bars_max)
            else:
                try:
                    data = self._get(f"/bj/history/{inst.code_full}/d/{adjust}")
                except MarketError:
                    data = []
                rows = data if isinstance(data, list) else []
                out = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    out.append(
                        {
                            "d": row.get("t") or row.get("d") or row.get("date"),
                            "o": row.get("o"),
                            "h": row.get("h"),
                            "l": row.get("l"),
                            "c": row.get("c"),
                            "v": row.get("v"),
                        }
                    )
                out = trim_bars(out, settings.bars_max)
                if out:
                    self._cache_put(key, out)
            return _filter_bars(out, start=start, end=end, limit=limit)
        key = f"bars_{inst.code6}_{adjust}"
        cached = self._cache_get(key)
        if isinstance(cached, list) and cached:
            raw = [row for row in cached if isinstance(row, dict)]
            out = trim_bars(raw, settings.bars_max)
            if len(out) < len(raw):
                self._cache_put(key, out)
        else:
            try:
                data = self._get(f"/hsstock/history/{inst.code_full}/d/{adjust}")
            except MarketError:
                data = []
            rows = data if isinstance(data, list) else []
            out = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                out.append(
                    {
                        "d": row.get("t") or row.get("d") or row.get("date"),
                        "o": row.get("o"),
                        "h": row.get("h"),
                        "l": row.get("l"),
                        "c": row.get("c"),
                        "v": row.get("v"),
                    }
                )
            out = trim_bars(out, settings.bars_max)
            if out:
                self._cache_put(key, out)
        return _filter_bars(out, start=start, end=end, limit=limit)

    def capital_flow(self, inst: Instrument) -> list[dict]:
        if self.offline:
            return [_flow_point(x) for x in fixtures.FLOW.get(inst.code6) or []]
        try:
            data = self._get(f"/hsstock/history/transaction/{inst.code_full}")
        except MarketError:
            return []
        rows = data if isinstance(data, list) else []
        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(_flow_point(row))
        return out

    def capital_flow_on_date(self, inst: Instrument, yyyymmdd: str) -> dict:
        day = _norm_day(yyyymmdd)
        if self.offline:
            for row in fixtures.FLOW.get(inst.code6) or []:
                if _bar_day(row) == day:
                    return _flow_point(row)
            return {}
        try:
            data = self._get(f"/hsstock/history/transaction/{day}/{inst.code6}")
        except MarketError:
            return {}
        rows = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
        if not rows:
            return {}
        return _flow_point(rows[0] if isinstance(rows[0], dict) else {})

    def announcements(self, inst: Instrument, limit: int = 8) -> list[dict]:
        if self.offline:
            return list(fixtures.ANNOUNCEMENTS.get(inst.code6) or [])
        if inst.market == "bj":
            return []
        data = self._try_get(f"/hsstock/announcement/{inst.code_full}") or []
        rows = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
        out = []
        for row in rows[: max(1, int(limit))]:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "t": row.get("t") or "",
                    "title": row.get("zt") or row.get("zy") or "",
                    "url": row.get("nr") or "",
                    "kind": "财报" if row.get("lx") == 1 else "其他",
                }
            )
        return out

    def interactive_qa(self, inst: Instrument, limit: int = 5) -> list[dict]:
        if self.offline:
            return list(fixtures.INTERACTIVE_QA.get(inst.code6) or [])
        if inst.market == "bj":
            return []
        data = self._try_get(f"/hsstock/interactiveqa/{inst.code_full}") or []
        rows = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
        out = []
        for row in rows[: max(1, int(limit))]:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "t": row.get("t") or row.get("qt") or "",
                    "q": row.get("q") or row.get("qh") or "",
                    "a": row.get("a") or "",
                    "at": row.get("at") or "",
                }
            )
        return out

    def limit_performance(self, inst: Instrument, limit: int = 3) -> list[dict]:
        if self.offline:
            row = fixtures.LIMIT_PERF.get(inst.code6)
            return [dict(row)] if row else []
        if inst.market == "bj":
            return []
        data = self._try_get(f"/hsstock/lup/limit/{inst.code_full}") or []
        rows = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
        out = []
        for row in rows[: max(1, int(limit))]:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "t": row.get("t") or "",
                    "direction": row.get("dr"),
                    "limit_up_amount": row.get("ua"),
                    "break_count": row.get("bu"),
                    "seal_ratio": row.get("vr"),
                    "boards": row.get("sc"),
                }
            )
        return out

    def auction(self, inst: Instrument, limit: int = 3) -> list[dict]:
        if self.offline:
            row = fixtures.AUCTION.get(inst.code6)
            return [dict(row)] if row else []
        if inst.market == "bj":
            return []
        data = self._try_get(f"/hsstock/lup/auction/{inst.code_full}") or []
        rows = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
        out = []
        for row in rows[: max(1, int(limit))]:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "t": row.get("t") or "",
                    "open_vol": row.get("ov"),
                    "close_vol": row.get("cv"),
                    "vs_prev": row.get("bp"),
                }
            )
        return out

    def dragon_tiger_date(self) -> str:
        if self.offline:
            return fixtures.DRAGON_TIGER_DATE
        data = self._try_get("/hilh/mrxq") or {}
        row = data[0] if isinstance(data, list) and data else data
        if isinstance(row, dict):
            return str(row.get("t") or "")[:10]
        return ""

    def dragon_tiger_codes(self) -> set[str]:
        if self.offline:
            return set(fixtures.DRAGON_TIGER_POOL)
        data = self._try_get("/hilh/mrxq") or {}
        row = data[0] if isinstance(data, list) and data else data
        if not isinstance(row, dict):
            return set()
        codes: set[str] = set()
        for key, items in row.items():
            if key == "t" or not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                dm = str(item.get("dm") or "")
                c6 = code6_of(dm) if dm else ""
                if c6:
                    codes.add(c6)
        return codes

    def sector_funds_top(self, kind: str = "industry", limit: int = 8) -> list[dict]:
        if self.offline:
            rows = fixtures.SECTOR_FUNDS_INDUSTRY if kind == "industry" else fixtures.SECTOR_FUNDS_CONCEPT
            return list(rows[: max(1, int(limit))])
        path = "/hibk/zjhhy" if kind == "industry" else "/hibk/gnbk"
        data = self._try_get(path) or []
        rows = data if isinstance(data, list) else []
        out = []
        for row in rows[: max(1, int(limit))]:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "name": row.get("mc") or "",
                    "code": row.get("dm") or "",
                    "pct": row.get("zdf"),
                    "net_in": row.get("jlr"),
                    "net_rate": row.get("jlrl"),
                    "leader": row.get("lzgmc") or "",
                    "leader_code": row.get("lzgdm") or "",
                }
            )
        return out

    def fund_holdings(self, inst: Instrument) -> list[dict]:
        if self.offline:
            return list(fixtures.FUNDS.get(inst.code6) or [])
        data = self._try_get(f"/hscp/jjcg/{inst.code6}")
        rows = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "name": row.get("name") or row.get("jjmc") or row.get("fund") or "",
                    "shares": row.get("cgs") or row.get("shares"),
                    "pct": row.get("zltg") or row.get("pct"),
                    "value": row.get("sz") or row.get("value"),
                }
            )
        return out

    def events(self, inst: Instrument) -> dict:
        if self.offline:
            ev = dict(fixtures.EVENTS.get(inst.code6, {"dividends": [], "seo": [], "unlock": []}))
            ev["cninfo_url"] = cninfo_url(inst.code6)
            return ev
        out = {"dividends": [], "seo": [], "unlock": [], "cninfo_url": cninfo_url(inst.code6)}
        try:
            data = self._get(f"/hscp/jnfh/{inst.code6}")
            rows = data if isinstance(data, list) else [data]
            for row in rows[:8]:
                if isinstance(row, dict):
                    out["dividends"].append(row)
        except MarketError:
            pass
        try:
            data = self._get(f"/hscp/jnzf/{inst.code6}")
            rows = data if isinstance(data, list) else [data]
            for row in rows[:8]:
                if isinstance(row, dict):
                    out["seo"].append(row)
        except MarketError:
            pass
        try:
            data = self._get(f"/hscp/jjxs/{inst.code6}")
            rows = data if isinstance(data, list) else [data]
            for row in rows[:8]:
                if isinstance(row, dict):
                    out["unlock"].append(row)
        except MarketError:
            pass
        return out

    def list_index(self, code: str) -> list[Instrument]:
        from src.market.indices import constituent_paths, index_status

        st = index_status(code)
        if self.offline or self.sample_only:
            if st["enabled"] and st["codes"]:
                return resolve_instruments(st["codes"], self)
            return []
        cached = self._cache_get(f"index_{code}")
        if cached:
            return [
                normalize_instrument(x.get("dm", ""), x.get("mc", ""), x.get("jys", ""))
                for x in cached
                if isinstance(x, dict)
            ]
        if st["enabled"] and st["codes"]:
            return resolve_instruments(st["codes"], self)
        for path in constituent_paths(code):
            try:
                data = self._get(path)
            except MarketError:
                continue
            if isinstance(data, list) and len(data) >= 10:
                if not self.sample_only:
                    self._cache_put(f"index_{code}", data)
                return [
                    normalize_instrument(
                        x.get("dm") or x.get("code") or "",
                        x.get("mc") or x.get("name") or "",
                        x.get("jys", ""),
                    )
                    for x in data
                    if isinstance(x, dict)
                ]
        return []


def _as_float(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("%", "").replace(",", "").replace("+", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _ssjy_quote(row: Any, source: str) -> dict:
    if not isinstance(row, dict):
        return {"source": source}
    hs = row.get("hs")
    if hs is None:
        hs = row.get("tr")
    return {
        "p": row.get("p"),
        "pc": row.get("pc"),
        "pe": row.get("pe"),
        "sjl": row.get("sjl"),
        "hs": hs,
        "sz": row.get("sz"),
        "lt": row.get("lt"),
        "zdf60": row.get("zdf60"),
        "zdfnc": row.get("zdfnc"),
        "source": source,
    }


def _parse_index_quote(data: Any) -> dict | None:
    if not data:
        return None
    row = data[0] if isinstance(data, list) else data
    if not isinstance(row, dict):
        return None
    price = None
    for key in ("p", "price", "close", "c", "zs", "zx", "last", "index"):
        price = _as_float(row.get(key))
        if price is not None:
            break
    pct = None
    for key in ("pc", "zdf", "zf", "percent", "pct", "change_pct"):
        pct = _as_float(row.get(key))
        if pct is not None:
            break
    if price is None and pct is None:
        return None
    return {"p": price, "pc": pct}


def cninfo_url(code6: str) -> str:
    return f"https://www.cninfo.com.cn/new/disclosure/stock?orgId=&stockCode={code6}"


def _with_taxonomy(row: dict, extra: dict | None = None) -> dict:
    tax = classify(row.get("industry") or "", row.get("concept") or "", extra)
    out = dict(row)
    out["sector"] = tax["sector"]
    out["sw_l1"] = tax["sw_l1"]
    out["hot_concepts"] = tax["hot_concepts"]
    return out


def _holder_rows(data) -> list[dict]:
    if not data:
        return []
    latest = data[0] if isinstance(data, list) else data
    detail = latest.get("sdgd") if isinstance(latest, dict) and "sdgd" in latest else data
    if not isinstance(detail, list):
        return []
    return [x for x in detail[:10] if isinstance(x, dict)]


def _pack_holders(flow_raw: list, top_raw: list, source: str) -> dict:
    flow = normalize_holders(flow_raw)
    top = normalize_holders(top_raw)
    return {
        "holders": summarize(flow) or summarize(top),
        "holders_detail": flow,
        "top_holders": summarize(top),
        "top_holders_detail": top,
        "source": source,
    }


def _flow_point(row: dict) -> dict:
    net = row.get("zljme") or row.get("net_in") or row.get("jlje")
    inflow = row.get("zljmr") or row.get("inflow") or row.get("lrje") or row.get("main_in") or row.get("zmbljcje")
    outflow = row.get("zljmc") or row.get("outflow") or row.get("lcje") or row.get("zmsljcje")
    if inflow is None and outflow is None and net not in (None, ""):
        try:
            n = float(net)
        except (TypeError, ValueError):
            n = None
        if n is not None:
            inflow = n if n > 0 else 0
            outflow = -n if n < 0 else 0
    if net in (None, "") and inflow is not None and outflow is not None:
        try:
            net = float(inflow) - float(outflow)
        except (TypeError, ValueError):
            pass
    return {"d": row.get("t") or row.get("d"), "net_in": net, "inflow": inflow, "outflow": outflow}


def _norm_day(value: str | None) -> str:
    return str(value or "").replace("-", "").replace("/", "")[:8]


def _bar_day(row: dict) -> str:
    return str(row.get("d") or row.get("t") or row.get("date") or "").replace("-", "")[:8]


def _filter_bars(rows: list[dict], start: str | None = None, end: str | None = None, limit: int | None = None) -> list[dict]:
    out = list(rows)

    def norm(value: str | None) -> str:
        return str(value or "").replace("-", "")[:8]

    if start:
        ns = norm(start)
        out = [r for r in out if _bar_day(r) >= ns]
    if end:
        ne = norm(end)
        out = [r for r in out if _bar_day(r) <= ne]
    if limit:
        out = out[-max(1, int(limit)) :]
    return out


def resolve_instruments(codes: list[str], client: MarketClient) -> list[Instrument]:
    known = {i.code6: i for i in fixtures.WATCH_SEED}
    try:
        catalog = client.list_hs() + client.list_bj()
    except MarketError:
        catalog = []
    for item in catalog:
        known[item.code6] = item
    out: list[Instrument] = []
    for raw in codes:
        key = code6_of(raw)
        if key in known:
            out.append(known[key])
        else:
            out.append(normalize_instrument(raw))
    return out
