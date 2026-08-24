"""
Heuristic Elliott Wave screeners. Two variants are provided, both built on
the same pivot-finding logic:

  - detect_wave3_established(...): the ORIGINAL screener. Requires the move
    off the wave-2 low to already be extended at least ~61.8% of wave 1's
    length. Finds stocks with a well-developed, high-conviction wave 3
    already underway.

  - detect_wave3_early(...): a NEW screener for catching wave 3 near its
    start. Requires price to have JUST broken above the wave-1 high (within
    MAX_BREAKOUT_AGE_BARS trading days) and to still be under
    MAX_WAVE3_EXTENSION_PCT of wave 1's length past the wave-2 low. Finds
    stocks earlier, with less confirmation.

IMPORTANT — read this before trusting either output:
Elliott Wave counting is inherently subjective; there is no universally agreed
algorithm. Both screeners share these base rules:

  1. Reduce the closing-price series to a zigzag of swing pivots (ZIGZAG_PCT
     threshold), which suppresses noise and leaves the "big" moves.
  2. Look at the last three pivots: P0 (swing low, impulse start) -> P1 (swing
     high, end of wave 1) -> P2 (swing low, end of wave 2).
  3. Wave 1 must be up (P1 > P0). Wave 2 must retrace between ~20% and ~90%
     of wave 1, and must NOT move below P0 (that would invalidate the count).
  4. Confirm "huge volume": average volume on the P2-to-now leg must exceed
     VOLUME_SURGE_MULT times the baseline average volume in the lookback
     window before P2.
  5. Score a 0-100 confidence from how cleanly the conditions are met.

This will produce false positives/negatives like any mechanical wave counter.
Treat either shortlist as "worth a manual look", not a trading signal.
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
    bars_since_breakout: int = 0
    pivots: list = field(default_factory=list)
    reason: str = ""


def zigzag(dates: list[str], closes: list[float], pct: float) -> list[Pivot]:
    """Simple percentage-threshold zigzag pivot detector.

    Tracks a running extreme (highest high while trending up, lowest low
    while trending down) and only confirms a pivot once price reverses by
    `pct` off that extreme.
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


class _NoMatch(Exception):
    def __init__(self, match: WaveMatch):
        self.match = match


def _has_implausible_single_day_move(closes: list[float], start_idx: int, max_pct: float) -> bool:
    """Detect a probable un-adjusted stock split (or bad print) within the
    window: a genuine single-day organic move of e.g. 200%+ is extremely
    rare, but is exactly what an un-adjusted reverse split looks like
    (common ratios: 2-for-1 up to 10-for-1+, i.e. 50-90%+ single-day
    "moves"). This check doesn't depend on whether the data vendor's
    adjusted-price field has caught up to a recent split -- it catches the
    artifact directly in whatever series we were given.
    """
    for i in range(start_idx + 1, len(closes)):
        prev, cur = closes[i - 1], closes[i]
        if prev <= 0:
            continue
        pct_move = abs(cur - prev) / prev
        if pct_move > max_pct:
            return True
    return False


def _find_wave12(dates, closes, volumes, zigzag_pct):
    """Shared setup: find pivots P0/P1/P2, validate waves 1 and 2. Returns
    (p0, p1, p2, wave1_len, retrace_pct, current_price) or raises _NoMatch.
    """
    if len(closes) < settings.MIN_BARS:
        raise _NoMatch(WaveMatch(matched=False, reason="insufficient history"))

    pivots = zigzag(dates, closes, zigzag_pct)
    if len(pivots) < 2:
        raise _NoMatch(WaveMatch(matched=False, reason="no clear swings"))

    p2 = pivots[-1]
    p1 = pivots[-2]
    if p2.kind != "low" or p1.kind != "high":
        raise _NoMatch(WaveMatch(matched=False, reason="last swing isn't a wave-2 low"))

    if len(pivots) >= 3 and pivots[-3].kind == "low":
        p0 = pivots[-3]
    else:
        p0 = Pivot(0, dates[0], closes[0], "low")

    # Guard against un-adjusted stock splits (or bad prints) anywhere in the
    # window we're about to base a pattern on. A real reverse split shows up
    # as an enormous single-day "move" -- catch it here regardless of
    # whether the data vendor's adjusted-price field is current.
    if _has_implausible_single_day_move(closes, p0.index, settings.MAX_SINGLE_DAY_MOVE_PCT):
        raise _NoMatch(WaveMatch(
            matched=False,
            reason=f"implausible single-day move (>{settings.MAX_SINGLE_DAY_MOVE_PCT:.0%}) in window -- "
                   f"likely an un-adjusted split or bad data print, not real price action",
        ))

    if not (p0.price < p1.price):
        raise _NoMatch(WaveMatch(matched=False, reason="wave 1 not upward"))

    wave1_len = p1.price - p0.price
    if wave1_len <= 0:
        raise _NoMatch(WaveMatch(matched=False, reason="degenerate wave 1"))

    if p2.price <= p0.price:
        raise _NoMatch(WaveMatch(matched=False, reason="wave 2 broke below wave 1 start (invalidated)"))

    retrace_pct = (p1.price - p2.price) / wave1_len
    if not (0.20 <= retrace_pct <= 0.90):
        raise _NoMatch(WaveMatch(matched=False, reason=f"wave 2 retrace {retrace_pct:.0%} outside typical range"))

    current_price = closes[-1]
    if current_price <= p1.price:
        raise _NoMatch(WaveMatch(matched=False, reason="price hasn't exceeded wave-1 high yet (still in wave 2)"))

    return p0, p1, p2, wave1_len, retrace_pct, current_price


