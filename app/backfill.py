"""
One-time (or occasional) backfill: pulls the full US common-stock symbol list
and BACKFILL_DAYS of daily history for each ticker into the database.

Run manually after first deploy, and re-run occasionally (e.g. monthly) to
pick up new listings:

    python -m app.backfill

This is the expensive step API-call-wise (~1 call per ticker, ~8,000+ calls).
The daily cron job (scan_job.py) after this only needs ONE bulk API call per
day, so your ongoing EODHD usage stays low.
"""
import asyncio
import sys
from datetime import datetime, date as date_cls

import httpx

from app.config import settings
from app.db import init_db, get_session, Ticker, PriceBar
from app.eodhd_client import fetch_us_symbol_list, fetch_history_bounded


async def run(limit: int | None = None):
    init_db()
    async with httpx.AsyncClient() as client:
        print("Fetching US symbol list from EODHD...")
        symbols = await fetch_us_symbol_list(client)
        if limit:
            symbols = symbols[:limit]
        print(f"Got {len(symbols)} tickers.")

        session = get_session()
        for row in symbols:
            code = row["Code"]
            t = session.get(Ticker, code)
            if not t:
                t = Ticker(symbol=code)
                session.add(t)
            t.name = row.get("Name", "")
            t.exchange = row.get("Exchange", "")
            t.is_active = True
        session.commit()
        session.close()

        semaphore = asyncio.Semaphore(settings.BACKFILL_CONCURRENCY)
        codes = [r["Code"] for r in symbols]
        total = len(codes)
        done = 0
        batch_size = 200

        for start in range(0, total, batch_size):
            batch = codes[start:start + batch_size]
            tasks = [
                fetch_history_bounded(client, sym, settings.BACKFILL_DAYS, semaphore)
                for sym in batch
            ]
            results = await asyncio.gather(*tasks)

            session = get_session()
            for symbol, rows in results:
                for r in rows:
                    try:
                        bar_date = datetime.strptime(r["date"], "%Y-%m-%d").date()
                    except Exception:
                        continue
                    existing = (
                        session.query(PriceBar)
                        .filter_by(symbol=symbol, bar_date=bar_date)
                        .first()
                    )
                    if existing:
                        continue
                    session.add(PriceBar(
                        symbol=symbol,
                        bar_date=bar_date,
                        open=r.get("open"),
                        high=r.get("high"),
                        low=r.get("low"),
                        close=r.get("close") or r.get("adjusted_close"),
                        volume=r.get("volume") or 0,
                    ))
                t = session.get(Ticker, symbol)
                if t:
                    t.last_backfilled = datetime.utcnow()
            session.commit()
            session.close()

            done += len(batch)
            print(f"Backfilled {done}/{total} tickers...")

        print("Backfill complete.")


if __name__ == "__main__":
    limit_arg = None
    for arg in sys.argv[1:]:
        if arg.startswith("--limit="):
            limit_arg = int(arg.split("=", 1)[1])
    asyncio.run(run(limit=limit_arg))
