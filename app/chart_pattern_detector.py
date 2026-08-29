"""
Bullish chart pattern entry screener: Double Bottom, Cup and Handle,
Ascending Triangle. These are multi-week/month STRUCTURAL patterns (built
from swing highs/lows and trendlines), distinct from the single-candle
patterns in retest_pattern_detector.py and the SMA-based setups in
ma_ribbon_detector.py.

Each detector looks for the pattern's shape AND a fresh, confirmed
breakout above its key resistance level (the "entry point"), with volume
and RSI/MACD momentum confirmation. As with every other screener here:
mechanical pattern recognition, not proof of a good trade -- multi-week
structural patterns are especially prone to being "obvious in hindsight,
ambiguous in real time." Verify manually before acting.
"""
from dataclasses import dataclass, field

from app.config import settings
from app.wave_detector import zigzag, Pivot
from app.retest_pattern_detector import _rsi_series, _prefix_sums, _sma


@dataclass
class ChartPatternMatch:
    matched: bool
    pattern_name: str = ""
    confidence: float = 0.0
    resistance_level: float = 0.0
    breakout_age_bars: int = 0
    rsi: float = 0.0
    volume_ratio: float = 0.0
    reason: str = ""


def _volume_ratio_recent(volumes: list[float], end_idx: int, recent_n: int = 5, baseline_n: int = 60) -> float:
    recent = volumes[max(0, end_idx - recent_n + 1):end_idx + 1]
    baseline_start = max(0, end_idx - recent_n - baseline_n + 1)
    baseline_end = end_idx - recent_n + 1
    baseline = volumes[baseline_start:baseline_end] or volumes[:baseline_end]
    r_avg = sum(recent) / len(recent) if recent else 0
    b_avg = sum(baseline) / len(baseline) if baseline else 0
    return (r_avg / b_avg) if b_avg > 0 else 0


def _macd_now(closes: list[float], fast: int = 12, slow: int = 26):
    def ema_series(period):
        n = len(closes)
        if n < period:
            return [None] * n
        k = 2 / (period + 1)
        ema = [None] * n
        ema[period - 1] = sum(closes[:period]) / period
        for i in range(period, n):
            ema[i] = closes[i] * k + ema[i - 1] * (1 - k)
        return ema

    ef, es = ema_series(fast), ema_series(slow)
    idx = len(closes) - 1
    if ef[idx] is None or es[idx] is None:
        return None
    return ef[idx] - es[idx]