def _volume_ratio(volumes, p2):
    baseline_end = p2.index
    baseline_start = max(0, baseline_end - 60)
    baseline_vols = volumes[baseline_start:baseline_end] or volumes[:baseline_end + 1]
    baseline_avg = sum(baseline_vols) / len(baseline_vols) if baseline_vols else 0

    wave3_vols = volumes[p2.index:]
    wave3_avg = sum(wave3_vols) / len(wave3_vols) if wave3_vols else 0

    return (wave3_avg / baseline_avg) if baseline_avg > 0 else 0


def detect_wave3_established(
    dates: list[str],
    closes: list[float],
    volumes: list[float],
    zigzag_pct: float = None,
    volume_surge_mult: float = None,
) -> WaveMatch:
    """ORIGINAL screener: wave 3 already well-extended (>= 61.8% of wave 1's
    length past the wave-2 low). Higher conviction, later entry.
    """
    zigzag_pct = zigzag_pct or settings.ZIGZAG_PCT
    volume_surge_mult = volume_surge_mult or settings.VOLUME_SURGE_MULT

    try:
        p0, p1, p2, wave1_len, retrace_pct, current_price = _find_wave12(dates, closes, volumes, zigzag_pct)
    except _NoMatch as e:
        return e.match

    wave3_progress = current_price - p2.price
    wave3_extension_pct = wave3_progress / wave1_len
    if wave3_extension_pct < 0.618:
        return WaveMatch(matched=False, reason="wave 3 move not yet extended enough")

    volume_ratio = _volume_ratio(volumes, p2)
    if volume_ratio < volume_surge_mult:
        return WaveMatch(
            matched=False,
            volume_ratio=round(volume_ratio, 2),
            reason=f"volume only {volume_ratio:.2f}x baseline, need >= {volume_surge_mult}x",
        )

    retrace_score = 1 - min(abs(retrace_pct - 0.5) / 0.5, 1)
    extension_score = min(wave3_extension_pct / 1.618, 1)
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


def detect_wave3_early(
    dates: list[str],
    closes: list[float],
    volumes: list[float],
    zigzag_pct: float = None,
    volume_surge_mult: float = None,
    max_extension_pct: float = None,
    max_breakout_age_bars: int = None,
) -> WaveMatch:
    """NEW screener: catches wave 3 near its START. Requires a recent
    breakout above the wave-1 high (within max_breakout_age_bars trading
    days) and limits how far the move has already extended (under
    max_extension_pct of wave 1's length). Earlier entry, lower conviction.
    """
    zigzag_pct = zigzag_pct or settings.ZIGZAG_PCT
    volume_surge_mult = volume_surge_mult or settings.VOLUME_SURGE_MULT
    max_extension_pct = max_extension_pct if max_extension_pct is not None else settings.MAX_WAVE3_EXTENSION_PCT
    max_breakout_age_bars = max_breakout_age_bars if max_breakout_age_bars is not None else settings.MAX_BREAKOUT_AGE_BARS

    try:
        p0, p1, p2, wave1_len, retrace_pct, current_price = _find_wave12(dates, closes, volumes, zigzag_pct)
    except _NoMatch as e:
        return e.match

    wave3_progress = current_price - p1.price
    wave3_extension_pct = wave3_progress / wave1_len
    if wave3_extension_pct > max_extension_pct:
        return WaveMatch(
            matched=False,
            wave3_extension_pct=round(wave3_extension_pct * 100, 2),
            reason=f"already {wave3_extension_pct:.0%} past the breakout point -- past the early stage",
        )

    breakout_idx = None
    for i in range(p2.index + 1, len(closes)):
        if closes[i] > p1.price:
            breakout_idx = i
            break
    if breakout_idx is None:
        return WaveMatch(matched=False, reason="could not locate breakout bar")

    bars_since_breakout = (len(closes) - 1) - breakout_idx
    if bars_since_breakout > max_breakout_age_bars:
        return WaveMatch(
            matched=False,
            bars_since_breakout=bars_since_breakout,
            reason=f"broke out {bars_since_breakout} bars ago -- too long ago to be 'just starting'",
        )

    volume_ratio = _volume_ratio(volumes, p2)
    if volume_ratio < volume_surge_mult:
        return WaveMatch(
            matched=False,
            volume_ratio=round(volume_ratio, 2),
            reason=f"volume only {volume_ratio:.2f}x baseline, need >= {volume_surge_mult}x",
        )

    retrace_score = 1 - min(abs(retrace_pct - 0.5) / 0.5, 1)
    freshness_score = 1 - min(wave3_extension_pct / max_extension_pct, 1)
    recency_score = 1 - min(bars_since_breakout / max(max_breakout_age_bars, 1), 1)
    volume_score = min((volume_ratio - volume_surge_mult) / volume_surge_mult, 1)
    confidence = round(100 * (
        0.25 * retrace_score
        + 0.30 * freshness_score
        + 0.20 * recency_score
        + 0.25 * volume_score
    ), 1)
    confidence = max(0.0, min(100.0, confidence))

    return WaveMatch(
        matched=True,
        confidence=confidence,
        volume_ratio=round(volume_ratio, 2),
        wave1_pct=round(wave1_len / p0.price * 100, 2),
        wave3_extension_pct=round(wave3_extension_pct * 100, 2),
        retrace_pct=round(retrace_pct * 100, 2),
        bars_since_breakout=bars_since_breakout,
        pivots=[
            {"date": p0.date, "price": p0.price, "kind": "low", "label": "0"},
            {"date": p1.date, "price": p1.price, "kind": "high", "label": "1"},
            {"date": p2.date, "price": p2.price, "kind": "low", "label": "2"},
            {"date": dates[-1], "price": current_price, "kind": "current", "label": "3?"},
        ],
        reason="wave-3-just-starting with volume confirmation",
    )
