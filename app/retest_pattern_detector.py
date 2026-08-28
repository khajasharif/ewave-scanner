"""
44/200 SMA golden-cross retest screener.

Structural setup (all required):
  1. SMA44 crossed above SMA200 within the recent lookback window (a
     "golden cross" using 44/200 instead of the more common 50/200).
  2. Both SMA44 and SMA200 are currently sloping upward.
  3. Since the cross, price pulled back down into the zone between the two
     SMAs (a "retest" of the crossover support) -- not just drifted near it.
  4. On the retest bar (or shortly after), price reversed upward, confirmed
     by EITHER a recognized bullish candlestick pattern OR bullish RSI
     divergence (price makes a lower/equal low while RSI makes a higher low).

Candlestick pattern functions operate on plain OHLC values for the last few
bars. Each implements the standard textbook geometric definition. As with
every other screener here: mechanical pattern recognition, not proof of a
good trade. Verify manually before acting.
"""
from dataclasses import dataclass, field

from app.config import settings


@dataclass
class Candle:
    date: str
    open: float
    high: float
    low: float
    close: float

    @property
    def body_top(self):
        return max(self.open, self.close)

    @property
    def body_bottom(self):
        return min(self.open, self.close)

    @property
    def body(self):
        return abs(self.close - self.open)

    @property
    def range(self):
        return self.high - self.low

    @property
    def upper_wick(self):
        return self.high - self.body_top

    @property
    def lower_wick(self):
        return self.body_bottom - self.low

    @property
    def is_bullish(self):
        return self.close > self.open

    @property
    def is_bearish(self):
        return self.close < self.open


@dataclass
class RetestMatch:
    matched: bool
    confidence: float = 0.0
    patterns: list = field(default_factory=list)  # which pattern(s) fired
    sma44: float = 0.0
    sma200: float = 0.0
    cross_age_bars: int = 0
    retest_age_bars: int = 0
    reason: str = ""


# ---------------------------------------------------------------------------
# Shared indicator helpers (SMA via prefix sums, RSI)
# ---------------------------------------------------------------------------

def _prefix_sums(closes: list[float]) -> list[float]:
    prefix = [0.0] * (len(closes) + 1)
    for i, c in enumerate(closes):
        prefix[i + 1] = prefix[i] + c
    return prefix


def _sma(prefix: list[float], period: int, end_idx: int):
    start = end_idx - period + 1
    if start < 0:
        return None
    return (prefix[end_idx + 1] - prefix[start]) / period


def _rsi_series(closes: list[float], period: int = 14) -> list:
    """Full RSI series (same length as closes, leading entries None).
    Needed for divergence detection, which compares RSI at two different
    past points -- not just a single 'now' value.
    """
    n = len(closes)
    rsi = [None] * n
    if n < period + 1:
        return rsi

    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        change = closes[i] - closes[i - 1]
        gains[i] = max(change, 0.0)
        losses[i] = max(-change, 0.0)

    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period
    rsi[period] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))

    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsi[i] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))

    return rsi


# ---------------------------------------------------------------------------
# Candlestick pattern functions.
# Each takes the trailing candles it needs (candles[-1] = most recent) and
# returns True/False. Named per standard technical-analysis definitions.
# ---------------------------------------------------------------------------

def is_hammer(candles: list[Candle]) -> bool:
    """Small body near the top, lower wick >= 2x body, minimal upper wick.
    Bullish variant: close > open.
    """
    c = candles[-1]
    if c.range <= 0 or c.body <= 0:
        return False
    return (
        c.is_bullish
        and c.lower_wick >= 2 * c.body
        and c.upper_wick <= 0.25 * c.body
    )


def is_bullish_pin_bar(candles: list[Candle]) -> bool:
    """Same shape as a hammer but with a stricter (longer) lower wick
    requirement -- the more extreme "rejection" version.
    """
    c = candles[-1]
    if c.range <= 0 or c.body <= 0:
        return False
    return (
        c.is_bullish
        and c.lower_wick >= 2.5 * c.body
        and c.upper_wick <= 0.2 * c.range
    )


def is_bullish_engulfing(candles: list[Candle]) -> bool:
    """Candle1 bearish, Candle2 bullish, Candle2's body fully engulfs
    Candle1's body.
    """
    if len(candles) < 2:
        return False
    c1, c2 = candles[-2], candles[-1]
    return (
        c1.is_bearish and c2.is_bullish
        and c2.open <= c1.close and c2.close >= c1.open
        and c2.body > c1.body
    )


