from datetime import date

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import init_db, get_session, ScanResult, ScanRun

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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/results")
def api_results():
    session = get_session()
    latest = _latest_scan_date(session)
    if not latest:
        session.close()
        return JSONResponse({"scan_date": None, "established": [], "early": []})

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
    last_run = session.query(ScanRun).order_by(ScanRun.started_at.desc()).first()
    session.close()
    return {
        "scan_date": latest.isoformat(),
        "tickers_scanned": last_run.tickers_scanned if last_run else None,
        "established": [_serialize(r) for r in established],
        "early": [_serialize(r) for r in early],
    }


@app.get("/")
def index(request: Request):
    session = get_session()
    latest = _latest_scan_date(session)
    established_results = []
    early_results = []
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
        last_run = session.query(ScanRun).order_by(ScanRun.started_at.desc()).first()
    session.close()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "scan_date": latest,
            "established_results": established_results,
            "early_results": early_results,
            "last_run": last_run,
        },
    )
