"""
Heuristic Elliott Wave "currently in wave 3 of an impulse, on volume" screener.

IMPORTANT — read this before trusting the output:
Elliott Wave counting is inherently subjective; there is no universally agreed
algorithm. This module implements one reasonable, rules-based approximation:

  1. Reduce the closing-price series to a zigzag of swing pivots (ZIGZAG_PCT
     threshold), which suppresses noise and leaves the "big" moves.
  2. Look at the last three pivots: P0 (swing low, impulse start) -> P1 (swing
     high, end of wave 1) -> P2 (swing low, end of wave 2).
  3. Apply the classic Elliott constraints:
       - Wave 1 is up (P1 > P0)
       - Wave 2 retraces between ~23.6% and ~88.6% of wave 1, and does NOT
         move below P0 (a wave 2 that breaks the wave-1 start invalidates the
         count)
       - Price is currently making new highs above P1 (i.e. already
         progressing into wave 3, not still stuck in wave 2)
       - The move off P2 already extends at least ~61.8% of wave 1's length
         (wave 3 is very often the longest/extended wave)
  4. Confirm "huge volume": average volume on the P2-to-now leg must exceed
     VOLUME_SURGE_MULT times the baseline average volume in the lookback
     window before P2 (wave 3 should show a visible volume expansion versus
     the quieter wave 1/2 formation).
  5. Score a 0-100 confidence from how cleanly those conditions are met.

This will produce false positives/negatives like any mechanical wave counter.
Treat the shortlist as "worth a manual look", not a trading signal.
"""
from dataclasses import dataclass, field
from typing import Optional

from app.config import settings


@dataclass
class Pivot:
    index: int
    date: str
    price: float
    kind: str  # "low" or "high"


@dataclass
class WaveMatch:
    matched: bool
    confidence: float = 0.0
    volume_ratio: float = 0.0
    wave1_pct: float = 0.0
    wave3_extension_pct: float = 0.0
    retrace_pct: float = 0.0
    pivots: list = field(default_factory=list)
    reason: str = ""


def zigzag(dates: list[str], closes: list[float], pct: float) -> list[Pivot]:
    """Simple percentage-threshold zigzag pivot detector.

    Tracks a running extreme (highest high while trending up, lowest low
    while trending down) and only confirms a pivot once price reverses by
    `pct` off that extreme -- not merely once it drifts `pct` from the last
    confirmed pivot, which was the earlier bug here (it kept re-firing a new
    pivot on almost every bar of a sustained trend).
    """
    if len(closes) < 3:
        return []

    pivots: list[Pivot] = []
    direction = 0  # 0 = trend not yet established, 1 = up, -1 = down
    anchor_price = closes[0]
    extreme_price = closes[0]
    extreme_idx = 0

    for i in range(1, len(closes)):
        price = closes[i]

        if direction == 0:
            if price >= anchor_price * (1 + pct):
                direction = 1
                extreme_price = price
                extreme_idx = i
            elif price <= anchor_price * (1 - pct):
                direction = -1
                extreme_price = price
                extreme_idx = i
            # else: still inside the noise band around the start, keep waiting

        elif direction == 1:
            if price > extreme_price:
                extreme_price = price
                extreme_idx = i
            elif price <= extreme_price * (1 - pct):
                pivots.append(Pivot(extreme_idx, dates[extreme_idx], extreme_price, "high"))
                direction = -1
                extreme_price = price
                extreme_idx = i

        elif direction == -1:
            if price < extreme_price:
                extreme_price = price
                extreme_idx = i
            elif price >= extreme_price * (1 + pct):
                pivots.append(Pivot(extreme_idx, dates[extreme_idx], extreme_price, "low"))
                direction = 1
                extreme_price = price
                extreme_idx = i

    return pivots


