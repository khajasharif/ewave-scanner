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

    # How far PAST the wave-1 breakout point a stock is allowed to have
    # already moved (as a fraction of wave 1's length) and still count as
    # "early" wave 3. Lower = catches stocks closer to the actual breakout
    # moment, but finds fewer of them; higher = catches more stocks but some
    # will already be well past the start.
    MAX_WAVE3_EXTENSION_PCT: float = float(os.environ.get("MAX_WAVE3_EXTENSION_PCT", "0.15"))

    # The breakout above the wave-1 high must have happened within this many
    # trading days of the most recent bar. Keeps the screener from flagging
    # a stock that broke out weeks ago and has just been drifting sideways
    # within the extension cap above.
    MAX_BREAKOUT_AGE_BARS: int = int(os.environ.get("MAX_BREAKOUT_AGE_BARS", "10"))

    # A single-day price move bigger than this (as a fraction, e.g. 0.5 =
    # 50%) within the pattern window is treated as an un-adjusted stock
    # split or bad data print, not real price action, and the match is
    # rejected. Real organic single-day moves this large are extremely
    # rare; reverse splits (2-for-1 and up) commonly produce exactly this
    # signature.
    MAX_SINGLE_DAY_MOVE_PCT: float = float(os.environ.get("MAX_SINGLE_DAY_MOVE_PCT", "0.5"))

    # --- MA Ribbon screener settings ---
    # How many bars back to compare each SMA against, to decide if it's
    # "rising" (SMA now vs. SMA this many bars ago).
    MA_SLOPE_LOOKBACK_BARS: int = int(os.environ.get("MA_SLOPE_LOOKBACK_BARS", "5"))

    # Recent (last 5 bars) avg volume must exceed this multiple of the
    # baseline (prior ~60 bars) average.
    MA_VOLUME_SURGE_MULT: float = float(os.environ.get("MA_VOLUME_SURGE_MULT", "1.3"))

    # Minimum price move required over MA_PRICE_MOVE_LOOKBACK_BARS trading
    # days (e.g. 0.08 = 8%) for "the stock moves greatly".
    MA_MIN_PRICE_MOVE_PCT: float = float(os.environ.get("MA_MIN_PRICE_MOVE_PCT", "0.08"))
    MA_PRICE_MOVE_LOOKBACK_BARS: int = int(os.environ.get("MA_PRICE_MOVE_LOOKBACK_BARS", "10"))

    # Concurrency for outbound EODHD calls during backfill
    BACKFILL_CONCURRENCY: int = int(os.environ.get("BACKFILL_CONCURRENCY", "10"))


settings = Settings()
