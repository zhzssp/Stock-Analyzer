from openpyxl import load_workbook

from src.platform.export_xlsx import as_yi, write_query_xlsx


def test_as_yi_converts_raw_shares_and_yuan_but_keeps_sample_yi():
    assert as_yi(19_405_918_198) == 194.06
    assert as_yi(22_604_455_882) == 226.04
    assert as_yi(412.5) == 412.5
    assert as_yi(8.6) == 8.6
    assert as_yi(None) is None
    assert as_yi("") is None


def test_query_excel_writes_yi_with_two_decimals(monkeypatch, tmp_path):
    from src.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.artifact_dir.mkdir(parents=True, exist_ok=True)
    path = write_query_xlsx(
        [{"name": "平安银行", "zgb": 19_405_918_198, "ltgb": 19_405_684_991, "mcap": 22_604_455_882, "fcap": 18_442_544_043}],
        ["name", "zgb", "ltgb", "mcap", "fcap"],
        "自选",
    )
    wb = load_workbook(path, data_only=True)
    ws = wb.active
    assert [ws.cell(1, col).value for col in range(1, 6)] == ["名称", "总股本(亿)", "流通股本(亿)", "总市值(亿)", "流通市值(亿)"]
    assert ws.cell(2, 2).value == 194.06
    assert ws.cell(2, 3).value == 194.06
    assert ws.cell(2, 4).value == 226.04
    assert ws.cell(2, 5).value == 184.43
    assert ws.cell(2, 4).number_format == "0.00"
    wb.close()


def test_query_excel_matches_screen_text(monkeypatch, tmp_path):
    from src.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.artifact_dir.mkdir(parents=True, exist_ok=True)
    path = write_query_xlsx(
        [{
            "pct": 1.2,
            "pct60": -3,
            "pct_ytd": 0,
            "turnover": 0.5,
            "off_low": 8.25,
            "vs_cost": -1.5,
            "dist_buy": 2,
            "dist_reduce": 4.5,
            "gross": 18.2,
            "pct3": 1.2,
            "concept": "所属概念板块,白酒、食品",
            "holders": "甲、乙",
        }],
        ["pct", "pct60", "pct_ytd", "turnover", "off_low", "vs_cost", "dist_buy", "dist_reduce", "gross", "pct3", "concept", "holders"],
        "自选",
    )
    wb = load_workbook(path, data_only=True)
    ws = wb.active
    got = [ws.cell(2, col).value for col in range(1, 13)]
    assert got == [
        "+1.20%",
        "-3.00%",
        "0.00%",
        "0.50%",
        "8.25%",
        "-1.50%",
        "2.00%",
        "4.50%",
        18.2,
        1.2,
        "白酒,食品",
        "甲、乙",
    ]
    wb.close()