def detect_wave3(
    dates: list[str],
    closes: list[float],
    volumes: list[float],
    zigzag_pct: float = None,
    volume_surge_mult: float = None,
) -> WaveMatch:
    zigzag_pct = zigzag_pct or settings.ZIGZAG_PCT
    volume_surge_mult = volume_surge_mult or settings.VOLUME_SURGE_MULT

    if len(closes) < settings.MIN_BARS:
        return WaveMatch(matched=False, reason="insufficient history")

    pivots = zigzag(dates, closes, zigzag_pct)
    if len(pivots) < 2:
        return WaveMatch(matched=False, reason="no clear swings")

    # We need the pattern low(P0) -> high(P1) -> low(P2) as the *last two*
    # confirmed pivots, with price now progressing beyond P1.
    p2 = pivots[-1]
    p1 = pivots[-2]
    if p2.kind != "low" or p1.kind != "high":
        return WaveMatch(matched=False, reason="last swing isn't a wave-2 low")

    # P0 = the pivot (or series start) before P1
    if len(pivots) >= 3 and pivots[-3].kind == "low":
        p0 = pivots[-3]
    else:
        p0 = Pivot(0, dates[0], closes[0], "low")

    if not (p0.price < p1.price):
        return WaveMatch(matched=False, reason="wave 1 not upward")

    wave1_len = p1.price - p0.price
    if wave1_len <= 0:
        return WaveMatch(matched=False, reason="degenerate wave 1")

    # Wave 2 must not break below the wave-1 start
    if p2.price <= p0.price:
        return WaveMatch(matched=False, reason="wave 2 broke below wave 1 start (invalidated)")

    retrace_pct = (p1.price - p2.price) / wave1_len
    if not (0.20 <= retrace_pct <= 0.90):
        return WaveMatch(matched=False, reason=f"wave 2 retrace {retrace_pct:.0%} outside typical range")

    current_price = closes[-1]
    if current_price <= p1.price:
        return WaveMatch(matched=False, reason="price hasn't exceeded wave-1 high yet (still in wave 2)")

    wave3_progress = current_price - p2.price
    wave3_extension_pct = wave3_progress / wave1_len
    if wave3_extension_pct < 0.618:
        return WaveMatch(matched=False, reason="wave 3 move not yet extended enough")

    # --- Volume confirmation ---
    baseline_end = p2.index
    baseline_start = max(0, baseline_end - 60)
    baseline_vols = volumes[baseline_start:baseline_end] or volumes[:baseline_end + 1]
    baseline_avg = sum(baseline_vols) / len(baseline_vols) if baseline_vols else 0

    wave3_vols = volumes[p2.index:]
    wave3_avg = sum(wave3_vols) / len(wave3_vols) if wave3_vols else 0

    volume_ratio = (wave3_avg / baseline_avg) if baseline_avg > 0 else 0
    if volume_ratio < volume_surge_mult:
        return WaveMatch(
            matched=False,
            volume_ratio=round(volume_ratio, 2),
            reason=f"volume only {volume_ratio:.2f}x baseline, need >= {volume_surge_mult}x",
        )

    # --- Confidence score (0-100), rewards a "textbook" wave 3 setup ---
    retrace_score = 1 - min(abs(retrace_pct - 0.5) / 0.5, 1)          # ideal retrace ~50%
    extension_score = min(wave3_extension_pct / 1.618, 1)             # reward extension toward 1.618x
    volume_score = min((volume_ratio - volume_surge_mult) / volume_surge_mult, 1)
    confidence = round(100 * (0.35 * retrace_score + 0.35 * extension_score + 0.30 * volume_score), 1)
    confidence = max(0.0, min(100.0, confidence))

    return WaveMatch(
        matched=True,
        confidence=confidence,
        volume_ratio=round(volume_ratio, 2),
        wave1_pct=round(wave1_len / p0.price * 100, 2),
        wave3_extension_pct=round(wave3_extension_pct * 100, 2),
        retrace_pct=round(retrace_pct * 100, 2),
        pivots=[
            {"date": p0.date, "price": p0.price, "kind": "low", "label": "0"},
            {"date": p1.date, "price": p1.price, "kind": "high", "label": "1"},
            {"date": p2.date, "price": p2.price, "kind": "low", "label": "2"},
            {"date": dates[-1], "price": current_price, "kind": "current", "label": "3?"},
        ],
        reason="wave-3-in-progress with volume confirmation",
    )
