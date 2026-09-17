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
    assert 'id="instList"' in html
    assert 'id="futuresList"' in html
    assert 'id="shareUpload"' in html
    assert "/export-share" in html
    assert "只跑这条" in html
    assert "对照上一份" in html
    assert "历史对话" in html