def is_morning_star(candles: list[Candle]) -> bool:
    """Candle1 large bearish, Candle2 small body (gaps down), Candle3
    bullish closing above the midpoint of Candle1's body.
    """
    if len(candles) < 3:
        return False
    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    if not c1.is_bearish or not c3.is_bullish:
        return False
    c1_mid = (c1.open + c1.close) / 2
    small_body = c2.body <= 0.5 * c1.body if c1.body > 0 else False
    gapped_down = c2.body_top <= c1.body_bottom * 1.01  # small tolerance
    closes_above_mid = c3.close > c1_mid
    return small_body and gapped_down and closes_above_mid


def is_bullish_harami(candles: list[Candle]) -> bool:
    """Candle1 large bearish, Candle2 smaller bullish candle whose body is
    fully contained within Candle1's body.
    """
    if len(candles) < 2:
        return False
    c1, c2 = candles[-2], candles[-1]
    return (
        c1.is_bearish and c2.is_bullish
        and c2.body_top <= c1.open and c2.body_bottom >= c1.close
        and c2.body < c1.body
    )


def is_bullish_piercing_line(candles: list[Candle]) -> bool:
    """Candle1 bearish, Candle2 bullish opening below Candle1's low but
    closing above the midpoint of Candle1's body (and below its open --
    otherwise it's a full engulfing, not a piercing line).
    """
    if len(candles) < 2:
        return False
    c1, c2 = candles[-2], candles[-1]
    if not c1.is_bearish or not c2.is_bullish:
        return False
    c1_mid = (c1.open + c1.close) / 2
    return c2.open < c1.low and c1_mid < c2.close < c1.open


def is_tweezer_bottom(candles: list[Candle]) -> bool:
    """Two candles with nearly identical lows, second candle bullish."""
    if len(candles) < 2:
        return False
    c1, c2 = candles[-2], candles[-1]
    if c1.low <= 0:
        return False
    lows_match = abs(c1.low - c2.low) / c1.low <= 0.003  # within 0.3%
    return lows_match and c2.is_bullish


def is_tri_star_bullish(candles: list[Candle], doji_threshold: float = 0.1) -> bool:
    """Three consecutive doji candles (very small bodies relative to range)."""
    if len(candles) < 3:
        return False
    for c in candles[-3:]:
        if c.range <= 0 or c.body > doji_threshold * c.range:
            return False
    return True


def is_inside_bar_breakout(candles: list[Candle]) -> bool:
    """Candle2 ('inside bar') fully contained within Candle1's range,
    Candle3 breaks out above Candle1's high (bullish confirmation).
    """
    if len(candles) < 3:
        return False
    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    inside = c2.high <= c1.high and c2.low >= c1.low
    breakout = c3.close > c1.high
    return inside and breakout


def is_bullish_shaven_head(candles: list[Candle]) -> bool:
    """Bullish candle closing at (or essentially at) its high -- no
    meaningful upper wick. Shows buyers were in control into the close.
    """
    c = candles[-1]
    if c.range <= 0:
        return False
    return c.is_bullish and c.upper_wick <= 0.05 * c.range


def is_homing_pigeon(candles: list[Candle]) -> bool:
    """Candle1 large bearish, Candle2 SMALLER bearish candle fully
    contained within Candle1's body (both red, but shrinking -- fading
    downward momentum). A bullish-reversal-context Harami variant where
    the second candle doesn't flip color.
    """
    if len(candles) < 2:
        return False
    c1, c2 = candles[-2], candles[-1]
    return (
        c1.is_bearish and c2.is_bearish
        and c2.body_top <= c1.open and c2.body_bottom >= c1.close
        and c2.body < c1.body
    )


def is_ladder_bottom(candles: list[Candle]) -> bool:
    """Three consecutive bearish candles with progressively lower closes,
    a fourth bearish candle with a long upper wick (buyers testing), then
    a fifth strong bullish candle confirming the reversal.
    """
    if len(candles) < 5:
        return False
    c1, c2, c3, c4, c5 = candles[-5], candles[-4], candles[-3], candles[-2], candles[-1]
    three_falling = (
        c1.is_bearish and c2.is_bearish and c3.is_bearish
        and c2.close < c1.close and c3.close < c2.close
    )
    fourth_upper_wick = c4.is_bearish and c4.range > 0 and c4.upper_wick >= c4.body
    fifth_confirms = c5.is_bullish and c5.close > c4.high
    return three_falling and fourth_upper_wick and fifth_confirms


def is_rising_three_methods(candles: list[Candle]) -> bool:
    """Candle1 strong bullish, Candles2-4 small bodies staying within
    Candle1's range (a contained pullback), Candle5 strong bullish
    breaking above Candle1's high.
    """
    if len(candles) < 5:
        return False
    c1, c2, c3, c4, c5 = candles[-5], candles[-4], candles[-3], candles[-2], candles[-1]
    if not c1.is_bullish or not c5.is_bullish:
        return False
    contained = all(c1.low <= c.low and c.high <= c1.high for c in (c2, c3, c4))
    small_bodies = all(c.body <= 0.6 * c1.body for c in (c2, c3, c4)) if c1.body > 0 else False
    breakout = c5.close > c1.high
    return contained and small_bodies and breakout


