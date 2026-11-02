import json

from fastapi.testclient import TestClient

from src.main import app
from src.market.fixtures import WATCH_SEED
from src.query.engine import REFRESH_SNAPSHOT, fetch_need
from src.market.normalize import normalize_instrument
from src.query.snapshot import (
    compose_snapshot,
    load_table_snapshot,
    open_pool_snapshot,
    merge_partial_snapshot,
    save_table_snapshot,
)


def test_fetch_need_snapshot_empty():
    assert fetch_need({"quote", "finance"}, REFRESH_SNAPSHOT) == set()


def test_snapshot_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.settings.data_dir", tmp_path)
    rows = [{"code6": "600038", "code_full": "600038.SH", "name": "中直", "price": 10, "pct": 1}]
    save_table_snapshot(
        1,
        pool="watch",
        field_keys=["code", "price", "pct"],
        codes=["600038.SH"],
        rows=rows,
        clock={"as_of": "2026-09-22", "source": "live"},
        refresh_mode="full",
    )
    snap = load_table_snapshot(1)
    assert snap and snap["rows"][0]["price"] == 10


def test_api_snapshot_mode():
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        client.put(
            "/api/watchlist",
            json={"items": [{"code": i.code_full} for i in WATCH_SEED[:2]]},
            headers=headers,
        )
        full = client.post("/api/query/run", json={"refresh_mode": "full"}, headers=headers)
        assert full.status_code == 200
        snap = client.post("/api/query/run", json={"refresh_mode": "snapshot"}, headers=headers)
        assert snap.status_code == 200
        assert snap.json()["refresh_mode"] == "snapshot"
        assert snap.json()["rows"]


def test_single_code_query_does_not_replace_pool_snapshot():
    """详情和「只看这一只」走临时代码，不能把自选快照换成这一只。"""
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        client.put(
            "/api/watchlist",
            json={"items": [{"code": i.code_full} for i in WATCH_SEED[:2]]},
            headers=headers,
        )
        full = client.post("/api/query/run", json={"refresh_mode": "full"}, headers=headers)
        assert full.status_code == 200
        kept = full.json()["total"]
        one = WATCH_SEED[0].code_full
        detail = client.post(
            "/api/query/run",
            json={"codes": [one], "refresh_mode": "cache", "pool_name": "筛选一次"},
            headers=headers,
        )
        assert detail.status_code == 200
        snap = client.post("/api/query/run", json={"refresh_mode": "snapshot"}, headers=headers)
        assert snap.status_code == 200, snap.text
        body = snap.json()
        assert body["total"] == kept
        assert body["snapshot"]["pool_id"] == "watch"


def test_stream_covering_the_pool_saves_and_a_short_page_does_not():
    """自选不满一页时，流式查询仍是整表，要留下快照；只流一只不能把快照切短。"""
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        client.put(
            "/api/watchlist",
            json={"items": [{"code": i.code_full} for i in WATCH_SEED[:2]]},
            headers=headers,
        )
        streamed = client.post(
            "/api/query/stream",
            json={"refresh_mode": "cache", "limit": 100},
            headers=headers,
        )
        assert streamed.status_code == 200, streamed.text
        snap = client.post("/api/query/run", json={"refresh_mode": "snapshot"}, headers=headers)
        assert snap.status_code == 200, snap.text
        assert snap.json()["total"] == 2
        client.post("/api/query/stream", json={"refresh_mode": "cache", "limit": 1}, headers=headers)
        again = client.post("/api/query/run", json={"refresh_mode": "snapshot"}, headers=headers)
        assert again.status_code == 200, again.text
        assert again.json()["total"] == 2


