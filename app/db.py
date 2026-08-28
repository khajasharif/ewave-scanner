from datetime import date, datetime

from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime, JSON, UniqueConstraint,
    Boolean, create_engine, Index
)
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

# Render's managed Postgres gives a "postgres://" URL; SQLAlchemy needs the
# dialect+driver form. We use psycopg (v3) instead of psycopg2 because it
# ships prebuilt wheels for current Python versions (psycopg2-binary lags
# behind on new Python releases and fails with an ImportError on them).
db_url = settings.DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
elif db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)

connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
engine = create_engine(db_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class Ticker(Base):
    __tablename__ = "tickers"

    symbol = Column(String, primary_key=True)
    name = Column(String, default="")
    exchange = Column(String, default="")
    is_active = Column(Boolean, default=True)
    last_backfilled = Column(DateTime, nullable=True)


class PriceBar(Base):
    __tablename__ = "price_bars"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, index=True, nullable=False)
    bar_date = Column(Date, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)

    __table_args__ = (
        UniqueConstraint("symbol", "bar_date", name="uq_symbol_date"),
        Index("ix_symbol_date", "symbol", "bar_date"),
    )


class ScanResult(Base):
    __tablename__ = "scan_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, index=True, nullable=False)
    scan_date = Column(Date, index=True, nullable=False, default=date.today)
    stage = Column(String, index=True, nullable=False, default="established")  # "established" or "early"
    name = Column(String, default="")
    last_close = Column(Float)
    confidence = Column(Float)
    volume_ratio = Column(Float)
    wave1_pct = Column(Float)
    wave3_extension_pct = Column(Float)
    retrace_pct = Column(Float)
    bars_since_breakout = Column(Integer, nullable=True)
    pivots = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_date = Column(Date, index=True, nullable=False, default=date.today)
    tickers_scanned = Column(Integer, default=0)
    matches_found = Column(Integer, default=0)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String, default="running")
    error = Column(String, nullable=True)


class MaRibbonResult(Base):
    __tablename__ = "ma_ribbon_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, index=True, nullable=False)
    scan_date = Column(Date, index=True, nullable=False, default=date.today)
    stage = Column(String, index=True, nullable=False, default="confirmed")  # "confirmed" or "early"
    name = Column(String, default="")
    last_close = Column(Float)
    confidence = Column(Float)
    sma21 = Column(Float)
    sma44 = Column(Float)
    sma80 = Column(Float)
    sma200 = Column(Float)
    rsi = Column(Float)
    macd = Column(Float)
    volume_ratio = Column(Float)
    price_move_pct = Column(Float)
    alignment_age_bars = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class RetestResult(Base):
    __tablename__ = "retest_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, index=True, nullable=False)
    scan_date = Column(Date, index=True, nullable=False, default=date.today)
    name = Column(String, default="")
    last_close = Column(Float)
    confidence = Column(Float)
    sma44 = Column(Float)
    sma200 = Column(Float)
    cross_age_bars = Column(Integer, nullable=True)
    retest_age_bars = Column(Integer, nullable=True)
    patterns = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(engine)
    _migrate_add_missing_columns()


def _migrate_add_missing_columns():
    """create_all() only creates tables that don't exist yet -- it won't add
    new columns to a table that's already there. Since scan_results already
    existed on deployed databases before `stage` and `bars_since_breakout`
    were added, patch them in here (harmless no-op if they're already
    present). Each ALTER runs in its own transaction: if one fails because
    the column already exists, Postgres poisons the rest of that
    transaction, so they can't share one.
    """
    from sqlalchemy import text
    additions = [
        ("scan_results", "stage", "VARCHAR DEFAULT 'established'"),
        ("scan_results", "bars_since_breakout", "INTEGER"),
        ("ma_ribbon_results", "stage", "VARCHAR DEFAULT 'confirmed'"),
        ("ma_ribbon_results", "alignment_age_bars", "INTEGER"),
    ]
    for table, column, coltype in additions:
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))
        except Exception:
            pass  # column already exists (or dialect quirk) -- safe to ignore


def get_session():
    return SessionLocal()


def upsert_tickers(session, rows: list[dict], chunk_size: int = 1000) -> None:
    """Bulk insert-or-update Ticker rows (by symbol). Same reasoning as
    upsert_price_bars: doing one session.get()+add() round-trip per ticker
    is what was timing out the connection when syncing the full ~18,000
    ticker symbol list.
    """
    if not rows:
        return
    dialect = session.get_bind().dialect.name

    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            stmt = pg_insert(Ticker).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol"],
                set_={
                    "name": stmt.excluded.name,
                    "exchange": stmt.excluded.exchange,
                    "is_active": stmt.excluded.is_active,
                },
            )
            session.execute(stmt)
        elif dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert
            stmt = sqlite_insert(Ticker).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol"],
                set_={
                    "name": stmt.excluded.name,
                    "exchange": stmt.excluded.exchange,
                    "is_active": stmt.excluded.is_active,
                },
            )
            session.execute(stmt)
        else:
            for r in chunk:
                session.merge(Ticker(**r))


def upsert_price_bars(session, rows: list[dict], chunk_size: int = 1000) -> None:
    """Bulk insert PriceBar rows, silently skipping ones that already exist
    (same symbol + date). Writes in chunks of `chunk_size` rows per
    statement -- Postgres has a hard limit of ~65,535 bound parameters per
    query, and this table has 7 columns, so a single statement can safely
    hold up to ~9,000 rows; 1,000 leaves comfortable headroom. Without
    chunking, one bulk statement covering a large batch silently fails
    (exceeds the parameter limit) instead of raising something obvious.
    """
    if not rows:
        return
    dialect = session.get_bind().dialect.name

    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            stmt = pg_insert(PriceBar).values(chunk)
            stmt = stmt.on_conflict_do_nothing(index_elements=["symbol", "bar_date"])
            session.execute(stmt)
        elif dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert
            stmt = sqlite_insert(PriceBar).values(chunk)
            stmt = stmt.on_conflict_do_nothing(index_elements=["symbol", "bar_date"])
            session.execute(stmt)
        else:
            session.bulk_insert_mappings(PriceBar, chunk)
