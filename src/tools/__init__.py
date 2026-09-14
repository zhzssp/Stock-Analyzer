"""Tool registry. Importing this package registers the first-batch tools."""

from src.tools import api_tools, excel_tools, market_tools, paste_tools, query_tools, warehouse_tools, watch_tools  # noqa: F401
from src.tools.loader import load_manifests
from src.tools.registry import registry

load_manifests()

__all__ = ["registry"]
