from datetime import date

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import init_db, get_session, ScanResult, ScanRun, MaRibbonResult, RetestResult

app = FastAPI(title="Wave 3 Screener")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
def on_startup():
    init_db()


def _latest_scan_date(session):
    row = session.query(ScanResult.scan_date).order_by(ScanResult.scan_date.desc()).first()
    return row[0] if row else None


def _serialize(r: ScanResult) -> dict:
    return {
        "symbol": r.symbol,
        "name": r.name,
        "last_close": r.last_close,
        "confidence": r.confidence,
        "volume_ratio": r.volume_ratio,
        "wave1_pct": r.wave1_pct,
        "wave3_extension_pct": r.wave3_extension_pct,
        "retrace_pct": r.retrace_pct,
        "bars_since_breakout": r.bars_since_breakout,
        "pivots": r.pivots,
    }


def _serialize_ma(r: MaRibbonResult) -> dict:
    return {
        "symbol": r.symbol,
        "name": r.name,
        "last_close": r.last_close,
        "confidence": r.confidence,
        "sma21": r.sma21, "sma44": r.sma44, "sma80": r.sma80, "sma200": r.sma200,
        "rsi": r.rsi, "macd": r.macd,
        "volume_ratio": r.volume_ratio,
        "price_move_pct": r.price_move_pct,
        "alignment_age_bars": r.alignment_age_bars,
    }


def _serialize_retest(r: RetestResult) -> dict:
    return {
        "symbol": r.symbol,
        "name": r.name,
        "last_close": r.last_close,
        "confidence": r.confidence,
        "sma44": r.sma44, "sma200": r.sma200,
        "cross_age_bars": r.cross_age_bars,
        "retest_age_bars": r.retest_age_bars,
        "patterns": r.patterns,
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/results")
def api_results():
    session = get_session()
    latest = _latest_scan_date(session)
    if not latest:
        session.close()
        return JSONResponse({"scan_date": None, "established": [], "early": [], "ma_ribbon": [], "ma_ribbon_early": [], "retest": []})

    established = (
        session.query(ScanResult)
        .filter_by(scan_date=latest, stage="established")
        .order_by(ScanResult.confidence.desc())
        .all()
    )
    early = (
        session.query(ScanResult)
        .filter_by(scan_date=latest, stage="early")
        .order_by(ScanResult.confidence.desc())
        .all()
    )
    ma_ribbon = (
        session.query(MaRibbonResult)
        .filter_by(scan_date=latest, stage="confirmed")
        .order_by(MaRibbonResult.confidence.desc())
        .all()
    )
    ma_ribbon_early = (
        session.query(MaRibbonResult)
        .filter_by(scan_date=latest, stage="early")
        .order_by(MaRibbonResult.confidence.desc())
        .all()
    )
    retest = (
        session.query(RetestResult)
        .filter_by(scan_date=latest)
        .order_by(RetestResult.confidence.desc())
        .all()
    )
    last_run = session.query(ScanRun).order_by(ScanRun.started_at.desc()).first()
    session.close()
    return {
        "scan_date": latest.isoformat(),
        "tickers_scanned": last_run.tickers_scanned if last_run else None,
        "established": [_serialize(r) for r in established],
        "early": [_serialize(r) for r in early],
        "ma_ribbon": [_serialize_ma(r) for r in ma_ribbon],
        "ma_ribbon_early": [_serialize_ma(r) for r in ma_ribbon_early],
        "retest": [_serialize_retest(r) for r in retest],
    }


@app.get("/")
def index(request: Request):
    session = get_session()
    latest = _latest_scan_date(session)
    established_results = []
    early_results = []
    ma_ribbon_results = []
    ma_ribbon_early_results = []
    retest_results = []
    last_run = None
    if latest:
        established_results = (
            session.query(ScanResult)
            .filter_by(scan_date=latest, stage="established")
            .order_by(ScanResult.confidence.desc())
            .all()
        )
        early_results = (
            session.query(ScanResult)
            .filter_by(scan_date=latest, stage="early")
            .order_by(ScanResult.confidence.desc())
            .all()
        )
        ma_ribbon_results = (
            session.query(MaRibbonResult)
            .filter_by(scan_date=latest, stage="confirmed")
            .order_by(MaRibbonResult.confidence.desc())
            .all()
        )
        ma_ribbon_early_results = (
            session.query(MaRibbonResult)
            .filter_by(scan_date=latest, stage="early")
            .order_by(MaRibbonResult.confidence.desc())
            .all()
        )
        retest_results = (
            session.query(RetestResult)
            .filter_by(scan_date=latest)
            .order_by(RetestResult.confidence.desc())
            .all()
        )
        last_run = session.query(ScanRun).order_by(ScanRun.started_at.desc()).first()
    session.close()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "scan_date": latest,
            "established_results": established_results,
            "early_results": early_results,
            "ma_ribbon_results": ma_ribbon_results,
            "ma_ribbon_early_results": ma_ribbon_early_results,
            "retest_results": retest_results,
            "last_run": last_run,
        },
    )
