"""
Bullish RSI divergence + unusual volume screener.

Pattern: price makes a low, then a second low at or below the first (NOT a
clearly higher low), while RSI's second low sits meaningfully ABOVE its
first -- momentum improving even as price stalls or slips. That divergence
only counts here if it's confirmed by a genuine volume SPIKE at or
immediately after the second low -- a single day well above baseline, not
just a mild sustained pickup. That spike is the "unusual trading activity"
that turns a maybe-signal into a real one.

  1. Find the last two swing lows via the shared zigzag pivot detector.
  2. Price: second low <= first low * (1 + small tolerance).
  3. RSI: RSI at the second low is meaningfully higher than at the first.
  4. Freshness: the second low must be recent, and price must currently be
     above it (a bounce has begun, but hasn't run far yet).
  5. Volume: an actual spike within the window from the second low to now.

Like every other screener here: mechanical pattern recognition, not proof
of a good trade. Divergences fail more often than highlight-reel examples
suggest. Verify manually before acting.
"""
from dataclasses import dataclass

from app.config import settings
from app.wave_detector import zigzag
from app.retest_pattern_detector import _rsi_series


@dataclass
class DivergenceMatch:
    matched: bool
    confidence: float = 0.0
    rsi_prior_low: float = 0.0
    rsi_recent_low: float = 0.0
    price_prior_low: float = 0.0
    price_recent_low: float = 0.0
    divergence_age_bars: int = 0
    volume_spike_ratio: float = 0.0
    reason: str = ""


def _volume_baseline_and_spike(volumes: list[float], window_start: int, window_end: int, baseline_lookback: int = 60):
    """Baseline = average volume in the period BEFORE the divergence low.
    Spike ratio = the single highest day's volume within [window_start,
    window_end] (the divergence low through now) relative to that
    baseline -- deliberately the MAX, not an average, since we're looking
    for an unusual single-day spike, not a smoothly elevated period.
    """
    baseline_start = max(0, window_start - baseline_lookback)
    baseline = volumes[baseline_start:window_start]
    baseline_avg = sum(baseline) / len(baseline) if baseline else 0
    if baseline_avg <= 0:
        return 0, 0
    window = volumes[window_start:window_end + 1]
    max_spike_ratio = max((v / baseline_avg for v in window), default=0)
    return baseline_avg, max_spike_ratio


