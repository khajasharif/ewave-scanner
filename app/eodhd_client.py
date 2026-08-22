"""
Thin wrapper around the EODHD endpoints this app needs:

- Exchange symbol list (one call, gets every US ticker)
- Bulk last-day EOD quotes (one call, gets today's OHLCV for the whole exchange)
- Per-ticker historical EOD (many calls, only used once during backfill)

Docs: https://eodhd.com/financial-apis/
"""
import asyncio
from datetime import date, timedelta
from typing import Optional

import httpx

from app.config import settings

BASE_URL = "https://eodhd.com/api"


def _token() -> str:
    if not settings.EODHD_API_KEY:
        raise RuntimeError("EODHD_API_KEY is not set")
    return settings.EODHD_API_KEY


async def fetch_us_symbol_list(client: httpx.AsyncClient) -> list[dict]:
    """Full list of tradable US common stocks."""
    url = f"{BASE_URL}/exchange-symbol-list/{settings.EODHD_EXCHANGE_CODE}"
    params = {"api_token": _token(), "fmt": "json"}
    resp = await client.get(url, params=params, timeout=60)
    resp.raise_for_status()
    rows = resp.json()
    return [
        r for r in rows
        if r.get("Type") == "Common Stock" and r.get("Code")
    ]


async def fetch_bulk_last_day(client: httpx.AsyncClient, day: Optional[date] = None) -> list[dict]:
    """One call: today's (or given day's) OHLCV for every ticker on the exchange."""
    url = f"{BASE_URL}/eod-bulk-last-day/{settings.EODHD_EXCHANGE_CODE}"
    params = {"api_token": _token(), "fmt": "json"}
    if day:
        params["date"] = day.isoformat()
    resp = await client.get(url, params=params, timeout=120)
    resp.raise_for_status()
    return resp.json()


async def fetch_history(client: httpx.AsyncClient, symbol: str, days: int) -> list[dict]:
    """Historical daily OHLCV for one ticker. Used only during backfill."""
    frm = (date.today() - timedelta(days=int(days * 1.6))).isoformat()  # pad for weekends/holidays
    url = f"{BASE_URL}/eod/{symbol}.{settings.EODHD_EXCHANGE_CODE}"
    params = {"api_token": _token(), "fmt": "json", "from": frm, "period": "d", "order": "a"}
    resp = await client.get(url, params=params, timeout=30)
    if resp.status_code != 200:
        return []
    data = resp.json()
    return data if isinstance(data, list) else []


async def fetch_history_bounded(client, symbol, days, semaphore) -> tuple[str, list[dict]]:
    async with semaphore:
        try:
            rows = await fetch_history(client, symbol, days)
        except Exception:
            rows = []
        return symbol, rows
