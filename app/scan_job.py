"""
Daily scan entrypoint, meant to be run by a Render Cron Job after US market
close:

    python -m app.scan_job

Steps:
  1. One bulk API call pulls today's OHLCV for every US ticker and appends it
     to price_bars.
  2. For every ticker with enough history, run the wave-3 + volume heuristic.
  3. Store today's matches in scan_results so the web app can show them
     instantly (no on-demand computation).
"""
import asyncio
from datetime import datetime, date as date_cls

import httpx

from app.config import settings
from app.db import init_db, get_session, Ticker, PriceBar, ScanResult, ScanRun, upsert_price_bars
from app.eodhd_client import fetch_bulk_last_day
from app.wave_detector import detect_wave3


async def update_today_bars(client: httpx.AsyncClient) -> int:
    rows = await fetch_bulk_last_day(client)
    session = get_session()

    all_rows = []
    for r in rows:
        code = r.get("code") or r.get("symbol") or r.get("Code")
        if not code:
            continue
        try:
            bar_date = datetime.strptime(r["date"], "%Y-%m-%d").date()
        except Exception:
            continue

        all_rows.append({
            "symbol": code,
            "bar_date": bar_date,
            "open": r.get("open"),
            "high": r.get("high"),
            "low": r.get("low"),
            "close": r.get("close") or r.get("adjusted_close"),
            "volume": r.get("volume") or 0,
        })

        t = session.get(Ticker, code)
        if not t:
            t = Ticker(symbol=code, name=r.get("name", ""), exchange=settings.EODHD_EXCHANGE_CODE)
            session.add(t)

    upsert_price_bars(session, all_rows)
    session.commit()
    session.close()
    return len(all_rows)


def scan_all(chunk_size: int = 300) -> tuple[int, int]:
    session = get_session()
    tickers = session.query(Ticker).filter_by(is_active=True).all()
    ticker_names = {t.symbol: t.name for t in tickers}
    symbols = list(ticker_names.keys())
    today = date_cls.today()

    # clear any prior result rows for today (in case job re-runs)
    session.query(ScanResult).filter_by(scan_date=today).delete()
    session.commit()

    scanned = 0
    matches = 0

    # Fetch price history in chunks of `chunk_size` symbols at a time (one
    # query per chunk covering many tickers at once) instead of one query
    # per ticker -- with ~18,000 tickers, one-query-per-ticker means 18,000
    # network round-trips to a remote database, which is what was making
    # this look "frozen."
    for start in range(0, len(symbols), chunk_size):
        chunk = symbols[start:start + chunk_size]
        bars = (
            session.query(PriceBar)
            .filter(PriceBar.symbol.in_(chunk))
            .order_by(PriceBar.symbol.asc(), PriceBar.bar_date.asc())
            .all()
        )
        grouped: dict[str, list] = {}
        for b in bars:
            grouped.setdefault(b.symbol, []).append(b)

        for symbol in chunk:
            sym_bars = grouped.get(symbol, [])
            if len(sym_bars) < settings.MIN_BARS:
                continue

            dates = [b.bar_date.isoformat() for b in sym_bars]
            closes = [b.close for b in sym_bars if b.close is not None]
            volumes = [b.volume or 0 for b in sym_bars]
            if len(closes) != len(sym_bars):
                continue

            scanned += 1
            last_close = closes[-1]
            last_volume = volumes[-1]
            dollar_volume = (last_close or 0) * (last_volume or 0)
            if dollar_volume < settings.MIN_DOLLAR_VOLUME:
                continue

            result = detect_wave3(dates, closes, volumes)
            if result.matched:
                matches += 1
                session.add(ScanResult(
                    symbol=symbol,
                    scan_date=today,
                    name=ticker_names.get(symbol, ""),
                    last_close=last_close,
                    confidence=result.confidence,
                    volume_ratio=result.volume_ratio,
                    wave1_pct=result.wave1_pct,
                    wave3_extension_pct=result.wave3_extension_pct,
                    retrace_pct=result.retrace_pct,
                    pivots=result.pivots,
                ))

        session.commit()
        print(f"  Scanned {min(start + chunk_size, len(symbols))}/{len(symbols)} tickers so far ({matches} matches)...")

    session.close()
    return scanned, matches


async def main():
    init_db()
    session = get_session()
    run = ScanRun(run_date=date_cls.today(), status="running")
    session.add(run)
    session.commit()
    run_id = run.id
    session.close()

    try:
        async with httpx.AsyncClient() as client:
            updated = await update_today_bars(client)
            print(f"Appended {updated} fresh daily bars.")

        scanned, matches = scan_all()
        print(f"Scanned {scanned} tickers, {matches} wave-3 matches found.")

        session = get_session()
        run = session.get(ScanRun, run_id)
        run.tickers_scanned = scanned
        run.matches_found = matches
        run.status = "done"
        run.finished_at = datetime.utcnow()
        session.commit()
        session.close()
    except Exception as e:
        session = get_session()
        run = session.get(ScanRun, run_id)
        run.status = "error"
        run.error = str(e)
        run.finished_at = datetime.utcnow()
        session.commit()
        session.close()
        raise


if __name__ == "__main__":
    asyncio.run(main())
