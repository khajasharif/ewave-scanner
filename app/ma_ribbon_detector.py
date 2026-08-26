"""
Moving-average "ribbon" breakout screeners. Two variants, sharing the same
core indicators:

  - detect_ma_ribbon(...): the CONFIRMED screener. Requires the stacked
    SMA21>SMA44>SMA80>SMA200 setup to already show a real price move (8%+
    over 10 bars by default). Higher conviction, later entry.

  - detect_ma_ribbon_early(...): catches the setup right as it FORMS --
    the stack must have become fully aligned only recently (within
    MA_MAX_ALIGNMENT_AGE_BARS), price must still be close to SMA21 (not
    already extended away from it), and only a small recent uptick is
    required rather than an already-large move. This is the "second green
    candle" moment: the ribbon just finished aligning and turning up.

Both require:
  - SMA21 > SMA44 > SMA80 > SMA200, all four sloping upward
  - RSI(14) in the 50-80 "healthy uptrend" band
  - MACD(12,26,9) line above zero
  - A pickup in recent volume vs. a longer baseline

SMA, RSI, and MACD are the standard textbook definitions (RSI uses
Wilder's smoothing; MACD line = EMA12 - EMA26). As with the wave
screeners: treat either shortlist as worth a manual chart check, not a
signal to trade on.
"""
from dataclasses import dataclass

from app.config import settings


@dataclass
class MaRibbonMatch:
    matched: bool
    confidence: float = 0.0
    sma21: float = 0.0
    sma44: float = 0.0
    sma80: float = 0.0
    sma200: float = 0.0
    rsi: float = 0.0
    macd: float = 0.0
    volume_ratio: float = 0.0
    price_move_pct: float = 0.0
    alignment_age_bars: int = 0
    reason: str = ""


def _prefix_sums(closes: list[float]) -> list[float]:
    """prefix[i] = sum(closes[0:i]). Lets any SMA(period, end_idx) be
    computed in O(1) instead of re-summing a window every time -- matters
    here since the "early" screener checks SMA values at many different
    end_idx points to find when the ribbon alignment formed.
    """
    prefix = [0.0] * (len(closes) + 1)
    for i, c in enumerate(closes):
        prefix[i + 1] = prefix[i] + c
    return prefix


def _sma(prefix: list[float], period: int, end_idx: int):
    start = end_idx - period + 1
    if start < 0:
        return None
    return (prefix[end_idx + 1] - prefix[start]) / period


def _ema_series(closes: list[float], period: int) -> list:
    n = len(closes)
    if n < period:
        return [None] * n
    k = 2 / (period + 1)
    ema = [None] * n
    ema[period - 1] = sum(closes[:period]) / period
    for i in range(period, n):
        ema[i] = closes[i] * k + ema[i - 1] * (1 - k)
    return ema


