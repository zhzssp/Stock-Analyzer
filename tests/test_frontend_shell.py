from pathlib import Path


def test_workbench_exposes_exchange_export_entry():
    html = Path("docs/frontend/index.html").read_text(encoding="utf-8")
    assert 'data-side="exchange"' in html
    assert 'id="exchangeChips"' in html
    assert "沪、深、北分开选、分开导" in html
    assert "currentExportPool" in html
    assert 'data-market="sh"' in html
    assert 'data-market="sz"' in html
    assert "上证指数 ≠ 沪市全部" in html


def test_workbench_exposes_landed_backend_entries():
    html = Path("docs/frontend/index.html").read_text(encoding="utf-8")
    assert 'id="archiveBtn"' in html
    assert 'id="diffBtn"' in html
    assert "/artifacts/diff" in html
    assert "/artifacts/" in html and "/preview" in html
    assert 'id="sessionList"' in html
    assert 'data-run="' in html
    assert "/monitor/jobs/" in html and "/run" in html
    assert "lastQueryCodes" in html
    assert 'id="replaceWatch"' in html
    assert 'method: "PUT"' in html
    assert 'data-market="cy"' in html
    assert 'id="swChips"' in html
    assert 'id="healthBar"' in html
    assert 'id="warehouseBox"' in html
    assert 'id="storageBox"' in html
    assert 'id="clockDirSave"' in html
    assert 'id="clockChart"' in html
    assert "/clock/series" in html
    assert "墙钟档案" in html
    assert "档案还没备份到远程" in html
    assert 'data-view="local"' in html
    assert 'id="cacheClear"' in html
    assert 'id="artifactPrune"' in html
    assert "/storage/cache/clear" in html
    assert "/storage/artifacts/prune" in html
    assert "只留最近导出" in html
    assert "本机数据" in html
    assert 'id="instList"' in html
    assert 'id="futuresList"' in html
    assert 'id="shareUpload"' in html
    assert "/export-share" in html
    assert "只跑这条" in html
    assert "添加规则" in html
    assert 'id="ruleMask"' in html
    assert 'id="ruleBuilder"' in html
    assert "data-del-rule" in html
    assert "规则定义 / 监控需求" in html
    assert 'id="ruleDefinition"' in html
    assert 'id="ruleNeed"' in html
    assert "不自动扫描（只给问答用）" in html
    assert "data-toggle-rule" in html
    assert "watch_rules" in html or "data-note=\"definition\"" in html
    assert "决策卡" in html
    assert 'data-monitor="today"' in html
    assert 'data-monitor="review"' in html
    assert 'id="reviewRun"' in html
    assert "/monitor/review/run" in html
    assert 'class="subtab on" data-monitor="today"' in html
    assert 'querySelectorAll("nav.tabs > .tab[data-view]")' in html
    assert "本轮守则" in html
    assert "/watchlist/" in html and "/card" in html
    assert "对照上一份" in html
    assert "历史对话" in html


def test_workbench_query_table_columns_are_resizable():
    html = Path("docs/frontend/index.html").read_text(encoding="utf-8")
    assert 'id="queryTable"' in html
    assert "col-resizer" in html
    assert "table-layout: fixed" in html
    assert "text-overflow: ellipsis" in html
    assert "sa_col_widths" in html
    assert "bindColResize" in html
    assert 'title="${escAttr(display)}"' in html


def test_workbench_shows_core_index_board():
    html = Path("docs/frontend/index.html").read_text(encoding="utf-8")
    assert 'id="boardBar"' in html
    assert "/markets/board" in html
    assert "startBoardClock" in html
    assert "上证：" in html
    assert "深成：" in html
    assert "科创：" in html
    assert "loadBoard" in html


def test_workbench_pct_column_sorts_index_constituents():
    html = Path("docs/frontend/index.html").read_text(encoding="utf-8")
    assert "sortedRows" in html
    assert "bindPctSort" in html
    assert 'th[data-key="pct"]' in html
    assert "点击按涨跌幅排序" in html
    assert 'sortKey: ""' in html
    assert 'sortDir: "desc"' in html
    assert 'state.sortKey = "pct"' in html
    assert "/watchlist/order" in html
    assert 'id="ruleCode"' in html
    assert "一只" in html
    assert "data-watch-up" in html
    assert "换手和市值默认不勾" in html


def test_workbench_picker_dialog_is_wide_and_short():
    html = Path("docs/frontend/index.html").read_text(encoding="utf-8")
    assert "picker-card" in html
    assert "picker-toolbar" in html
    assert "picker-tax" in html
    assert "min(900px" in html
    assert "min(86vh, 680px)" in html
    assert "font: 15px/1.5" in html
    assert ".table-wrap { overflow: auto;" in html or "table-wrap { overflow: auto" in html


def test_decision_card_overlay_sits_above_sticky_table_headers():
    html = Path("docs/frontend/index.html").read_text(encoding="utf-8")
    assert "isolation: isolate;" in html
    assert ".drawer-mask {" in html
    assert html.split(".drawer-mask {", 1)[1].split("}", 1)[0].count("z-index: 40") == 1
    assert html.split(".login-mask {", 1)[1].split("}", 1)[0].count("z-index: 40") == 1
    assert "#queryTable th" in html
    assert "z-index: 1;" in html.split("#queryTable th {", 1)[1].split("}", 1)[0]