def detect_double_bottom(
    dates: list[str],
    closes: list[float],
    volumes: list[float],
    zigzag_pct: float = None,
    trough_match_tolerance_pct: float = None,
    max_breakout_age_bars: int = None,
    min_volume_ratio: float = None,
) -> ChartPatternMatch:
    """Two troughs at a similar support level, separated by a peak (the
    "neckline"). Entry = a fresh, confirmed breakout above the neckline.
    """
    zigzag_pct = zigzag_pct or settings.CHART_ZIGZAG_PCT
    trough_match_tolerance_pct = trough_match_tolerance_pct if trough_match_tolerance_pct is not None else settings.DOUBLE_BOTTOM_TROUGH_TOLERANCE_PCT
    max_breakout_age_bars = max_breakout_age_bars or settings.CHART_MAX_BREAKOUT_AGE_BARS
    min_volume_ratio = min_volume_ratio if min_volume_ratio is not None else settings.CHART_MIN_VOLUME_RATIO

    if len(closes) < settings.CHART_MIN_BARS:
        return ChartPatternMatch(matched=False, pattern_name="Double Bottom", reason="insufficient history")

    pivots = zigzag(dates, closes, zigzag_pct)
    if len(pivots) < 3:
        return ChartPatternMatch(matched=False, pattern_name="Double Bottom", reason="not enough swings")

    # Need Low1 -> High(neckline) -> Low2 as the last three confirmed pivots.
    low2, neckline, low1 = pivots[-1], pivots[-2], pivots[-3]
    if low2.kind != "low" or neckline.kind != "high" or low1.kind != "low":
        return ChartPatternMatch(matched=False, pattern_name="Double Bottom", reason="last three swings aren't low-high-low")

    if low1.price <= 0:
        return ChartPatternMatch(matched=False, pattern_name="Double Bottom", reason="degenerate low")
    trough_diff_pct = abs(low2.price - low1.price) / low1.price
    if trough_diff_pct > trough_match_tolerance_pct:
        return ChartPatternMatch(
            matched=False, pattern_name="Double Bottom",
            reason=f"troughs {trough_diff_pct:.0%} apart, need within {trough_match_tolerance_pct:.0%}",
        )

    if neckline.price <= max(low1.price, low2.price):
        return ChartPatternMatch(matched=False, pattern_name="Double Bottom", reason="no real neckline peak between troughs")

    last = len(closes) - 1
    current_price = closes[last]
    if current_price <= neckline.price:
        return ChartPatternMatch(matched=False, pattern_name="Double Bottom", resistance_level=round(neckline.price, 2),
                                  reason="price hasn't broken the neckline yet")

    # Find when the breakout actually happened (first close above neckline after low2)
    breakout_idx = None
    for i in range(low2.index + 1, len(closes)):
        if closes[i] > neckline.price:
            breakout_idx = i
            break
    if breakout_idx is None:
        return ChartPatternMatch(matched=False, pattern_name="Double Bottom", reason="could not locate breakout bar")

    breakout_age = last - breakout_idx
    if breakout_age > max_breakout_age_bars:
        return ChartPatternMatch(matched=False, pattern_name="Double Bottom", breakout_age_bars=breakout_age,
                                  reason=f"breakout was {breakout_age} bars ago -- not a fresh entry")

    volume_ratio = _volume_ratio_recent(volumes, last)
    if volume_ratio < min_volume_ratio:
        return ChartPatternMatch(matched=False, pattern_name="Double Bottom", volume_ratio=round(volume_ratio, 2),
                                  reason=f"volume only {volume_ratio:.2f}x baseline")

    rsi_series = _rsi_series(closes)
    rsi = rsi_series[last]
    if rsi is None or rsi < 50:
        return ChartPatternMatch(matched=False, pattern_name="Double Bottom", reason="RSI below 50 -- momentum not confirmed")

    freshness_score = 1 - (breakout_age / max(max_breakout_age_bars, 1))
    match_score = 1 - (trough_diff_pct / max(trough_match_tolerance_pct, 0.001))
    volume_score = min((volume_ratio - min_volume_ratio) / max(min_volume_ratio, 0.1), 1)
    confidence = round(100 * (0.35 * freshness_score + 0.35 * match_score + 0.3 * volume_score), 1)
    confidence = max(0.0, min(100.0, confidence))

    return ChartPatternMatch(
        matched=True, pattern_name="Double Bottom", confidence=confidence,
        resistance_level=round(neckline.price, 2), breakout_age_bars=breakout_age,
        rsi=round(rsi, 1), volume_ratio=round(volume_ratio, 2),
        reason="double bottom neckline breakout confirmed",
    )


