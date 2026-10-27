from openpyxl import Workbook

from src.models import Artifact
from src.tools.base import ToolContext
from src.tools.excel_tools import excel_diff


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter_by(self, **_kwargs):
        return self

    def order_by(self, *_args):
        return self

    def all(self):
        return self.rows


class _DB:
    def __init__(self, rows):
        self.rows = rows

    def query(self, _model):
        return _Query(self.rows)


def _book(path, start: int, count: int, price: int) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "query"
    ws.append(["代码", "名称", "现价"])
    for i in range(start, start + count):
        code = f"{i:06d}"
        ws.append([code, f"股票{code}", price])
    wb.save(path)
    wb.close()


def test_diff_covers_every_row_past_the_old_caps(tmp_path):
    left = tmp_path / "older.xlsx"
    right = tmp_path / "newer.xlsx"
    _book(left, 1, 250, 1)
    _book(right, 201, 250, 2)
    arts = [
        Artifact(id=2, user_id=1, path=str(right), filename=right.name, pool_name="后"),
        Artifact(id=1, user_id=1, path=str(left), filename=left.name, pool_name="前"),
    ]
    result = excel_diff(
        {"id_a": 1, "id_b": 2, "column": "现价"},
        ToolContext(user_id=1, db=_DB(arts), market=None, engine=None),
    )
    data = result.data
    assert result.ok
    assert data["rows_a"] == 250
    assert data["rows_b"] == 250
    assert data["change_count"] == 450
    assert len(data["changes"]) == 450
    by_code = {item["code"]: item for item in data["changes"]}
    assert by_code["000001"]["before"] == 1
    assert by_code["000001"]["after"] is None
    assert by_code["000450"]["before"] is None
    assert by_code["000450"]["after"] == 2
    assert by_code["000201"]["before"] == 1
    assert by_code["000201"]["after"] == 2
