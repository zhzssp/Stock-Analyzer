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