def detect_ascending_triangle(
    dates: list[str],
    closes: list[float],
    volumes: list[float],
    zigzag_pct: float = None,
    resistance_tolerance_pct: float = None,
    max_breakout_age_bars: int = None,
    min_volume_ratio: float = None,
) -> ChartPatternMatch:
    """Roughly equal highs (horizontal resistance) with progressively
    rising lows (ascending support). Entry = a fresh breakout above
    resistance.

    Only the FIRST resistance touch needs to be a confirmed pivot -- the
    second touch is exactly the breakout itself (price approaches
    resistance and breaks through in the same move, no pullback first),
    so it can't be required as a separately-confirmed pivot without
    demanding an extra pullback that a real triangle breakout doesn't have.
    """
    zigzag_pct = zigzag_pct or settings.CHART_ZIGZAG_PCT
    resistance_tolerance_pct = resistance_tolerance_pct if resistance_tolerance_pct is not None else settings.TRIANGLE_RESISTANCE_TOLERANCE_PCT
    max_breakout_age_bars = max_breakout_age_bars or settings.CHART_MAX_BREAKOUT_AGE_BARS
    min_volume_ratio = min_volume_ratio if min_volume_ratio is not None else settings.CHART_MIN_VOLUME_RATIO

    if len(closes) < settings.CHART_MIN_BARS:
        return ChartPatternMatch(matched=False, pattern_name="Ascending Triangle", reason="insufficient history")

    pivots = zigzag(dates, closes, zigzag_pct)
    if len(pivots) < 3:
        return ChartPatternMatch(matched=False, pattern_name="Ascending Triangle", reason="not enough swings")

    # Need Low1 -> High1(resistance) -> Low2(rising) as the last three
    # confirmed pivots -- we're currently past low2, in the leg that either
    # is or isn't breaking out above high1.
    low1, high1, low2 = pivots[-3], pivots[-2], pivots[-1]
    if low1.kind != "low" or high1.kind != "high" or low2.kind != "low":
        return ChartPatternMatch(matched=False, pattern_name="Ascending Triangle", reason="last three swings aren't low-high-low")

    if not (low2.price > low1.price):
        return ChartPatternMatch(matched=False, pattern_name="Ascending Triangle", reason="lows are not rising")

    resistance_level = high1.price
    last = len(closes) - 1
    current_price = closes[last]
    if current_price <= resistance_level:
        return ChartPatternMatch(matched=False, pattern_name="Ascending Triangle", resistance_level=round(resistance_level, 2),
                                  reason="price hasn't broken resistance yet")

    # The breakout is the first close after low2 that clears resistance --
    # this IS the "second touch," happening in the same move (a real
    # triangle breaks out directly off the second touch, no pullback first).
    breakout_idx = None
    for i in range(low2.index + 1, len(closes)):
        if closes[i] > resistance_level:
            breakout_idx = i
            break
    if breakout_idx is None:
        return ChartPatternMatch(matched=False, pattern_name="Ascending Triangle", reason="could not locate breakout bar")

    breakout_age = last - breakout_idx
    if breakout_age > max_breakout_age_bars:
        return ChartPatternMatch(matched=False, pattern_name="Ascending Triangle", breakout_age_bars=breakout_age,
                                  reason=f"breakout was {breakout_age} bars ago -- not a fresh entry")

    volume_ratio = _volume_ratio_recent(volumes, last)
    if volume_ratio < min_volume_ratio:
        return ChartPatternMatch(matched=False, pattern_name="Ascending Triangle", volume_ratio=round(volume_ratio, 2),
                                  reason=f"volume only {volume_ratio:.2f}x baseline")

    rsi_series = _rsi_series(closes)
    rsi = rsi_series[last]
    if rsi is None or rsi < 50:
        return ChartPatternMatch(matched=False, pattern_name="Ascending Triangle", reason="RSI below 50 -- momentum not confirmed")

    freshness_score = 1 - (breakout_age / max(max_breakout_age_bars, 1))
    volume_score = min((volume_ratio - min_volume_ratio) / max(min_volume_ratio, 0.1), 1)
    confidence = round(100 * (0.4 * freshness_score + 0.6 * volume_score), 1)
    confidence = max(0.0, min(100.0, confidence))

    return ChartPatternMatch(
        matched=True, pattern_name="Ascending Triangle", confidence=confidence,
        resistance_level=round(resistance_level, 2), breakout_age_bars=breakout_age,
        rsi=round(rsi, 1), volume_ratio=round(volume_ratio, 2),
        reason="ascending triangle resistance breakout confirmed",
    )