def is_bullish_mat_hold(candles: list[Candle]) -> bool:
    """Candle1 strong bullish, Candles2-4 small bearish/neutral candles
    that stay mostly within Candle1's range (allowing a slightly deeper
    dip than Rising Three Methods), Candle5 strong bullish breaking out.
    """
    if len(candles) < 5:
        return False
    c1, c2, c3, c4, c5 = candles[-5], candles[-4], candles[-3], candles[-2], candles[-1]
    if not c1.is_bullish or not c5.is_bullish:
        return False
    shallow_pullback = all(c.low >= c1.body_bottom * 0.98 for c in (c2, c3, c4))
    breakout = c5.close > c1.high
    return shallow_pullback and breakout


def check_all_patterns(candles: list[Candle]) -> list[str]:
    """Runs every pattern function against the trailing candles and returns
    the names of every pattern that fired (a bar can match more than one).
    """
    checks = [
        ("Hammer", is_hammer),
        ("Bullish Pin Bar", is_bullish_pin_bar),
        ("Bullish Engulfing", is_bullish_engulfing),
        ("Morning Star", is_morning_star),
        ("Bullish Harami", is_bullish_harami),
        ("Bullish Piercing Line", is_bullish_piercing_line),
        ("Tweezer Bottom", is_tweezer_bottom),
        ("Tri Star Bullish", is_tri_star_bullish),
        ("Inside Bar Breakout", is_inside_bar_breakout),
        ("Bullish Shaven Head", is_bullish_shaven_head),
        ("Homing Pigeon", is_homing_pigeon),
        ("Ladder Bottom", is_ladder_bottom),
        ("Rising Three Methods", is_rising_three_methods),
        ("Bullish Mat Hold", is_bullish_mat_hold),
    ]
    fired = []
    for name, fn in checks:
        try:
            if fn(candles):
                fired.append(name)
        except Exception:
            continue
    return fired


# ---------------------------------------------------------------------------
# Structural setup: 44/200 golden cross + retest into the crossover zone
# ---------------------------------------------------------------------------

def _find_cross_event(prefix: list[float], last_idx: int, lookback: int):
    """Finds the most recent bar where SMA44 crossed from <= SMA200 to
    > SMA200, searching back up to `lookback` bars from last_idx. Returns
    the bar index of the cross, or None if no cross happened in that
    window (or not enough history to check).
    """
    for i in range(last_idx, max(last_idx - lookback, 200), -1):
        sma44_i = _sma(prefix, 44, i)
        sma44_prev = _sma(prefix, 44, i - 1)
        sma200_i = _sma(prefix, 200, i)
        sma200_prev = _sma(prefix, 200, i - 1)
        if None in (sma44_i, sma44_prev, sma200_i, sma200_prev):
            continue
        crossed_today = sma44_prev <= sma200_prev and sma44_i > sma200_i
        if crossed_today:
            return i
    return None


