"""
Recursively replace NaN / inf / -inf with None so FastAPI can JSON-serialize them.
Also provides shared input validators.
"""
import math
import re
from typing import Any

from fastapi import HTTPException

_SYMBOL_RE = re.compile(r'^[A-Z0-9.\-]{1,10}$')


def validate_symbol(symbol: str) -> str:
    """Uppercase and validate a ticker symbol. Raises 400 if invalid."""
    symbol = symbol.upper()
    if not _SYMBOL_RE.match(symbol):
        raise HTTPException(status_code=400, detail=f"Invalid ticker symbol: {symbol}")
    return symbol


def clean(obj: Any) -> Any:
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean(v) for v in obj]
    return obj
