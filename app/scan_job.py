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
import time
from datetime import datetime, date as date_cls, timezone

import httpx

from app.config import settings
from app.db import init_db, get_session, Ticker, PriceBar, ScanResult, ScanRun, upsert_price_bars, upsert_tickers, MaRibbonResult, RetestResult, ChartPatternResult
from app.eodhd_client import fetch_bulk_last_day
from app.wave_detector import detect_wave3_established, detect_wave3_early
from app.ma_ribbon_detector import detect_ma_ribbon, detect_ma_ribbon_early
from app.retest_pattern_detector import detect_ma_cross_retest
from app.chart_pattern_detector import check_all_chart_patterns


async def update_today_bars(client: httpx.AsyncClient) -> int:
    rows = await fetch_bulk_last_day(client)
    session = get_session()

    all_rows = []
    ticker_rows = []
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
            "close": r.get("adjusted_close") or r.get("close"),
            "volume": r.get("volume") or 0,
        })
        ticker_rows.append({
            "symbol": code,
            "name": r.get("name", ""),
            "exchange": settings.EODHD_EXCHANGE_CODE,
            "is_active": True,
        })

    # Bulk upsert, not one session.get() per ticker -- this is the exact
    # same per-row round-trip bug that was fixed in backfill.py, just
    # present here too. With ~18,000 tickers this alone was enough to make
    # the script sit silently for a very long time before ever reaching a
    # print() statement.
    upsert_tickers(session, ticker_rows)
    upsert_price_bars(session, all_rows)
    session.commit()
    session.close()
    return len(all_rows)