def detect_bullish_divergence(
    dates: list[str],
    closes: list[float],
    volumes: list[float],
    zigzag_pct: float = None,
    price_tolerance_pct: float = None,
    min_rsi_gap: float = None,
    max_divergence_age_bars: int = None,
    min_volume_spike_mult: float = None,
) -> DivergenceMatch:
    zigzag_pct = zigzag_pct or settings.DIVERGENCE_ZIGZAG_PCT
    price_tolerance_pct = price_tolerance_pct if price_tolerance_pct is not None else settings.DIVERGENCE_PRICE_TOLERANCE_PCT
    min_rsi_gap = min_rsi_gap if min_rsi_gap is not None else settings.DIVERGENCE_MIN_RSI_GAP
    max_divergence_age_bars = max_divergence_age_bars or settings.DIVERGENCE_MAX_AGE_BARS
    min_volume_spike_mult = min_volume_spike_mult if min_volume_spike_mult is not None else settings.DIVERGENCE_MIN_VOLUME_SPIKE_MULT

    if len(closes) < settings.DIVERGENCE_MIN_BARS:
        return DivergenceMatch(matched=False, reason="insufficient history")

    pivots = zigzag(dates, closes, zigzag_pct)
    low_pivots = [p for p in pivots if p.kind == "low"]
    if not low_pivots:
        return DivergenceMatch(matched=False, reason="not enough swing lows")

    last = len(closes) - 1

    # The recent low is EITHER the most recent confirmed low pivot itself,
    # OR (if price has declined again since the last confirmed high after
    # that) the current still-forming minimum -- whichever is more recent.
    # Confirmation only happens in hindsight once price reverses far enough,
    # which is fundamentally incompatible with catching this setup fresh,
    # so we can't just always require a confirmed pivot for "recent."
    recent_low_idx = low_pivots[-1].index
    recent_low_price = low_pivots[-1].price
    prior_low = low_pivots[-2] if len(low_pivots) >= 2 else None

    highs_after_last_low = [p for p in pivots if p.kind == "high" and p.index > low_pivots[-1].index]
    if highs_after_last_low:
        last_high = highs_after_last_low[-1]
        if last_high.index < last:
            unconfirmed_idx = min(range(last_high.index, last + 1), key=lambda i: closes[i])
            if unconfirmed_idx > recent_low_idx:
                recent_low_idx = unconfirmed_idx
                recent_low_price = closes[unconfirmed_idx]
                prior_low = low_pivots[-1]

    if prior_low is None:
        return DivergenceMatch(matched=False, reason="no earlier confirmed low to compare against")

    if prior_low.price <= 0:
        return DivergenceMatch(matched=False, reason="degenerate low")

    # Price must NOT make a clearly higher low -- has to be flat/lower for
    # this to be a divergence rather than just a normal uptrend continuation.
    if recent_low_price > prior_low.price * (1 + price_tolerance_pct):
        return DivergenceMatch(matched=False, reason="second low is clearly higher -- not a divergence setup")

    rsi_series = _rsi_series(closes)
    rsi_prior = rsi_series[prior_low.index]
    rsi_recent = rsi_series[recent_low_idx]
    if rsi_prior is None or rsi_recent is None:
        return DivergenceMatch(matched=False, reason="insufficient history for RSI at pivot points")

    rsi_gap = rsi_recent - rsi_prior
    if rsi_gap < min_rsi_gap:
        return DivergenceMatch(
            matched=False,
            rsi_prior_low=round(rsi_prior, 1), rsi_recent_low=round(rsi_recent, 1),
            reason=f"RSI only {rsi_gap:.1f} pts higher at the second low, need >= {min_rsi_gap}",
        )

    divergence_age = last - recent_low_idx
    if divergence_age > max_divergence_age_bars:
        return DivergenceMatch(matched=False, divergence_age_bars=divergence_age,
                                reason=f"divergence low was {divergence_age} bars ago -- not fresh")

    if closes[last] <= recent_low_price:
        return DivergenceMatch(matched=False, divergence_age_bars=divergence_age,
                                reason="price hasn't bounced off the divergence low yet")

    baseline_avg, spike_ratio = _volume_baseline_and_spike(volumes, recent_low_idx, last)
    if spike_ratio < min_volume_spike_mult:
        return DivergenceMatch(
            matched=False, divergence_age_bars=divergence_age, volume_spike_ratio=round(spike_ratio, 2),
            reason=f"no unusual volume spike found ({spike_ratio:.2f}x baseline, need >= {min_volume_spike_mult}x)",
        )

    freshness_score = 1 - (divergence_age / max(max_divergence_age_bars, 1))
    rsi_score = min(rsi_gap / (min_rsi_gap * 3), 1) if min_rsi_gap > 0 else 0
    volume_score = min((spike_ratio - min_volume_spike_mult) / max(min_volume_spike_mult, 0.1), 1)
    confidence = round(100 * (0.35 * freshness_score + 0.3 * rsi_score + 0.35 * volume_score), 1)
    confidence = max(0.0, min(100.0, confidence))

    return DivergenceMatch(
        matched=True, confidence=confidence,
        rsi_prior_low=round(rsi_prior, 1), rsi_recent_low=round(rsi_recent, 1),
        price_prior_low=round(prior_low.price, 2), price_recent_low=round(recent_low_price, 2),
        divergence_age_bars=divergence_age, volume_spike_ratio=round(spike_ratio, 2),
        reason="bullish RSI divergence confirmed by an unusual volume spike",
    )
