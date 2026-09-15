from __future__ import annotations

import json
from typing import Any

import httpx

from src.config import settings
from src.market import fixtures
from src.market.holders_diff import normalize_holders, summarize
from src.market.normalize import Instrument, code6_of, normalize_instrument
from src.market.taxonomy import classify, search_needles


class MarketError(RuntimeError):
    pass


class MarketClient:
    """Only module allowed to talk to Mairui.

    Demo licence responses are never persisted as live cache.
    """

    def __init__(self) -> None:
        self.offline = settings.mairui_offline or not settings.mairui_licence
        self.licence = settings.mairui_licence.strip()
        self.sample_only = False
        self.status = "offline" if self.offline else "unchecked"
        if not self.offline:
            self._probe()

    def _url(self, path: str) -> str:
        return f"{settings.mairui_base}{path}/{self.licence}"

    def _get(self, path: str) -> Any:
        if self.offline:
            raise MarketError("offline mode: live API disabled")
        try:
            resp = httpx.get(self._url(path), timeout=30.0)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            raise MarketError(str(exc)) from exc

    def _try_get(self, path: str) -> Any | None:
        try:
            return self._get(path)
        except MarketError:
            return None

    def _probe(self) -> None:
        if self.licence == settings.demo_licence:
            self.sample_only = True
            self.status = "demo-licence"
            return
        prices = []
        for code in ("000001", "600038", "002230"):
            try:
                data = httpx.get(self._url(f"/hsrl/ssjy/{code}"), timeout=20.0).json()
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
        path = settings.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _cache_put(self, key: str, payload: Any) -> None:
        if self.sample_only or self.offline:
            return
        path = settings.cache_dir / f"{key}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def health(self) -> dict:
        return {
            "offline": self.offline,
            "sample_only": self.sample_only,
            "status": self.status,
            "has_licence": bool(self.licence),
        }

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

    def search(self, q: str = "", market: str = "all", limit: int = 50) -> list[dict]:
        items = self.list_hs() + self.list_bj()
        market = (market or "all").lower()
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
        extra = search_needles(needle)
        out = []
        for inst in items:
            industry = fixtures.INDUSTRY.get(inst.code6, "")
            profile = fixtures.PROFILE.get(inst.code6) or {}
            concept = profile.get("concept") or ""
            tax = classify(industry, concept)
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
                if not hit and extra:
                    hit = any(token.lower() in hay for token in extra)
                if not hit:
                    continue
            out.append(
                {
                    "code6": inst.code6,
                    "code_full": inst.code_full,
                    "name": inst.name,
                    "market": inst.market,
                    "industry": industry,
                    "sector": tax.get("sector") or "",
                    "sw_l1": tax.get("sw_l1") or "",
                    "hot_concepts": tax.get("hot_concepts") or "",
                }
            )
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
        return {"p": row.get("p"), "pc": row.get("pc"), "pe": row.get("pe"), "sjl": row.get("sjl"), "source": "live"}

    def profile(self, inst: Instrument) -> dict:
        if self.offline:
            return _with_taxonomy(dict(fixtures.PROFILE.get(inst.code6, {"source": "offline"})))
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
        return _with_taxonomy(out)

    def holders(self, inst: Instrument) -> dict:
        if self.offline:
            raw = fixtures.HOLDERS.get(inst.code6)
            if not raw:
                return {"holders": None, "holders_detail": [], "top_holders": None, "top_holders_detail": [], "source": "offline"}
            return _pack_holders(raw.get("holders_detail") or [], raw.get("top_holders_detail") or [], "offline")
        flow = _holder_rows(self._try_get(f"/hsstock/financial/flowholder/{inst.code_full}") or self._try_get(f"/hscp/ltgd/{inst.code6}"))
        top = _holder_rows(self._try_get(f"/hsstock/financial/topholder/{inst.code_full}") or self._try_get(f"/hscp/sdgd/{inst.code6}"))
        return _pack_holders(flow, top, "live")

    def finance(self, inst: Instrument) -> dict:
        if self.offline:
            return fixtures.FINANCE.get(inst.code6, {"source": "offline"})
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
                    mapped[inst.code6] = {
                        "p": row.get("p"),
                        "pc": row.get("pc"),
                        "pe": row.get("pe"),
                        "sjl": row.get("sjl"),
                        "source": "live",
                    }
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
        elif inst.market == "bj":
            out = []
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
        from src.market.indices import CANDIDATE_PATHS, index_status

        st = index_status(code)
        if st["enabled"] and st["codes"]:
            return resolve_instruments(st["codes"], self)
        if self.offline or self.sample_only:
            return []
        cached = self._cache_get(f"index_{code}")
        if cached:
            return [normalize_instrument(x.get("dm", ""), x.get("mc", ""), x.get("jys", "")) for x in cached]
        for tmpl in CANDIDATE_PATHS:
            try:
                data = self._get(tmpl.format(code=code))
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


def cninfo_url(code6: str) -> str:
    return f"https://www.cninfo.com.cn/new/disclosure/stock?orgId=&stockCode={code6}"


def _with_taxonomy(row: dict) -> dict:
    tax = classify(row.get("industry") or "", row.get("concept") or "")
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
    inflow = row.get("zljmr") or row.get("inflow") or row.get("lrje") or row.get("main_in")
    outflow = row.get("zljmc") or row.get("outflow") or row.get("lcje")
    if inflow is None and outflow is None and net not in (None, ""):
        try:
            n = float(net)
        except (TypeError, ValueError):
            n = None
        if n is not None:
            inflow = n if n > 0 else 0
            outflow = -n if n < 0 else 0
    return {"d": row.get("t") or row.get("d"), "net_in": net, "inflow": inflow, "outflow": outflow}


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
    for item in client.list_hs() + client.list_bj():
        known[item.code6] = item
    out: list[Instrument] = []
    for raw in codes:
        key = code6_of(raw)
        if key in known:
            out.append(known[key])
        else:
            out.append(normalize_instrument(raw))
    return out
