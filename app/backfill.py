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
from datetime import datetime, date as date_cls, timezone

import httpx

from app.config import settings
from app.db import init_db, get_session, Ticker, PriceBar, upsert_price_bars, upsert_tickers
from app.eodhd_client import fetch_us_symbol_list, fetch_history_bounded


async def run(limit: int | None = None):
    init_db()
    async with httpx.AsyncClient() as client:
        print("Fetching US symbol list from EODHD...")
        symbols = await fetch_us_symbol_list(client)
        if limit:
            symbols = symbols[:limit]
        print(f"Got {len(symbols)} tickers.")

        ticker_rows = [
            {
                "symbol": r["Code"],
                "name": r.get("Name", ""),
                "exchange": r.get("Exchange", ""),
                "is_active": True,
            }
            for r in symbols
        ]
        session = get_session()
        upsert_tickers(session, ticker_rows)
        session.commit()
        session.close()
        print(f"Synced {len(ticker_rows)} ticker records.")

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

            # Build one big list of row dicts for the whole batch, then write
            # it in a single bulk statement -- avoids one DB round-trip per
            # row, which is what caused the remote connection to time out.
            all_rows = []
            touched_symbols = []
            for symbol, rows in results:
                if not rows:
                    continue
                touched_symbols.append(symbol)
                for r in rows:
                    try:
                        bar_date = datetime.strptime(r["date"], "%Y-%m-%d").date()
                    except Exception:
                        continue
                    all_rows.append({
                        "symbol": symbol,
                        "bar_date": bar_date,
                        "open": r.get("open"),
                        "high": r.get("high"),
                        "low": r.get("low"),
                        "close": r.get("adjusted_close") or r.get("close"),
                        "volume": r.get("volume") or 0,
                    })

            session = get_session()
            try:
                upsert_price_bars(session, all_rows)
                if touched_symbols:
                    now = datetime.now(timezone.utc)
                    (
                        session.query(Ticker)
                        .filter(Ticker.symbol.in_(touched_symbols))
                        .update({"last_backfilled": now}, synchronize_session=False)
                    )
                session.commit()
            except Exception as e:
                session.rollback()
                print(f"  Batch starting at {start} failed to write ({e}); skipping this batch.")
            finally:
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
