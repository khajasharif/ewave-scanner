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
    name = Column(String, default="")
    last_close = Column(Float)
    confidence = Column(Float)
    volume_ratio = Column(Float)
    wave1_pct = Column(Float)
    wave3_extension_pct = Column(Float)
    retrace_pct = Column(Float)
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


def init_db():
    Base.metadata.create_all(engine)


def get_session():
    return SessionLocal()


def upsert_price_bars(session, rows: list[dict]) -> None:
    """Bulk insert PriceBar rows, silently skipping ones that already exist
    (same symbol + date). One round-trip for the whole batch instead of a
    separate existence-check query per row -- doing per-row checks against a
    remote database is what was causing backfill to time out / drop
    connection partway through.
    """
    if not rows:
        return
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        stmt = pg_insert(PriceBar).values(rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["symbol", "bar_date"])
        session.execute(stmt)
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        stmt = sqlite_insert(PriceBar).values(rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["symbol", "bar_date"])
        session.execute(stmt)
    else:
        session.bulk_insert_mappings(PriceBar, rows)