def detect_cup_and_handle(
    dates: list[str],
    closes: list[float],
    volumes: list[float],
    min_cup_depth_pct: float = None,
    max_cup_depth_pct: float = None,
    rim_match_tolerance_pct: float = None,
    handle_max_depth_ratio: float = None,
    max_breakout_age_bars: int = None,
    min_volume_ratio: float = None,
    lookback_bars: int = 150,
) -> ChartPatternMatch:
    """Rounded cup (retracing ~12-55% of the run into the left lip),
    recovery to a similar level (right lip), a SHALLOW handle pullback,
    then a breakout above the rim. Uses depth ratios on the close series
    directly rather than requiring sharp zigzag pivots, since a cup is
    fundamentally a smooth/rounded shape, not a sharp reversal.
    """
    min_cup_depth_pct = min_cup_depth_pct if min_cup_depth_pct is not None else settings.CUP_MIN_DEPTH_PCT
    max_cup_depth_pct = max_cup_depth_pct if max_cup_depth_pct is not None else settings.CUP_MAX_DEPTH_PCT
    rim_match_tolerance_pct = rim_match_tolerance_pct if rim_match_tolerance_pct is not None else settings.CUP_RIM_MATCH_TOLERANCE_PCT
    handle_max_depth_ratio = handle_max_depth_ratio if handle_max_depth_ratio is not None else settings.HANDLE_MAX_DEPTH_RATIO
    max_breakout_age_bars = max_breakout_age_bars or settings.CHART_MAX_BREAKOUT_AGE_BARS
    min_volume_ratio = min_volume_ratio if min_volume_ratio is not None else settings.CHART_MIN_VOLUME_RATIO

    if len(closes) < settings.CHART_MIN_BARS:
        return ChartPatternMatch(matched=False, pattern_name="Cup and Handle", reason="insufficient history")

    last = len(closes) - 1
    window_start = max(0, last - lookback_bars)
    window = closes[window_start:last + 1]

    # Left lip: the highest point in the first half of the window (before
    # the cup bottom forms).
    first_half_end = window_start + len(window) // 2
    if first_half_end <= window_start:
        return ChartPatternMatch(matched=False, pattern_name="Cup and Handle", reason="window too short")
    left_lip_idx = max(range(window_start, first_half_end), key=lambda i: closes[i])
    left_lip_price = closes[left_lip_idx]

    # Cup bottom: the lowest close after the left lip.
    if left_lip_idx >= last:
        return ChartPatternMatch(matched=False, pattern_name="Cup and Handle", reason="left lip too close to the end")
    bottom_idx = min(range(left_lip_idx, last + 1), key=lambda i: closes[i])
    bottom_price = closes[bottom_idx]

    if left_lip_price <= 0:
        return ChartPatternMatch(matched=False, pattern_name="Cup and Handle", reason="degenerate left lip")
    cup_depth_pct = (left_lip_price - bottom_price) / left_lip_price
    if not (min_cup_depth_pct <= cup_depth_pct <= max_cup_depth_pct):
        return ChartPatternMatch(
            matched=False, pattern_name="Cup and Handle",
            reason=f"cup depth {cup_depth_pct:.0%} outside the {min_cup_depth_pct:.0%}-{max_cup_depth_pct:.0%} range",
        )

    # Right lip: the FIRST point after the bottom where price recovers back
    # near the left lip's level -- NOT the global max of everything after
    # the bottom, which would wrongly swallow the handle and breakout into
    # an ever-later "right lip" once price makes a new high.
    if bottom_idx >= last:
        return ChartPatternMatch(matched=False, pattern_name="Cup and Handle", reason="cup bottom too close to the end")
    right_lip_idx = None
    for i in range(bottom_idx, last + 1):
        if closes[i] >= left_lip_price * (1 - rim_match_tolerance_pct):
            right_lip_idx = i
            break
    if right_lip_idx is None:
        return ChartPatternMatch(matched=False, pattern_name="Cup and Handle", reason="price hasn't recovered back near the left lip yet")
    right_lip_price = closes[right_lip_idx]
    rim_level = max(left_lip_price, right_lip_price)

    # Handle: after the right lip, a SHALLOW pullback (much shallower than
    # the cup itself), then a breakout above the rim.
    if right_lip_idx >= last:
        return ChartPatternMatch(matched=False, pattern_name="Cup and Handle", reason="right lip is the most recent bar -- no handle yet")
    handle_low_idx = min(range(right_lip_idx, last + 1), key=lambda i: closes[i])
    handle_low_price = closes[handle_low_idx]
    handle_depth_pct = (right_lip_price - handle_low_price) / right_lip_price if right_lip_price > 0 else 1
    cup_depth_abs = cup_depth_pct
    if cup_depth_abs > 0 and handle_depth_pct > handle_max_depth_ratio * cup_depth_abs:
        return ChartPatternMatch(
            matched=False, pattern_name="Cup and Handle",
            reason=f"handle pullback ({handle_depth_pct:.0%}) too deep relative to the cup ({cup_depth_abs:.0%})",
        )

    current_price = closes[last]
    if current_price <= rim_level:
        return ChartPatternMatch(matched=False, pattern_name="Cup and Handle", resistance_level=round(rim_level, 2),
                                  reason="price hasn't broken the rim yet")

    breakout_idx = None
    for i in range(handle_low_idx, len(closes)):
        if closes[i] > rim_level:
            breakout_idx = i
            break
    if breakout_idx is None:
        return ChartPatternMatch(matched=False, pattern_name="Cup and Handle", reason="could not locate breakout bar")

    breakout_age = last - breakout_idx
    if breakout_age > max_breakout_age_bars:
        return ChartPatternMatch(matched=False, pattern_name="Cup and Handle", breakout_age_bars=breakout_age,
                                  reason=f"breakout was {breakout_age} bars ago -- not a fresh entry")

    volume_ratio = _volume_ratio_recent(volumes, last)
    if volume_ratio < min_volume_ratio:
        return ChartPatternMatch(matched=False, pattern_name="Cup and Handle", volume_ratio=round(volume_ratio, 2),
                                  reason=f"volume only {volume_ratio:.2f}x baseline")

    rsi_series = _rsi_series(closes)
    rsi = rsi_series[last]
    if rsi is None or rsi < 50:
        return ChartPatternMatch(matched=False, pattern_name="Cup and Handle", reason="RSI below 50 -- momentum not confirmed")

    freshness_score = 1 - (breakout_age / max(max_breakout_age_bars, 1))
    depth_score = 1 - abs(cup_depth_pct - 0.30) / 0.30  # reward depths near the "textbook" ~1/3 retrace
    depth_score = max(0.0, min(1.0, depth_score))
    volume_score = min((volume_ratio - min_volume_ratio) / max(min_volume_ratio, 0.1), 1)
    confidence = round(100 * (0.4 * freshness_score + 0.3 * depth_score + 0.3 * volume_score), 1)
    confidence = max(0.0, min(100.0, confidence))

    return ChartPatternMatch(
        matched=True, pattern_name="Cup and Handle", confidence=confidence,
        resistance_level=round(rim_level, 2), breakout_age_bars=breakout_age,
        rsi=round(rsi, 1), volume_ratio=round(volume_ratio, 2),
        reason=f"cup and handle rim breakout confirmed (cup depth {cup_depth_pct:.0%})",
    )


def check_all_chart_patterns(dates: list[str], closes: list[float], volumes: list[float]) -> list[ChartPatternMatch]:
    """Runs all three chart-pattern detectors and returns every one that
    matched (a stock could in principle match more than one at once,
    though it's uncommon given how differently the setups look).
    """
    detectors = [detect_double_bottom, detect_ascending_triangle, detect_cup_and_handle]
    results = []
    for fn in detectors:
        try:
            r = fn(dates, closes, volumes)
            if r.matched:
                results.append(r)
        except Exception:
            continue
    return results