def _rsi(closes: list[float], period: int = 14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _macd(closes: list[float], fast: int = 12, slow: int = 26):
    ema_fast = _ema_series(closes, fast)
    ema_slow = _ema_series(closes, slow)
    idx = len(closes) - 1
    if idx < 0 or ema_fast[idx] is None or ema_slow[idx] is None:
        return None
    return ema_fast[idx] - ema_slow[idx]


def _stack_holds(prefix: list[float], idx: int) -> bool:
    s21, s44 = _sma(prefix, 21, idx), _sma(prefix, 44, idx)
    s80, s200 = _sma(prefix, 80, idx), _sma(prefix, 200, idx)
    if None in (s21, s44, s80, s200):
        return False
    return s21 > s44 > s80 > s200


def _alignment_age(prefix: list[float], last_idx: int, max_check: int) -> int:
    """How many bars back the stacked order has held continuously, ending
    today. 0 = the stack only became fully aligned as of today's bar (it
    wasn't aligned yesterday). Returns max_check if it's been aligned for
    at least that long (i.e. "old news" -- we stop looking further back).
    """
    age = -1
    idx = last_idx
    while idx >= 0 and (last_idx - idx) <= max_check and _stack_holds(prefix, idx):
        age += 1
        idx -= 1
    return age


def _shared_indicators(closes: list[float], volumes: list[float], slope_lookback: int, volume_surge_mult: float):
    """Computes everything both screeners need in common. Returns a dict on
    success, or a MaRibbonMatch(matched=False, ...) on the first failure.
    """
    prefix = _prefix_sums(closes)
    last = len(closes) - 1
    prev = last - slope_lookback

    sma21_now, sma44_now = _sma(prefix, 21, last), _sma(prefix, 44, last)
    sma80_now, sma200_now = _sma(prefix, 80, last), _sma(prefix, 200, last)
    sma21_prev, sma44_prev = _sma(prefix, 21, prev), _sma(prefix, 44, prev)
    sma80_prev, sma200_prev = _sma(prefix, 80, prev), _sma(prefix, 200, prev)

    if None in (sma21_now, sma44_now, sma80_now, sma200_now,
                sma21_prev, sma44_prev, sma80_prev, sma200_prev):
        return MaRibbonMatch(matched=False, reason="insufficient history for SMA slope check")

    if not (sma21_now > sma44_now > sma80_now > sma200_now):
        return MaRibbonMatch(
            matched=False,
            sma21=round(sma21_now, 2), sma44=round(sma44_now, 2),
            sma80=round(sma80_now, 2), sma200=round(sma200_now, 2),
            reason="SMAs not stacked 21>44>80>200",
        )

    if not (sma21_now > sma21_prev and sma44_now > sma44_prev
            and sma80_now > sma80_prev and sma200_now > sma200_prev):
        return MaRibbonMatch(matched=False, reason="not all four SMAs are rising yet")

    rsi = _rsi(closes)
    if rsi is None:
        return MaRibbonMatch(matched=False, reason="insufficient history for RSI")
    if not (50 <= rsi <= 80):
        return MaRibbonMatch(matched=False, rsi=round(rsi, 1), reason=f"RSI {rsi:.1f} outside the 50-80 band")

    macd = _macd(closes)
    if macd is None:
        return MaRibbonMatch(matched=False, reason="insufficient history for MACD")
    if macd <= 0:
        return MaRibbonMatch(matched=False, macd=round(macd, 4), reason="MACD not above zero")

    recent_vol = volumes[-5:]
    baseline_vol = volumes[-65:-5] if len(volumes) >= 65 else volumes[:-5]
    recent_avg = sum(recent_vol) / len(recent_vol) if recent_vol else 0
    baseline_avg = sum(baseline_vol) / len(baseline_vol) if baseline_vol else 0
    volume_ratio = (recent_avg / baseline_avg) if baseline_avg > 0 else 0
    if volume_ratio < volume_surge_mult:
        return MaRibbonMatch(
            matched=False, volume_ratio=round(volume_ratio, 2),
            reason=f"volume only {volume_ratio:.2f}x baseline, need >= {volume_surge_mult}x",
        )

    return {
        "prefix": prefix, "last": last,
        "sma21": sma21_now, "sma44": sma44_now, "sma80": sma80_now, "sma200": sma200_now,
        "rsi": rsi, "macd": macd, "volume_ratio": volume_ratio,
    }


def detect_ma_ribbon(
    dates: list[str],
    closes: list[float],
    volumes: list[float],
    slope_lookback: int = None,
    volume_surge_mult: float = None,
    min_price_move_pct: float = None,
    price_move_lookback: int = None,
) -> MaRibbonMatch:
    """CONFIRMED variant: requires an already-real price move."""
    slope_lookback = slope_lookback or settings.MA_SLOPE_LOOKBACK_BARS
    volume_surge_mult = volume_surge_mult or settings.MA_VOLUME_SURGE_MULT
    min_price_move_pct = min_price_move_pct if min_price_move_pct is not None else settings.MA_MIN_PRICE_MOVE_PCT
    price_move_lookback = price_move_lookback or settings.MA_PRICE_MOVE_LOOKBACK_BARS

    min_bars_needed = 200 + max(slope_lookback, price_move_lookback) + 5
    if len(closes) < min_bars_needed:
        return MaRibbonMatch(matched=False, reason="insufficient history for 200-SMA")

    shared = _shared_indicators(closes, volumes, slope_lookback, volume_surge_mult)
    if isinstance(shared, MaRibbonMatch):
        return shared

    last = shared["last"]
    if last - price_move_lookback < 0:
        return MaRibbonMatch(matched=False, reason="insufficient history for price-move check")
    price_then = closes[last - price_move_lookback]
    price_now = closes[last]
    price_move_pct = (price_now - price_then) / price_then if price_then > 0 else 0
    if price_move_pct < min_price_move_pct:
        return MaRibbonMatch(
            matched=False, price_move_pct=round(price_move_pct * 100, 2),
            reason=f"only {price_move_pct:.0%} move over {price_move_lookback} bars, need >= {min_price_move_pct:.0%}",
        )

    sma200_now = shared["sma200"]
    spread_score = min(((shared["sma21"] - sma200_now) / sma200_now) / 0.15, 1) if sma200_now > 0 else 0
    rsi_score = max(0.0, 1 - abs(shared["rsi"] - 65) / 30)
    volume_score = min((shared["volume_ratio"] - volume_surge_mult) / volume_surge_mult, 1)
    move_score = min(price_move_pct / (min_price_move_pct * 2), 1) if min_price_move_pct > 0 else 0
    confidence = round(100 * (0.25 * spread_score + 0.25 * rsi_score + 0.25 * volume_score + 0.25 * move_score), 1)
    confidence = max(0.0, min(100.0, confidence))

    return MaRibbonMatch(
        matched=True, confidence=confidence,
        sma21=round(shared["sma21"], 2), sma44=round(shared["sma44"], 2),
        sma80=round(shared["sma80"], 2), sma200=round(sma200_now, 2),
        rsi=round(shared["rsi"], 1), macd=round(shared["macd"], 4),
        volume_ratio=round(shared["volume_ratio"], 2),
        price_move_pct=round(price_move_pct * 100, 2),
        reason="bullish stacked/rising SMA ribbon with volume and momentum confirmation",
    )


def detect_ma_ribbon_early(
    dates: list[str],
    closes: list[float],
    volumes: list[float],
    slope_lookback: int = None,
    volume_surge_mult: float = None,
    max_alignment_age_bars: int = None,
    max_price_above_sma21_pct: float = None,
    min_recent_move_pct: float = None,
    recent_move_lookback_bars: int = None,
) -> MaRibbonMatch:
    """EARLY variant: catches the ribbon right as it finishes aligning --
    the "second green candle" moment, before a big move has happened yet.
    """
    slope_lookback = slope_lookback or settings.MA_SLOPE_LOOKBACK_BARS
    volume_surge_mult = volume_surge_mult or settings.MA_EARLY_VOLUME_SURGE_MULT
    max_alignment_age_bars = max_alignment_age_bars if max_alignment_age_bars is not None else settings.MA_MAX_ALIGNMENT_AGE_BARS
    max_price_above_sma21_pct = max_price_above_sma21_pct if max_price_above_sma21_pct is not None else settings.MA_MAX_PRICE_ABOVE_SMA21_PCT
    min_recent_move_pct = min_recent_move_pct if min_recent_move_pct is not None else settings.MA_EARLY_MIN_RECENT_MOVE_PCT
    recent_move_lookback_bars = recent_move_lookback_bars or settings.MA_EARLY_RECENT_MOVE_LOOKBACK_BARS

    min_bars_needed = 200 + slope_lookback + max_alignment_age_bars + 5
    if len(closes) < min_bars_needed:
        return MaRibbonMatch(matched=False, reason="insufficient history for 200-SMA")

    shared = _shared_indicators(closes, volumes, slope_lookback, volume_surge_mult)
    if isinstance(shared, MaRibbonMatch):
        return shared

    prefix, last = shared["prefix"], shared["last"]

    # The stack must have JUST formed -- not been aligned for a while
    # already. This is what separates "early" from "confirmed": both
    # require the same 21>44>80>200-and-rising snapshot, but early also
    # requires that snapshot to be recent.
    age = _alignment_age(prefix, last, max_check=max(max_alignment_age_bars * 3, 30))
    if age > max_alignment_age_bars:
        return MaRibbonMatch(
            matched=False, alignment_age_bars=age,
            reason=f"ribbon has been aligned for {age} bars already -- not a fresh formation",
        )

    # Price shouldn't have already run away from SMA21 -- keeps this to the
    # "still near the breakout, second green candle" zone rather than
    # something that's already extended well above its own 21-SMA.
    close_now = closes[last]
    price_above_sma21_pct = (close_now - shared["sma21"]) / shared["sma21"] if shared["sma21"] > 0 else 0
    if price_above_sma21_pct > max_price_above_sma21_pct:
        return MaRibbonMatch(
            matched=False, alignment_age_bars=age,
            reason=f"price already {price_above_sma21_pct:.0%} above SMA21 -- too extended for an early catch",
        )

    # A small but real recent uptick (the actual "green candle(s)"),
    # instead of requiring a large cumulative move.
    if last - recent_move_lookback_bars < 0:
        return MaRibbonMatch(matched=False, reason="insufficient history for recent-move check")
    price_then = closes[last - recent_move_lookback_bars]
    recent_move_pct = (close_now - price_then) / price_then if price_then > 0 else 0
    if recent_move_pct < min_recent_move_pct:
        return MaRibbonMatch(
            matched=False, alignment_age_bars=age, price_move_pct=round(recent_move_pct * 100, 2),
            reason=f"only {recent_move_pct:.0%} move over the last {recent_move_lookback_bars} bars",
        )

    # --- confidence: freshest alignment + closest to SMA21 + strongest
    # immediate move scores highest ---
    freshness_score = 1 - (age / max(max_alignment_age_bars, 1))
    proximity_score = max(0.0, 1 - (price_above_sma21_pct / max_price_above_sma21_pct)) if max_price_above_sma21_pct > 0 else 0
    rsi_score = max(0.0, 1 - abs(shared["rsi"] - 65) / 30)
    volume_score = min((shared["volume_ratio"] - volume_surge_mult) / volume_surge_mult, 1)
    confidence = round(100 * (0.30 * freshness_score + 0.25 * proximity_score + 0.20 * rsi_score + 0.25 * volume_score), 1)
    confidence = max(0.0, min(100.0, confidence))

    return MaRibbonMatch(
        matched=True, confidence=confidence,
        sma21=round(shared["sma21"], 2), sma44=round(shared["sma44"], 2),
        sma80=round(shared["sma80"], 2), sma200=round(shared["sma200"], 2),
        rsi=round(shared["rsi"], 1), macd=round(shared["macd"], 4),
        volume_ratio=round(shared["volume_ratio"], 2),
        price_move_pct=round(recent_move_pct * 100, 2),
        alignment_age_bars=age,
        reason="ribbon just finished aligning -- early catch",
    )
