import os


class Settings:
    EODHD_API_KEY: str = os.environ.get("EODHD_API_KEY", "")
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///./local.db")

    # US "exchange code" EODHD uses for its combined symbol list / bulk endpoints
    EODHD_EXCHANGE_CODE: str = os.environ.get("EODHD_EXCHANGE_CODE", "US")

    # How many calendar days of history to keep per ticker (~1.5 years of trading days)
    BACKFILL_DAYS: int = int(os.environ.get("BACKFILL_DAYS", "420"))

    # Zigzag pivot threshold (fraction, e.g. 0.07 = 7% swing to register a pivot)
    ZIGZAG_PCT: float = float(os.environ.get("ZIGZAG_PCT", "0.07"))

    # Minimum bars of history required before a ticker is eligible for scanning
    MIN_BARS: int = int(os.environ.get("MIN_BARS", "120"))

    # Volume surge multiplier: avg volume during the wave-3 leg vs. the baseline
    # average volume in the prior lookback window. "Huge volume" = at/above this.
    VOLUME_SURGE_MULT: float = float(os.environ.get("VOLUME_SURGE_MULT", "1.5"))

    # Minimum dollar volume (price * volume, latest bar) to filter out illiquid/penny names
    MIN_DOLLAR_VOLUME: float = float(os.environ.get("MIN_DOLLAR_VOLUME", "5000000"))

    # Concurrency for outbound EODHD calls during backfill
    BACKFILL_CONCURRENCY: int = int(os.environ.get("BACKFILL_CONCURRENCY", "10"))


settings = Settings()
