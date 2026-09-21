from src.market.indices import codes_from_constituent_rows, constituent_paths, index_tree_code


def test_official_tree_codes():
    assert index_tree_code("000001.SH") == "zhishu_000001"
    assert constituent_paths("000001.SH") == ("/hszg/gg/zhishu_000001",)
    assert index_tree_code("399001.SZ") == "zhishu_399001"
    assert index_tree_code("000680.SH") is None
    assert constituent_paths("000680.SH") == ()


def test_codes_from_hszg_gg_rows():
    rows = [
        {"dm": "600519", "mc": "贵州茅台", "jys": "sh"},
        {"dm": "600519", "mc": "dup"},
        {"mc": "无代码"},
        {"dm": "000001", "jys": "sz"},
    ]
    assert codes_from_constituent_rows(rows) == ["600519", "000001"]
