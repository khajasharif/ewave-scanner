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
    MA_VOLUME_SURGE_MULT: float = float(os.environ.get("MA_VOLUME_SURGE_MULT", "3.0"))
    # Minimum price move required over MA_PRICE_MOVE_LOOKBACK_BARS trading
    # days (e.g. 0.08 = 8%) for "the stock moves greatly".
    MA_MIN_PRICE_MOVE_PCT: float = float(os.environ.get("MA_MIN_PRICE_MOVE_PCT", "0.08"))
    MA_PRICE_MOVE_LOOKBACK_BARS: int = int(os.environ.get("MA_PRICE_MOVE_LOOKBACK_BARS", "10"))

    # --- MA Ribbon EARLY variant settings ---
    # The stacked SMA order must have formed within this many bars to count
    # as "just aligned" rather than old news.
    MA_MAX_ALIGNMENT_AGE_BARS: int = int(os.environ.get("MA_MAX_ALIGNMENT_AGE_BARS", "5"))

    # Price can be at most this far above SMA21 (as a fraction) and still
    # count as "near the breakout, not yet extended".
    MA_MAX_PRICE_ABOVE_SMA21_PCT: float = float(os.environ.get("MA_MAX_PRICE_ABOVE_SMA21_PCT", "0.06"))

    # A much smaller move than the confirmed variant's -- just enough to
    # capture "the second green candle" rather than a big cumulative move.
    MA_EARLY_MIN_RECENT_MOVE_PCT: float = float(os.environ.get("MA_EARLY_MIN_RECENT_MOVE_PCT", "0.02"))
    MA_EARLY_RECENT_MOVE_LOOKBACK_BARS: int = int(os.environ.get("MA_EARLY_RECENT_MOVE_LOOKBACK_BARS", "3"))

    # The Early tab uses its OWN (lower) volume bar than the Confirmed tab.
    # Volume typically builds up gradually AFTER a breakout starts, not
    # instantly on the first aligned bar -- requiring the same strict bar
    # as Confirmed would make Early nearly impossible to trigger, since a
    # stock rarely hits a big volume multiple at the exact moment the
    # ribbon just finished aligning.
    MA_EARLY_VOLUME_SURGE_MULT: float = float(os.environ.get("MA_EARLY_VOLUME_SURGE_MULT", "1.4"))

    # --- 44/200 Golden Cross Retest screener settings ---
    RETEST_SLOPE_LOOKBACK_BARS: int = int(os.environ.get("RETEST_SLOPE_LOOKBACK_BARS", "5"))
    # How far back to search for the 44/200 golden cross event itself.
    RETEST_CROSS_LOOKBACK_BARS: int = int(os.environ.get("RETEST_CROSS_LOOKBACK_BARS", "90"))
    # How close price must come to the SMA44/SMA200 zone to count as a
    # genuine "retest" (as a fraction, e.g. 0.02 = 2% buffer around the zone).
    RETEST_ZONE_BUFFER_PCT: float = float(os.environ.get("RETEST_ZONE_BUFFER_PCT", "0.02"))
    # The retest (and reversal confirmation) must be this recent to count.
    RETEST_MAX_AGE_BARS: int = int(os.environ.get("RETEST_MAX_AGE_BARS", "5"))

    # --- Bullish Chart Pattern (Double Bottom / Cup & Handle / Ascending
    # Triangle) screener settings ---
    CHART_ZIGZAG_PCT: float = float(os.environ.get("CHART_ZIGZAG_PCT", "0.06"))
    CHART_MIN_BARS: int = int(os.environ.get("CHART_MIN_BARS", "120"))
    CHART_MAX_BREAKOUT_AGE_BARS: int = int(os.environ.get("CHART_MAX_BREAKOUT_AGE_BARS", "5"))
    CHART_MIN_VOLUME_RATIO: float = float(os.environ.get("CHART_MIN_VOLUME_RATIO", "1.4"))
    DOUBLE_BOTTOM_TROUGH_TOLERANCE_PCT: float = float(os.environ.get("DOUBLE_BOTTOM_TROUGH_TOLERANCE_PCT", "0.04"))
    CUP_MIN_DEPTH_PCT: float = float(os.environ.get("CUP_MIN_DEPTH_PCT", "0.12"))
    CUP_MAX_DEPTH_PCT: float = float(os.environ.get("CUP_MAX_DEPTH_PCT", "0.55"))
    CUP_RIM_MATCH_TOLERANCE_PCT: float = float(os.environ.get("CUP_RIM_MATCH_TOLERANCE_PCT", "0.08"))
    HANDLE_MAX_DEPTH_RATIO: float = float(os.environ.get("HANDLE_MAX_DEPTH_RATIO", "0.5"))
    TRIANGLE_RESISTANCE_TOLERANCE_PCT: float = float(os.environ.get("TRIANGLE_RESISTANCE_TOLERANCE_PCT", "0.03"))

    # --- Bullish RSI Divergence + Volume Spike screener settings ---
    DIVERGENCE_ZIGZAG_PCT: float = float(os.environ.get("DIVERGENCE_ZIGZAG_PCT", "0.06"))
    DIVERGENCE_MIN_BARS: int = int(os.environ.get("DIVERGENCE_MIN_BARS", "60"))
    # How much lower/equal (as a fraction) the second price low is allowed
    # to be vs. the first and still count -- and how much HIGHER it can be
    # (small tolerance) before it's just a normal higher low, not a divergence.
    DIVERGENCE_PRICE_TOLERANCE_PCT: float = float(os.environ.get("DIVERGENCE_PRICE_TOLERANCE_PCT", "0.02"))
    # Minimum RSI-point gap between the two lows to count as a real divergence.
    DIVERGENCE_MIN_RSI_GAP: float = float(os.environ.get("DIVERGENCE_MIN_RSI_GAP", "5"))
    # The divergence low must be this recent (bars) for the setup to still be "fresh".
    DIVERGENCE_MAX_AGE_BARS: int = int(os.environ.get("DIVERGENCE_MAX_AGE_BARS", "10"))
    # A single day's volume must reach this multiple of the pre-divergence
    # baseline average somewhere in the window -- the "unusual activity" gate.
    DIVERGENCE_MIN_VOLUME_SPIKE_MULT: float = float(os.environ.get("DIVERGENCE_MIN_VOLUME_SPIKE_MULT", "3.0"))

    # Concurrency for outbound EODHD calls during backfill
    BACKFILL_CONCURRENCY: int = int(os.environ.get("BACKFILL_CONCURRENCY", "10"))


settings = Settings()