def test_legacy_one_stock_file_is_not_a_watch_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.settings.data_dir", tmp_path)
    folder = tmp_path / "snapshots"
    folder.mkdir()
    (folder / "user_1.json").write_text(
        json.dumps(
            {
                "pool": "筛选一次",
                "rows": [{"code6": "920091", "name": "大鹏工业", "price": 33.51, "industry": "机械"}],
                "field_keys": ["price", "industry"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert load_table_snapshot(1, "watch") is None


def test_legacy_watch_file_still_loads(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.settings.data_dir", tmp_path)
    folder = tmp_path / "snapshots"
    folder.mkdir()
    (folder / "user_1.json").write_text(
        json.dumps({"pool": "自选", "rows": [{"code6": "600038", "price": 10}], "field_keys": ["price"]}),
        encoding="utf-8",
    )
    snap = load_table_snapshot(1, "watch")
    assert snap and snap["rows"][0]["price"] == 10


def _inst(code: str, name: str = ""):
    return normalize_instrument(code, name)


def test_partial_pages_keep_earlier_rows_and_donate_the_intersection(tmp_path, monkeypatch):
    """沪市查到一半也要留下。自选里被盖住的那只用更新的格子，空格子和其余股票仍用自选。"""
    monkeypatch.setattr("src.config.settings.data_dir", tmp_path)
    save_table_snapshot(
        1,
        pool="自选",
        pool_id="watch",
        field_keys=["price", "yffy"],
        codes=["688001.SH", "688002.SH"],
        rows=[
            {"code6": "688001", "code_full": "688001.SH", "name": "甲", "price": 10, "yffy": 1.5},
            {"code6": "688002", "code_full": "688002.SH", "name": "乙", "price": 20, "yffy": 2.5},
        ],
        clock={"as_of": "2026-10-25T07:00:00+00:00", "source": "live"},
        refresh_mode="cache",
        saved_at="2026-10-25T07:00:00+00:00",
    )
    merge_partial_snapshot(
        1,
        pool="沪市全部",
        pool_id="exchange:sh",
        field_keys=["price"],
        rows=[{"code6": "688001", "code_full": "688001.SH", "name": "甲", "price": 11}],
        clock={},
        refresh_mode="cache",
        total=2000,
        saved_at="2026-10-25T08:00:00+00:00",
    )
    merge_partial_snapshot(
        1,
        pool="沪市全部",
        pool_id="exchange:sh",
        field_keys=["price"],
        rows=[{"code6": "600000", "code_full": "600000.SH", "name": "丙", "price": 8}],
        clock={},
        refresh_mode="cache",
        total=2000,
        saved_at="2026-10-25T08:10:00+00:00",
    )
    sh = load_table_snapshot(1, "exchange:sh")
    assert sh["complete"] is False
    assert {row["code6"] for row in sh["rows"]} == {"688001", "600000"}
    got = compose_snapshot(1, "watch", [_inst("688001.SH", "甲"), _inst("688002.SH", "乙")])
    by = {row["code6"]: row for row in got["rows"]}
    assert [row["code6"] for row in got["rows"]] == ["688001", "688002"]
    assert by["688001"]["price"] == 11
    assert by["688001"]["yffy"] == 1.5
    assert by["688002"]["price"] == 20
    assert got["own_used"] == 1
    assert got["sources"][0]["pool_id"] == "exchange:sh"
    assert got["sources"][0]["complete"] is False
    assert got["sources"][0]["used"] == 1
    assert got["sources"][0]["covered"] == 2


def test_newer_complete_exchange_feeds_the_board_without_wiping_blanks(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.settings.data_dir", tmp_path)
    save_table_snapshot(
        1,
        pool="科创板全部",
        pool_id="board:kc",
        field_keys=["price", "yffy"],
        codes=["688001.SH"],
        rows=[{"code6": "688001", "code_full": "688001.SH", "name": "甲", "price": 10, "yffy": 3}],
        clock={"source": "live"},
        refresh_mode="full",
        saved_at="2026-10-25T07:00:00+00:00",
    )
    save_table_snapshot(
        1,
        pool="沪市全部",
        pool_id="exchange:sh",
        field_keys=["price", "yffy"],
        codes=["688001.SH", "600000.SH"],
        rows=[
            {"code6": "688001", "code_full": "688001.SH", "name": "甲", "price": 12, "yffy": None},
            {"code6": "600000", "code_full": "600000.SH", "name": "丙", "price": 8, "yffy": 9},
        ],
        clock={"source": "live"},
        refresh_mode="full",
        saved_at="2026-10-25T09:00:00+00:00",
    )
    got = compose_snapshot(1, "board:kc", [_inst("688001.SH", "甲")])
    assert got["rows"][0]["price"] == 12
    assert got["rows"][0]["yffy"] == 3
    assert got["sources"][0]["complete"] is True
    assert got["sources"][0]["pool"] == "沪市全部"
    assert got["own_used"] == 0


def test_older_superset_does_not_replace_a_newer_own_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.settings.data_dir", tmp_path)
    save_table_snapshot(
        1,
        pool="沪市全部",
        pool_id="exchange:sh",
        field_keys=["price"],
        codes=["688001.SH"],
        rows=[{"code6": "688001", "price": 1}],
        clock={},
        refresh_mode="full",
        saved_at="2026-10-25T06:00:00+00:00",
    )
    save_table_snapshot(
        1,
        pool="科创板全部",
        pool_id="board:kc",
        field_keys=["price"],
        codes=["688001.SH"],
        rows=[{"code6": "688001", "price": 5}],
        clock={},
        refresh_mode="full",
        saved_at="2026-10-25T09:00:00+00:00",
    )
    got = compose_snapshot(1, "board:kc", [_inst("688001.SH")])
    assert got["rows"][0]["price"] == 5
    assert got["sources"] == []
    assert got["own_used"] == 1
    assert got["saved_at"] == "2026-10-25T09:00:00+00:00"


def test_opening_a_board_writes_the_newer_exchange_into_its_own_snapshot(tmp_path, monkeypatch):
    """打开创业板时，更晚的深市全部写进创业板自己的副本。深市文件保持原样。"""
    monkeypatch.setattr("src.config.settings.data_dir", tmp_path)
    save_table_snapshot(
        1,
        pool="创业板全部",
        pool_id="board:cy",
        field_keys=["price", "yffy"],
        codes=["300274.SZ", "300220.SZ"],
        rows=[
            {"code6": "300274", "code_full": "300274.SZ", "name": "阳光电源", "price": 10, "yffy": 3},
            {"code6": "300220", "code_full": "300220.SZ", "name": "金运激光", "price": 7, "yffy": 1},
        ],
        clock={},
        refresh_mode="full",
        saved_at="2026-10-25T07:00:00+00:00",
    )
    save_table_snapshot(
        1,
        pool="深市全部",
        pool_id="exchange:sz",
        field_keys=["price", "yffy"],
        codes=["300274.SZ", "000001.SZ"],
        rows=[
            {"code6": "300274", "code_full": "300274.SZ", "name": "阳光电源", "price": 12, "yffy": None},
            {"code6": "000001", "code_full": "000001.SZ", "name": "平安银行", "price": 8},
        ],
        clock={},
        refresh_mode="full",
        saved_at="2026-10-25T09:00:00+00:00",
    )
    opened = open_pool_snapshot(1, "board:cy", [_inst("300274.SZ", "阳光电源")])
    assert opened["rows"][0]["price"] == 12
    assert opened["rows"][0]["yffy"] == 3
    assert opened["rows"][0]["row_saved_at"] == "2026-10-25T09:00:00+00:00"
    assert opened["pool"] == "创业板全部"
    assert opened["sources"][0]["pool"] == "深市全部"
    assert opened["sources"][0]["complete"] is True
    own = load_table_snapshot(1, "board:cy")
    stored = {row["code6"]: row for row in own["rows"]}
    assert stored["300274"]["price"] == 12
    assert stored["300274"]["yffy"] == 3
    assert stored["300220"]["price"] == 7
    assert "000001" not in stored
    assert own["saved_at"] != "2026-10-25T07:00:00+00:00"
    parent = load_table_snapshot(1, "exchange:sz")
    assert {row["code6"]: row["price"] for row in parent["rows"]}["300274"] == 12
    assert parent["saved_at"] == "2026-10-25T09:00:00+00:00"
    archived = list((tmp_path / "snapshots" / "days").rglob("board_cy.json"))
    assert any(
        row.get("code6") == "300274" and row.get("price") == 12
        for path in archived
        for row in (json.loads(path.read_text(encoding="utf-8")).get("rows") or [])
    )
    again = open_pool_snapshot(1, "board:cy", [_inst("300274.SZ", "阳光电源")])
    assert again["sources"] == []
    assert load_table_snapshot(1, "board:cy")["saved_at"] == own["saved_at"]
    (tmp_path / "artifacts" / "query").mkdir(parents=True)
    from io import BytesIO

    from openpyxl import load_workbook

    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        exported = client.post(
            "/api/query/export",
            json={
                "rows": [opened["rows"][0]],
                "fields": ["name", "code", "price", "yffy"],
                "pool": "board:cy",
                "pool_name": "创业板全部",
                "export_label": "创业板全部_当前栏目",
            },
            headers=headers,
        )
        assert exported.status_code == 200, exported.text
        downloaded = client.get(exported.json()["download_url"], headers=headers)
        wb = load_workbook(BytesIO(downloaded.content), data_only=True)
        ws = wb.active
        header = [cell.value for cell in next(ws.iter_rows(max_row=1))]
        assert ws.cell(2, header.index("最新价") + 1).value == 12
        assert ws.cell(2, header.index("研发费用") + 1).value == 3


def test_opening_a_board_with_no_own_file_still_uses_the_covering_exchange(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.settings.data_dir", tmp_path)
    save_table_snapshot(
        1,
        pool="深市全部",
        pool_id="exchange:sz",
        field_keys=["price"],
        codes=["300274.SZ"],
        rows=[{"code6": "300274", "name": "阳光电源", "price": 12}],
        clock={},
        refresh_mode="full",
        saved_at="2026-10-25T09:00:00+00:00",
    )
    opened = open_pool_snapshot(1, "board:cy", [_inst("300274.SZ", "阳光电源")])
    assert opened["found"] is True
    assert opened["pool"] == "创业板全部"
    assert opened["rows"][0]["price"] == 12
    own = load_table_snapshot(1, "board:cy")
    assert own["rows"][0]["price"] == 12
    assert own["pool"] == "创业板全部"


def test_opening_watch_keeps_its_own_rows_when_a_complete_exchange_does_not_cover_them(tmp_path, monkeypatch):
    """完整快照盖不住整批自选时，打开自选仍只用自己的副本。"""
    monkeypatch.setattr("src.config.settings.data_dir", tmp_path)
    save_table_snapshot(
        1,
        pool="自选",
        pool_id="watch",
        field_keys=["price"],
        codes=["600038.SH", "300274.SZ"],
        rows=[
            {"code6": "600038", "name": "中直股份", "price": 10},
            {"code6": "300274", "name": "阳光电源", "price": 20},
        ],
        clock={},
        refresh_mode="full",
        saved_at="2026-10-25T08:00:00+00:00",
    )
    save_table_snapshot(
        1,
        pool="深市全部",
        pool_id="exchange:sz",
        field_keys=["price"],
        codes=["300274.SZ"],
        rows=[{"code6": "300274", "price": 99}],
        clock={},
        refresh_mode="full",
        saved_at="2026-10-25T09:00:00+00:00",
    )
    opened = open_pool_snapshot(1, "watch", [_inst("600038.SH", "中直股份"), _inst("300274.SZ", "阳光电源")])
    by = {row["code6"]: row for row in opened["rows"]}
    assert by["300274"]["price"] == 20
    assert by["600038"]["price"] == 10
    assert opened["sources"] == []
    stored = {row["code6"]: row["price"] for row in load_table_snapshot(1, "watch")["rows"]}
    assert stored == {"600038": 10, "300274": 20}


def test_opening_watch_takes_newer_rows_from_an_incomplete_exchange(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.settings.data_dir", tmp_path)
    save_table_snapshot(
        1,
        pool="自选",
        pool_id="watch",
        field_keys=["price", "yffy"],
        codes=["300274.SZ", "600038.SH"],
        rows=[
            {"code6": "300274", "name": "阳光电源", "price": 10, "yffy": 1.5},
            {"code6": "600038", "name": "中直股份", "price": 8, "yffy": 2},
        ],
        clock={},
        refresh_mode="full",
        saved_at="2026-10-25T07:00:00+00:00",
    )
    merge_partial_snapshot(
        1,
        pool="深市全部",
        pool_id="exchange:sz",
        field_keys=["price", "yffy"],
        rows=[{"code6": "300274", "code_full": "300274.SZ", "name": "阳光电源", "price": 12, "yffy": None}],
        total=2,
        clock={},
        refresh_mode="full",
        saved_at="2026-10-25T09:00:00+00:00",
    )
    opened = open_pool_snapshot(1, "watch", [_inst("300274.SZ", "阳光电源"), _inst("600038.SH", "中直股份")])
    by = {row["code6"]: row for row in opened["rows"]}
    assert by["300274"]["price"] == 12
    assert by["300274"]["yffy"] == 1.5
    assert by["600038"]["price"] == 8
    assert opened["sources"][0]["pool"] == "深市全部"
    own = load_table_snapshot(1, "watch")
    stored = {row["code6"]: row for row in own["rows"]}
    assert stored["300274"]["price"] == 12
    assert stored["300274"]["yffy"] == 1.5
    assert stored["600038"]["price"] == 8
    parent = load_table_snapshot(1, "exchange:sz")
    assert parent["rows"][0]["price"] == 12


def test_partial_merge_keeps_the_other_stock_in_a_complete_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.settings.data_dir", tmp_path)
    save_table_snapshot(
        1,
        pool="自选",
        pool_id="watch",
        field_keys=["price"],
        codes=["600038.SH", "600893.SH"],
        rows=[{"code6": "600038", "price": 10}, {"code6": "600893", "price": 20}],
        clock={},
        refresh_mode="cache",
        saved_at="2026-10-25T07:00:00+00:00",
    )
    merge_partial_snapshot(
        1,
        pool="自选",
        pool_id="watch",
        field_keys=["price"],
        rows=[{"code6": "600038", "price": 11}],
        clock={},
        refresh_mode="cache",
        total=2,
        saved_at="2026-10-25T08:00:00+00:00",
    )
    snap = load_table_snapshot(1, "watch")
    assert snap["complete"] is True
    by = {row["code6"]: row for row in snap["rows"]}
    assert set(by) == {"600038", "600893"}
    assert by["600038"]["price"] == 11
    assert by["600893"]["price"] == 20
    assert by["600893"]["row_saved_at"] == "2026-10-25T07:00:00+00:00"
    assert snap["taken_from"] == "2026-10-25T07:00:00+00:00"
    assert snap["taken_to"] == "2026-10-25T08:00:00+00:00"


def test_quote_merge_keeps_slow_fields_and_does_not_wipe_price(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.settings.data_dir", tmp_path)
    save_table_snapshot(
        1,
        pool="创业板全部",
        pool_id="board:cy",
        field_keys=["price", "pct", "industry"],
        codes=["300001.SZ", "300324.SZ"],
        rows=[
            {"code6": "300001", "code": "300001.SZ", "price": 10, "pct": 1, "industry": "计算机"},
            {"code6": "300324", "code": "300324.SZ", "price": 8, "pct": -1, "industry": "电子"},
        ],
        clock={},
        refresh_mode="full",
        saved_at="2026-10-25T07:00:00+00:00",
    )
    merge_partial_snapshot(
        1,
        pool="创业板全部",
        pool_id="board:cy",
        field_keys=["price", "pct", "industry"],
        rows=[{"code6": "300001", "price": 12, "pct": 2, "industry": None}],
        clock={},
        refresh_mode="quote",
        total=936,
        saved_at="2026-10-25T08:00:00+00:00",
    )
    snap = load_table_snapshot(1, "board:cy")
    by = {row["code6"]: row for row in snap["rows"]}
    assert by["300001"]["price"] == 12
    assert by["300001"]["industry"] == "计算机"
    assert by["300324"]["price"] == 8
    assert snap["complete"] is False
    assert snap["total"] == 936


def test_open_copy_export_writes_the_given_rows(tmp_path, monkeypatch):
    """导出带上行时只写文件，不把空价格重新查满。"""
    from io import BytesIO

    from openpyxl import load_workbook

    monkeypatch.setattr("src.config.settings.data_dir", tmp_path)
    (tmp_path / "artifacts" / "query").mkdir(parents=True)
    (tmp_path / "snapshots").mkdir(parents=True)
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        saved = client.post(
            "/api/query/run",
            json={"refresh_mode": "full", "pool": "watch"},
            headers=headers,
        )
        assert saved.status_code == 200, saved.text
        opened = client.get("/api/query/snapshot", params={"pool": "watch"}, headers=headers)
        assert opened.status_code == 200
        snap = opened.json()
        assert snap["found"] is True
        assert snap["rows"]
        kept_industry = {row["code6"]: row.get("industry") for row in snap["rows"]}
        quoted = client.post(
            "/api/query/run",
            json={
                "refresh_mode": "quote",
                "pool": "watch",
                "fields": ["name", "code", "price", "pct"],
            },
            headers=headers,
        )
        assert quoted.status_code == 200, quoted.text
        again = client.get("/api/query/snapshot", params={"pool": "watch"}, headers=headers).json()
        by = {row["code6"]: row for row in again["rows"]}
        for code, industry in kept_industry.items():
            if industry:
                assert by[code].get("industry") == industry
        sample = dict(next(iter(by.values())))
        sample["price"] = 123.45
        sample["pct"] = 1.25
        exported = client.post(
            "/api/query/export",
            json={
                "rows": [sample],
                "fields": ["name", "code", "price", "pct", "industry"],
                "pool": "watch",
                "pool_name": "自选",
                "export_label": "自选_当前栏目",
            },
            headers=headers,
        )
        assert exported.status_code == 200, exported.text
        body = exported.json()
        assert body["refresh_mode"] == "copy"
        assert body["count"] == 1
        downloaded = client.get(body["download_url"], headers=headers)
        assert downloaded.status_code == 200
        wb = load_workbook(BytesIO(downloaded.content), data_only=True)
        ws = wb.active
        header = [cell.value for cell in next(ws.iter_rows(max_row=1))]
        price_at = header.index("最新价") + 1
        assert ws.cell(2, price_at).value == 123.45


def test_page_with_an_error_still_merges_instead_of_being_dropped():
    from src.query.snapshot import snapshot_persist_kind

    assert snapshot_persist_kind("full", partial=True, stopped=False, fatal=True) == "merge"
    assert snapshot_persist_kind("quote", partial=False, stopped=False, fatal=True) == "merge"
    assert snapshot_persist_kind("full", partial=False, stopped=False, fatal=True) is None
    assert snapshot_persist_kind("full", partial=False, stopped=False, fatal=False) == "replace"


def test_ledger_replaces_sample_capital_and_fills_a_blank_page(tmp_path, monkeypatch):
    """全量账本里已有的股本和股东要写回副本。样例数字不能盖过实数，实数也不能被账本改掉。"""
    from src.market.fixtures import FINANCE, HOLDERS
    from src.query.resume_ledger import fresh_ledger, ledger_path, save_ledger
    from src.query.snapshot import load_table_snapshot, repair_saved_snapshot, save_table_snapshot

    monkeypatch.setattr("src.config.settings.data_dir", tmp_path)
    ledger = fresh_ledger(["300274", "300220", "300750"], ["zgb", "ltgb", "holders"], "full")
    ledger["rows"] = {
        "300274": {
            "code6": "300274",
            "zgb": 2073211424.0,
            "ltgb": 1587459661.0,
            "holders": "曹仁贤、香港中央结算有限公司、易方达创业板ETF",
        },
        "300220": {"code6": "300220", "zgb": 151200000.0, "holders": "甲、乙、丙"},
        "300750": {"code6": "300750", "zgb": 1.0, "holders": "不应覆盖"},
    }
    save_ledger(ledger_path(1, "board:cy", "full"), ledger)
    save_table_snapshot(
        1,
        pool="创业板全部",
        pool_id="board:cy",
        field_keys=["name", "zgb", "ltgb", "holders"],
        codes=["300274.SZ", "300220.SZ", "300750.SZ"],
        rows=[
            {
                "code6": "300274",
                "name": "阳光电源",
                "zgb": FINANCE["300274"]["zgb"],
                "ltgb": FINANCE["300274"]["ysltag"],
                "holders": HOLDERS["300274"]["holders"],
            },
            {"code6": "300220", "name": "邻股", "price": 9.5},
            {"code6": "300750", "name": "宁德时代", "zgb": 4627249686.0, "holders": "厦门瑞庭投资有限公司"},
        ],
        clock={},
        refresh_mode="full",
    )
    snap = load_table_snapshot(1, "board:cy")
    by = {row["code6"]: row for row in snap["rows"]}
    assert by["300274"]["zgb"] == 2073211424.0
    assert by["300274"]["ltgb"] == 1587459661.0
    assert by["300274"]["holders"].startswith("曹仁贤")
    assert "控股股东" not in by["300274"]["holders"]
    assert by["300220"]["zgb"] == 151200000.0
    assert by["300220"]["holders"] == "甲、乙、丙"
    assert by["300750"]["zgb"] == 4627249686.0
    assert by["300750"]["holders"] == "厦门瑞庭投资有限公司"
    again = repair_saved_snapshot(1, "board:cy")
    assert again["rows"]
