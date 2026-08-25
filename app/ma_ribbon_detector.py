"""
Moving-average "ribbon" breakout screener.

Looks for the specific stacked/rising SMA setup: SMA21 > SMA44 > SMA80 >
SMA200, with all four sloping upward together (the moment a longer base
resolves into a fanning-out uptrend), confirmed by:
  - RSI(14) sitting in the 50-80 "healthy uptrend" band (below 80 keeps out
    already-overbought names)
  - MACD(12,26,9) line above zero (short-term average above long-term,
    i.e. a bullish momentum regime)
  - A pickup in recent volume vs. a longer baseline
  - A meaningful recent price move (not just drifting)

SMA, RSI, and MACD here are the standard textbook definitions (RSI uses
Wilder's smoothing; MACD line = EMA12 - EMA26). As with the wave
screeners: treat this as a shortlist worth a manual chart check, not a
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
    reason: str = ""


def _sma(closes: list[float], period: int, end_idx: int):
    start = end_idx - period + 1
    if start < 0:
        return None
    window = closes[start:end_idx + 1]
    return sum(window) / period


def _ema_series(closes: list[float], period: int) -> list:
    """Full EMA series (same length as closes, leading entries None),
    seeded with a plain SMA of the first `period` values."""
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


def detect_ma_ribbon(
    dates: list[str],
    closes: list[float],
    volumes: list[float],
    slope_lookback: int = None,
    volume_surge_mult: float = None,
    min_price_move_pct: float = None,
    price_move_lookback: int = None,
) -> MaRibbonMatch:
    slope_lookback = slope_lookback or settings.MA_SLOPE_LOOKBACK_BARS
    volume_surge_mult = volume_surge_mult or settings.MA_VOLUME_SURGE_MULT
    min_price_move_pct = min_price_move_pct if min_price_move_pct is not None else settings.MA_MIN_PRICE_MOVE_PCT
    price_move_lookback = price_move_lookback or settings.MA_PRICE_MOVE_LOOKBACK_BARS

    min_bars_needed = 200 + slope_lookback + 5
    if len(closes) < min_bars_needed:
        return MaRibbonMatch(matched=False, reason="insufficient history for 200-SMA")

    last = len(closes) - 1
    prev = last - slope_lookback

    sma21_now, sma44_now = _sma(closes, 21, last), _sma(closes, 44, last)
    sma80_now, sma200_now = _sma(closes, 80, last), _sma(closes, 200, last)
    sma21_prev, sma44_prev = _sma(closes, 21, prev), _sma(closes, 44, prev)
    sma80_prev, sma200_prev = _sma(closes, 80, prev), _sma(closes, 200, prev)

    if None in (sma21_now, sma44_now, sma80_now, sma200_now,
                sma21_prev, sma44_prev, sma80_prev, sma200_prev):
        return MaRibbonMatch(matched=False, reason="insufficient history for SMA slope check")

    # 1. Stacked bullish alignment
    if not (sma21_now > sma44_now > sma80_now > sma200_now):
        return MaRibbonMatch(
            matched=False,
            sma21=round(sma21_now, 2), sma44=round(sma44_now, 2),
            sma80=round(sma80_now, 2), sma200=round(sma200_now, 2),
            reason="SMAs not stacked 21>44>80>200",
        )

    # 2. All four sloping upward
    if not (sma21_now > sma21_prev and sma44_now > sma44_prev
            and sma80_now > sma80_prev and sma200_now > sma200_prev):
        return MaRibbonMatch(matched=False, reason="not all four SMAs are rising yet")

    # 3. RSI in the 50-80 band
    rsi = _rsi(closes)
    if rsi is None:
        return MaRibbonMatch(matched=False, reason="insufficient history for RSI")
    if not (50 <= rsi <= 80):
        return MaRibbonMatch(matched=False, rsi=round(rsi, 1), reason=f"RSI {rsi:.1f} outside the 50-80 band")

    # 4. MACD above zero
    macd = _macd(closes)
    if macd is None:
        return MaRibbonMatch(matched=False, reason="insufficient history for MACD")
    if macd <= 0:
        return MaRibbonMatch(matched=False, macd=round(macd, 4), reason="MACD not above zero")

    # 5. Volume pickup: last 5 bars vs. the prior baseline
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

    # 6. Meaningful recent price move
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

    # --- confidence: reward a wide, healthy ribbon spread; mid-band RSI;
    # volume and price move comfortably past their minimums ---
    spread_score = min(((sma21_now - sma200_now) / sma200_now) / 0.15, 1) if sma200_now > 0 else 0
    rsi_score = max(0.0, 1 - abs(rsi - 65) / 30)
    volume_score = min((volume_ratio - volume_surge_mult) / volume_surge_mult, 1)
    move_score = min(price_move_pct / (min_price_move_pct * 2), 1) if min_price_move_pct > 0 else 0
    confidence = round(100 * (0.25 * spread_score + 0.25 * rsi_score + 0.25 * volume_score + 0.25 * move_score), 1)
    confidence = max(0.0, min(100.0, confidence))

    return MaRibbonMatch(
        matched=True,
        confidence=confidence,
        sma21=round(sma21_now, 2), sma44=round(sma44_now, 2),
        sma80=round(sma80_now, 2), sma200=round(sma200_now, 2),
        rsi=round(rsi, 1), macd=round(macd, 4),
        volume_ratio=round(volume_ratio, 2),
        price_move_pct=round(price_move_pct * 100, 2),
        reason="bullish stacked/rising SMA ribbon with volume and momentum confirmation",
    )