def detect_ma_cross_retest(
    dates: list[str],
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    slope_lookback: int = None,
    cross_lookback_bars: int = None,
    retest_zone_buffer_pct: float = None,
    max_retest_age_bars: int = None,
    require_rsi_divergence_ok: bool = True,
) -> RetestMatch:
    """44/200 golden cross, both rising, price retests the zone between
    the two SMAs, then reverses -- confirmed by a candlestick pattern or
    bullish RSI divergence.
    """
    slope_lookback = slope_lookback or settings.RETEST_SLOPE_LOOKBACK_BARS
    cross_lookback_bars = cross_lookback_bars or settings.RETEST_CROSS_LOOKBACK_BARS
    retest_zone_buffer_pct = retest_zone_buffer_pct if retest_zone_buffer_pct is not None else settings.RETEST_ZONE_BUFFER_PCT
    max_retest_age_bars = max_retest_age_bars or settings.RETEST_MAX_AGE_BARS

    min_bars = 200 + cross_lookback_bars + 5
    if len(closes) < min_bars:
        return RetestMatch(matched=False, reason="insufficient history for 200-SMA + cross lookback")

    prefix = _prefix_sums(closes)
    last = len(closes) - 1

    sma44_now, sma200_now = _sma(prefix, 44, last), _sma(prefix, 200, last)
    sma44_prev, sma200_prev = _sma(prefix, 44, last - slope_lookback), _sma(prefix, 200, last - slope_lookback)
    if None in (sma44_now, sma200_now, sma44_prev, sma200_prev):
        return RetestMatch(matched=False, reason="insufficient history for slope check")

    if sma44_now <= sma200_now:
        return RetestMatch(matched=False, sma44=round(sma44_now, 2), sma200=round(sma200_now, 2),
                            reason="SMA44 is not currently above SMA200")

    if not (sma44_now > sma44_prev and sma200_now > sma200_prev):
        return RetestMatch(matched=False, reason="SMA44 and/or SMA200 are not both rising")

    cross_idx = _find_cross_event(prefix, last, cross_lookback_bars)
    if cross_idx is None:
        return RetestMatch(matched=False, reason=f"no 44/200 golden cross found in the last {cross_lookback_bars} bars")
    cross_age = last - cross_idx

    # Find the retest: the most recent bar (after the cross) whose LOW
    # dipped into the zone between the two SMAs (as they stood on that
    # bar), i.e. price came back down to test the crossover support.
    retest_idx = None
    for i in range(last, cross_idx, -1):
        s44_i = _sma(prefix, 44, i)
        s200_i = _sma(prefix, 200, i)
        if s44_i is None or s200_i is None:
            continue
        zone_low = s200_i * (1 - retest_zone_buffer_pct)
        zone_high = s44_i * (1 + retest_zone_buffer_pct)
        if lows[i] <= zone_high and lows[i] >= zone_low * 0.9:
            # dipped into (or very near) the zone between the SMAs
            retest_idx = i
            break

    if retest_idx is None:
        return RetestMatch(matched=False, cross_age_bars=cross_age,
                            reason="no retest of the crossover zone found since the cross")

    retest_age = last - retest_idx
    if retest_age > max_retest_age_bars:
        return RetestMatch(matched=False, cross_age_bars=cross_age, retest_age_bars=retest_age,
                            reason=f"retest happened {retest_age} bars ago -- too long ago for a fresh reversal")

    # Price should have reversed back up off the retest low by now.
    if closes[last] <= lows[retest_idx]:
        return RetestMatch(matched=False, cross_age_bars=cross_age, retest_age_bars=retest_age,
                            reason="no reversal above the retest low yet")

    # Build Candle objects for the confirmation window (from the retest
    # bar through today) to check candlestick patterns.
    window_start = max(0, retest_idx - 4)  # a little padding before the retest low, for multi-candle patterns
    candles = [
        Candle(dates[i], opens[i], highs[i], lows[i], closes[i])
        for i in range(window_start, last + 1)
    ]
    fired_patterns = check_all_patterns(candles)

    # Bullish RSI divergence: price makes a lower (or equal) low at the
    # retest vs. the prior swing low, while RSI makes a higher low.
    divergence = False
    if require_rsi_divergence_ok:
        rsi_series = _rsi_series(closes)
        prior_low_idx = None
        for i in range(retest_idx - 5, max(retest_idx - 60, 200), -1):
            if lows[i] <= lows[retest_idx] * 1.02 and i < retest_idx - 3:
                prior_low_idx = i
                break
        if prior_low_idx is not None and rsi_series[retest_idx] is not None and rsi_series[prior_low_idx] is not None:
            price_lower_or_equal = lows[retest_idx] <= lows[prior_low_idx] * 1.01
            rsi_higher = rsi_series[retest_idx] > rsi_series[prior_low_idx]
            divergence = price_lower_or_equal and rsi_higher

    if not fired_patterns and not divergence:
        return RetestMatch(matched=False, cross_age_bars=cross_age, retest_age_bars=retest_age,
                            reason="no confirming candlestick pattern or bullish divergence at the retest")

    if divergence:
        fired_patterns = fired_patterns + ["Bullish RSI Divergence"]

    # --- confidence: fresher retest + more confirming patterns + cleaner
    # slope scores higher ---
    freshness_score = 1 - (retest_age / max(max_retest_age_bars, 1))
    pattern_score = min(len(fired_patterns) / 2, 1)
    slope_pct = (sma44_now - sma44_prev) / sma44_prev if sma44_prev > 0 else 0
    slope_score = min(slope_pct / 0.03, 1)
    confidence = round(100 * (0.4 * freshness_score + 0.35 * pattern_score + 0.25 * slope_score), 1)
    confidence = max(0.0, min(100.0, confidence))

    return RetestMatch(
        matched=True,
        confidence=confidence,
        patterns=fired_patterns,
        sma44=round(sma44_now, 2),
        sma200=round(sma200_now, 2),
        cross_age_bars=cross_age,
        retest_age_bars=retest_age,
        reason="44/200 golden cross retest with bullish confirmation",
    )
