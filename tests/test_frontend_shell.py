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
    assert 'id="diffSelected"' in html
    assert 'id="diffLatest"' not in html
    assert "对照勾选的两份" in html
    assert "对照最近两份" not in html
    assert "function renderDiffSide" in html
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
    assert 'id="userLabel"' in html
    assert 'id="warehouseBox"' in html
    assert 'id="storageBox"' in html
    assert 'id="runtimeSave"' in html
    assert 'name="runtimeMode"' in html
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
    assert "移出白名单" in html
    assert 'id="reviewPending"' in html
    assert "data-alert-id" in html
    assert "data-del-review" in html
    assert "deleteReviewAlert" in html
    assert "data-drop-inst" in html
    assert "data-src-idx" in html
    assert "data-inst-origin" in html
    assert 'id="sourceList"' in html
    assert 'id="srcSave"' in html
    assert "检索源" in html
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
    assert "对照勾选的两份" in html
    assert "历史对话" in html


def test_list_refresh_ignores_stale_progress():
    """换池或再次刷新后，上一轮不得再改右上角进度。"""
    html = Path("docs/frontend/index.html").read_text(encoding="utf-8")
    assert "function supersedeListQuery" in html
    assert "function listQueryCurrent" in html
    assert "activeJobId" in html
    assert 'api("/query/jobs/" + jobId + "/cancel"' in html
    assert "if (poolId !== state.pool) supersedeListQuery();" in html
    assert 'if (gen != null && !listQueryCurrent(gen)) return;' in html


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
    assert "const poolId = it.code ? `index:${it.code}` : \"\";" in html
    assert "function revealPoolChip" in html
    assert "/markets/board" in html
    assert "startBoardClock" in html
    assert "上证：" in html
    assert "深成：" in html
    assert "科创：" in html
    assert "loadBoard" in html
    assert "无点位" in html
    assert 'n + "只"' not in html


def test_workbench_pct_column_sorts_index_constituents():
    html = Path("docs/frontend/index.html").read_text(encoding="utf-8")
    assert "sortedRows" in html
    assert "bindColumnSort" in html
    assert "th.sortable" in html
    assert "SORTABLE" in html
    assert 'pct: "desc"' in html
    assert 'code: "asc"' in html
    assert "点击按${f.label}排序" in html
    assert "排序只针对已加载的行" in html
    assert "function displayedQueryRows" in html
    # 点列头只排已加载的行，不能再发一次查询把后面几页丢掉
    sort_fn = html.split("function bindColumnSort", 1)[1].split("function fillRuleCodes", 1)[0]
    assert "runQuery(" not in sort_fn
    more_fn = html.split("async function loadMorePage", 1)[1].split("function renderSkeleton", 1)[0]
    assert "stream: true" in more_fn
    assert "noJobFallback: true" in more_fn
    assert "/watchlist/order" in html
    assert 'id="ruleCode"' in html
    assert "一只" in html
    # 自选排序改为按住拖动，删除改为右键菜单
    assert 'draggable="true"' in html
    assert "function moveWatch" in html
    assert "function openCtxMenu" in html
    # 列表 / 表格分页（导出不受分页影响）
    assert "data-pool-more" in html
    assert "PAGE_SIZE" in html
    # 导出选项弹窗：范围 / 新鲜度 / 列 + 预估与警告
    assert 'id="exportMask"' in html
    assert 'id="expConfirm"' in html
    assert "要导出" in html
    assert "export_label" in html
    assert 'id="expFreshOpts"' in html
    assert "用上次保存的表" in html
    assert "全部重新查一遍" in html
    assert "要导出哪些股票" in html
    assert "数字从哪里来" in html
    assert "表格里放什么" in html
    assert "function renderExportHint" in html
    assert 'id="colPresets"' in html
    assert "预设「看盘」" in html
    assert 'id="customConceptAdd"' in html
    assert "/markets/concepts" in html
    assert "自定义概念" in html
    assert "--up: #b42318" in html
    assert "--down: #1f7a4d" in html
    assert "function signedClass" in html
    assert 'return "flat"' in html