def _run_chunk(chunk: list[str], ticker_names: dict, today) -> tuple[int, int, int]:
    """Process one chunk of symbols in its own session. Returns
    (scanned, established_matches, early_matches) for this chunk only.
    Raises on failure so the caller can retry with a fresh connection.
    """
    session = get_session()
    try:
        bars = (
            session.query(PriceBar)
            .filter(PriceBar.symbol.in_(chunk))
            .order_by(PriceBar.symbol.asc(), PriceBar.bar_date.asc())
            .all()
        )
        grouped: dict[str, list] = {}
        for b in bars:
            grouped.setdefault(b.symbol, []).append(b)

        scanned = 0
        established_matches = 0
        early_matches = 0
        ma_ribbon_matches = 0
        ma_ribbon_early_matches = 0
        retest_matches = 0
        chart_matches = 0

        for symbol in chunk:
            sym_bars = grouped.get(symbol, [])
            if len(sym_bars) < settings.MIN_BARS:
                continue

            dates = [b.bar_date.isoformat() for b in sym_bars]
            opens = [b.open for b in sym_bars]
            highs = [b.high for b in sym_bars]
            lows = [b.low for b in sym_bars]
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

            # Run all THREE screeners on every ticker -- the two wave
            # screeners are mutually exclusive by construction (established
            # requires >=61.8% past the wave-2 low; early requires a fresh
            # breakout under the extension cap). The MA ribbon screener is
            # independent of both -- a stock could in principle appear on
            # that tab as well as one of the wave tabs.
            established = detect_wave3_established(dates, closes, volumes)
            if established.matched:
                established_matches += 1
                session.add(ScanResult(
                    symbol=symbol, scan_date=today, stage="established",
                    name=ticker_names.get(symbol, ""), last_close=last_close,
                    confidence=established.confidence, volume_ratio=established.volume_ratio,
                    wave1_pct=established.wave1_pct, wave3_extension_pct=established.wave3_extension_pct,
                    retrace_pct=established.retrace_pct, pivots=established.pivots,
                ))

            early = detect_wave3_early(dates, closes, volumes)
            if early.matched:
                early_matches += 1
                session.add(ScanResult(
                    symbol=symbol, scan_date=today, stage="early",
                    name=ticker_names.get(symbol, ""), last_close=last_close,
                    confidence=early.confidence, volume_ratio=early.volume_ratio,
                    wave1_pct=early.wave1_pct, wave3_extension_pct=early.wave3_extension_pct,
                    retrace_pct=early.retrace_pct, bars_since_breakout=early.bars_since_breakout,
                    pivots=early.pivots,
                ))

            ma_ribbon = detect_ma_ribbon(dates, closes, volumes)
            if ma_ribbon.matched:
                ma_ribbon_matches += 1
                session.add(MaRibbonResult(
                    symbol=symbol, scan_date=today, stage="confirmed",
                    name=ticker_names.get(symbol, ""), last_close=last_close,
                    confidence=ma_ribbon.confidence,
                    sma21=ma_ribbon.sma21, sma44=ma_ribbon.sma44,
                    sma80=ma_ribbon.sma80, sma200=ma_ribbon.sma200,
                    rsi=ma_ribbon.rsi, macd=ma_ribbon.macd,
                    volume_ratio=ma_ribbon.volume_ratio,
                    price_move_pct=ma_ribbon.price_move_pct,
                ))

            ma_ribbon_early = detect_ma_ribbon_early(dates, closes, volumes)
            if ma_ribbon_early.matched:
                ma_ribbon_early_matches += 1
                session.add(MaRibbonResult(
                    symbol=symbol, scan_date=today, stage="early",
                    name=ticker_names.get(symbol, ""), last_close=last_close,
                    confidence=ma_ribbon_early.confidence,
                    sma21=ma_ribbon_early.sma21, sma44=ma_ribbon_early.sma44,
                    sma80=ma_ribbon_early.sma80, sma200=ma_ribbon_early.sma200,
                    rsi=ma_ribbon_early.rsi, macd=ma_ribbon_early.macd,
                    volume_ratio=ma_ribbon_early.volume_ratio,
                    price_move_pct=ma_ribbon_early.price_move_pct,
                    alignment_age_bars=ma_ribbon_early.alignment_age_bars,
                ))

            retest = detect_ma_cross_retest(dates, opens, highs, lows, closes)
            if retest.matched:
                retest_matches += 1
                session.add(RetestResult(
                    symbol=symbol, scan_date=today,
                    name=ticker_names.get(symbol, ""), last_close=last_close,
                    confidence=retest.confidence,
                    sma44=retest.sma44, sma200=retest.sma200,
                    cross_age_bars=retest.cross_age_bars,
                    retest_age_bars=retest.retest_age_bars,
                    patterns=retest.patterns,
                ))

            for chart_match in check_all_chart_patterns(dates, closes, volumes):
                chart_matches += 1
                session.add(ChartPatternResult(
                    symbol=symbol, scan_date=today,
                    pattern_name=chart_match.pattern_name,
                    name=ticker_names.get(symbol, ""), last_close=last_close,
                    confidence=chart_match.confidence,
                    resistance_level=chart_match.resistance_level,
                    breakout_age_bars=chart_match.breakout_age_bars,
                    rsi=chart_match.rsi, volume_ratio=chart_match.volume_ratio,
                ))

        session.commit()
        return scanned, established_matches, early_matches, ma_ribbon_matches, ma_ribbon_early_matches, retest_matches, chart_matches
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def scan_all(chunk_size: int = 150, max_retries: int = 3) -> tuple[int, int, int, int, int, int, int]:
    # Short-lived session just to grab the ticker list and clear today's
    # old results -- not held open for the rest of the scan.
    session = get_session()
    tickers = session.query(Ticker).filter_by(is_active=True).all()
    ticker_names = {t.symbol: t.name for t in tickers}
    symbols = list(ticker_names.keys())
    today = date_cls.today()
    session.query(ScanResult).filter_by(scan_date=today).delete()
    session.query(MaRibbonResult).filter_by(scan_date=today).delete()
    session.query(RetestResult).filter_by(scan_date=today).delete()
    session.query(ChartPatternResult).filter_by(scan_date=today).delete()
    session.commit()
    session.close()

    scanned = 0
    established_matches = 0
    early_matches = 0
    ma_ribbon_matches = 0
    ma_ribbon_early_matches = 0
    retest_matches = 0
    chart_matches = 0

    # Each chunk gets its OWN fresh database session/connection (see
    # _run_chunk), and is retried with backoff if the connection drops.
    # Holding a single session open across the entire scan (which can take
    # many minutes over a home internet connection to a remote database) is
    # what was causing "server closed the connection unexpectedly" partway
    # through a run.
    for start in range(0, len(symbols), chunk_size):
        chunk = symbols[start:start + chunk_size]

        for attempt in range(1, max_retries + 1):
            try:
                c_scanned, c_established, c_early, c_ma, c_ma_early, c_retest, c_chart = _run_chunk(chunk, ticker_names, today)
                scanned += c_scanned
                established_matches += c_established
                early_matches += c_early
                ma_ribbon_matches += c_ma
                ma_ribbon_early_matches += c_ma_early
                retest_matches += c_retest
                chart_matches += c_chart
                break
            except Exception as e:
                if attempt == max_retries:
                    print(f"  Chunk at {start} failed after {max_retries} attempts ({e}); skipping this chunk.")
                else:
                    wait = 2 * attempt
                    print(f"  Chunk at {start} failed (attempt {attempt}/{max_retries}): {e} -- retrying in {wait}s...")
                    time.sleep(wait)

        total_matches = established_matches + early_matches + ma_ribbon_matches + ma_ribbon_early_matches + retest_matches + chart_matches
        print(f"  Scanned {min(start + chunk_size, len(symbols))}/{len(symbols)} tickers so far "
              f"({established_matches} established, {early_matches} early, {ma_ribbon_matches} ma-ribbon, "
              f"{ma_ribbon_early_matches} ma-ribbon-early, {retest_matches} retest, {chart_matches} chart, {total_matches} total)...")

    return scanned, established_matches, early_matches, ma_ribbon_matches, ma_ribbon_early_matches, retest_matches, chart_matches


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
            print("Fetching today's bulk price update from EODHD...")
            updated = await update_today_bars(client)
            print(f"Appended {updated} fresh daily bars.")

        print("Scanning tickers for wave-3, MA-ribbon, retest, and chart-pattern setups...")
        scanned, established_matches, early_matches, ma_ribbon_matches, ma_ribbon_early_matches, retest_matches, chart_matches = scan_all()
        total_matches = established_matches + early_matches + ma_ribbon_matches + ma_ribbon_early_matches + retest_matches + chart_matches
        print(f"Scanned {scanned} tickers -- {established_matches} established, {early_matches} early, "
              f"{ma_ribbon_matches} ma-ribbon, {ma_ribbon_early_matches} ma-ribbon-early, "
              f"{retest_matches} retest, {chart_matches} chart, {total_matches} total.")

        session = get_session()
        run = session.get(ScanRun, run_id)
        run.tickers_scanned = scanned
        run.matches_found = total_matches
        run.status = "done"
        run.finished_at = datetime.now(timezone.utc)
        session.commit()
        session.close()
    except Exception as e:
        session = get_session()
        run = session.get(ScanRun, run_id)
        run.status = "error"
        run.error = str(e)
        run.finished_at = datetime.now(timezone.utc)
        session.commit()
        session.close()
        raise


if __name__ == "__main__":
    asyncio.run(main())
