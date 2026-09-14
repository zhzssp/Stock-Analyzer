"""Tool registry. Importing this package registers the first-batch tools."""

from src.tools import excel_tools, market_tools, query_tools  # noqa: F401
from src.tools.registry import registry

__all__ = ["registry"]