def test_workbench_picker_dialog_is_wide_and_short():
    html = Path("docs/frontend/index.html").read_text(encoding="utf-8")
    assert "picker-card" in html
    assert "picker-toolbar" in html
    assert "picker-tax" in html
    assert "min(900px" in html
    assert "min(96vh, 1080px)" in html
    assert ".picker-tax" in html
    tax_css = html.split(".picker-tax {", 1)[1].split("}", 1)[0]
    assert "flex: 0 0 400px" in tax_css
    assert "height: 400px" in tax_css
    assert "min-height: 400px" in tax_css
    assert "font: 15px/1.5" in html
    assert ".table-wrap { overflow: auto;" in html or "table-wrap { overflow: auto" in html


def test_query_hint_estimates_remaining_time():
    html = Path("docs/frontend/index.html").read_text(encoding="utf-8")
    assert "function formatRemain" in html
    assert "function etaSuffix" in html
    assert "正在估算剩余时间" in html
    assert "若后面每页也按这个速度，" in html
    assert "现价 ${done}/${total}${suffix}" in html
    assert '"本页资料"} ${done}/${total}${suffix}' in html
    assert 'id="queryHintExport"' in html
    assert "function renderStatusLines" in html


def test_export_job_hint_names_excel_progress():
    html = Path("docs/frontend/index.html").read_text(encoding="utf-8")
    assert "Excel表格导出进度：" in html
    assert "Excel表格导出完成：" in html
    assert "任务进行中" not in html


def test_query_buttons_peek_selected_columns():
    html = Path("docs/frontend/index.html").read_text(encoding="utf-8")
    assert 'data-action-peek="cache"' in html
    assert 'data-action-peek="quote"' in html
    assert 'data-action-peek="full"' in html
    assert "function rememberColumnChoice" in html
    assert "function chosenFieldList" in html
    assert "function actionPeekBlocks" in html
    assert "QUOTE_REFRESH_KEYS" in html
    assert "这些列会重做一遍。本机已有的直接用，缺的才去要。" in html
    assert "不换名单，只更新这些行情列。" in html
    assert "这些列全部重新向数据源要，不用本机已经存好的。" in html
    assert "本机今天已经有的就直接用" not in html
    assert html.count('tag.className = "peek-tag"') >= 2


def test_repeat_click_does_not_start_another_round():
    html = Path("docs/frontend/index.html").read_text(encoding="utf-8")
    assert "function sameListFlight" in html
    assert "exportBusy" in html
    assert "这一轮还在进行" in html
    assert "导出还在进行" in html
    assert "等上一轮结束" in html
    assert "导出排队，等当前刷新结束" in html
    assert "已经有一份导出在进行" in html
    refresh = html.split('getElementById("refreshBtn")', 1)[1].split("exportBtn", 1)[0]
    assert refresh.index("sameListFlight") < refresh.index("supersedeListQuery")
    query = html.split("async function runQuery(", 1)[1].split("async function downloadArtifact", 1)[0]
    assert query.index("sameListFlight") < query.index("supersedeListQuery")
    start = html.split('getElementById("expStart").addEventListener', 1)[1][:900]
    assert start.index("exportBusy") < start.index("closeExport")


def test_decision_card_overlay_sits_above_sticky_table_headers():
    html = Path("docs/frontend/index.html").read_text(encoding="utf-8")
    assert "isolation: isolate;" in html
    assert ".drawer-mask {" in html
    assert html.split(".drawer-mask {", 1)[1].split("}", 1)[0].count("z-index: 40") == 1
    assert html.split(".login-mask {", 1)[1].split("}", 1)[0].count("z-index: 40") == 1
    assert "#queryTable th" in html
    assert "z-index: 1;" in html.split("#queryTable th {", 1)[1].split("}", 1)[0]


def test_date_box_opens_the_saved_table():
    html = Path("docs/frontend/index.html").read_text(encoding="utf-8")
    assert "X日价" not in html
    assert "x_date" not in html
    assert "打开这一天保存过的查询表" in html
    assert "/query/snapshot-day?date=" in html
    assert "这一天没有可打开的查询表" in html
    assert '正在查看 " + (when || day) + " 的"' in html
    assert "已保存 " in html
    query = html.split("async function runQuery(", 1)[1].split("async function downloadArtifact", 1)[0]
    assert query.index("clearDateBox") < query.index("supersedeListQuery")
    payload = html.split("function queryPayload", 1)[1].split("function formatShanghaiMinute", 1)[0]
    assert "xDate" not in payload
    shown = html.split("function showSnapshotPool", 1)[1].split("\n    function ", 1)[0]
    assert "selectPool(" not in shown
    assert 'getElementById("xDate").addEventListener("change"' in html
