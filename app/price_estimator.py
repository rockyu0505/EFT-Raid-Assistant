from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping


MIN_DIRECT_OFFER_COUNT = 10
FAST_PRICE_DIVERGENCE_RATIO = 2.0
HISTORY_HALF_LIFE_HOURS = 6.0
HISTORY_WINDOW_HOURS = 48.0
REGIME_MIN_EFFECT_RATIO = 1.25
SALE_REGION_MARGIN_RATIO = 0.05


@dataclass(frozen=True)
class FastPriceEstimate:
    listing_price: int | None
    label: str
    conservative: bool
    divergence_ratio: float | None
    risk_notice: str = ""


@dataclass(frozen=True)
class SmartPriceEstimate:
    suggested_price: int | None
    lower_price: int | None
    upper_price: int | None
    confidence: str
    basis: str
    risk_notice: str
    sample_count: int
    effective_sample_size: float
    current_offer_count: int | None
    regime_shift: bool = False

    @property
    def confidence_label(self) -> str:
        return {"high": "高", "medium": "中", "low": "低"}.get(
            self.confidence,
            "低",
        )


@dataclass(frozen=True)
class SaleRegionAssessment:
    region: str
    flea_lower_net: int | None
    flea_upper_net: int | None
    trader_net: int | None
    margin_ratio: float = SALE_REGION_MARGIN_RATIO


@dataclass(frozen=True)
class _HistoryPoint:
    timestamp: float
    min_price: int
    book_price: int
    offer_count: int | None


def classify_sale_region(
    recent_low_net: object,
    avg_24h_net: object,
    trader_net: object,
    *,
    margin_ratio: float = SALE_REGION_MARGIN_RATIO,
) -> SaleRegionAssessment:
    """Classify flea/trader proceeds using both market references.

    The available fee-adjusted flea values form an uncertainty interval. With
    both channels present, one is called clearly better only when it beats the
    entire interval by the practical margin; incomplete comparisons are
    reported as unknown.
    """
    flea_values = [
        value
        for value in (
            _finite_int(recent_low_net),
            _finite_int(avg_24h_net),
        )
        if value is not None
    ]
    trader = _finite_int(trader_net)
    try:
        margin = float(margin_ratio)
    except (TypeError, ValueError, OverflowError):
        margin = SALE_REGION_MARGIN_RATIO
    if not math.isfinite(margin):
        margin = SALE_REGION_MARGIN_RATIO
    margin = max(0.0, margin)

    lower = min(flea_values) if flea_values else None
    upper = max(flea_values) if flea_values else None
    if not flea_values or trader is None:
        return SaleRegionAssessment(
            "unknown",
            lower,
            upper,
            trader,
            margin,
        )

    assert lower is not None and upper is not None
    if lower > trader * (1.0 + margin):
        region = "flea"
    elif trader > upper * (1.0 + margin):
        region = "trader"
    else:
        region = "close"
    return SaleRegionAssessment(region, lower, upper, trader, margin)


def build_fast_price_estimate(
    last_low_price: object,
    avg_24h_price: object,
    offer_count: object,
) -> FastPriceEstimate:
    """Build the immediate local suggestion and its market-risk notice.

    Smart mode off always follows the API recent low when it exists. Offer
    depth and disagreement with the 24-hour average affect only the warning;
    they do not silently replace the listing suggestion with a floor value.
    """
    last_low = _positive_int(last_low_price)
    avg_24h = _positive_int(avg_24h_price)
    offers = _non_negative_int(offer_count)

    if last_low is None and avg_24h is None:
        return FastPriceEstimate(None, "市场参考", True, None, "市场价格数据不足")

    if last_low is None:
        return FastPriceEstimate(
            avg_24h,
            "24h均价回退",
            True,
            None,
            "API最近低价缺失，建议价暂用24h均价",
        )
    if avg_24h is None:
        conservative = offers is None or offers < MIN_DIRECT_OFFER_COUNT
        risk = "24h均价缺失"
        if conservative:
            risk = _thin_offer_notice(offers) + "，且24h均价缺失"
        return FastPriceEstimate(
            last_low,
            "API最近低价",
            conservative,
            None,
            risk,
        )

    lower = min(last_low, avg_24h)
    upper = max(last_low, avg_24h)
    divergence = upper / lower
    thin = offers is None or offers < MIN_DIRECT_OFFER_COUNT
    conflicting = divergence >= FAST_PRICE_DIVERGENCE_RATIO
    conservative = thin or conflicting

    risks: list[str] = []
    if conflicting:
        risks.append(
            f"API最近低价与24h均价相差{divergence:.2f}倍，市场参考分歧较大"
        )
    if thin:
        risks.append(_thin_offer_notice(offers))

    return FastPriceEstimate(
        last_low,
        "API最近低价",
        conservative,
        divergence,
        "；".join(risks),
    )


def estimate_smart_listing_price(
    points: Iterable[Mapping[str, object]],
    *,
    current_last_low: object,
    current_offer_count: object,
    now: float | None = None,
) -> SmartPriceEstimate:
    """Estimate a competitive listing price from recent public offer history.

    The estimator works in log-price space, uses a liquidity/time weighted
    median and MAD, and treats the front-book average as a separate regime
    signal. It estimates a competitive listing price, not a completed trade.
    """
    history = _clean_history_points(points)
    current_low = _positive_int(current_last_low)
    current_offers = _non_negative_int(current_offer_count)
    if not history:
        return SmartPriceEstimate(
            suggested_price=current_low,
            lower_price=current_low,
            upper_price=current_low,
            confidence="low",
            basis="API最近低价",
            risk_notice="历史价格样本不足",
            sample_count=0,
            effective_sample_size=0.0,
            current_offer_count=current_offers,
        )

    latest_timestamp = history[-1].timestamp
    reference_time = float(now) if now is not None else latest_timestamp
    cutoff = latest_timestamp - HISTORY_WINDOW_HOURS * 3600.0
    history = [point for point in history if point.timestamp >= cutoff]

    regime_index = _detect_latest_regime_start(history)
    regime_shift = regime_index is not None
    if regime_index is not None:
        active = history[regime_index:]
    else:
        active = [
            point
            for point in history
            if point.timestamp >= latest_timestamp - 24.0 * 3600.0
        ]
        if len(active) < 6:
            active = history

    weighted_logs = [
        (
            math.log(point.min_price),
            _history_weight(point, latest_timestamp),
        )
        for point in active
    ]
    anchor_log = _weighted_median(weighted_logs)
    if anchor_log is None:
        return SmartPriceEstimate(
            suggested_price=current_low,
            lower_price=current_low,
            upper_price=current_low,
            confidence="low",
            basis="API最近低价",
            risk_notice="近期历史价格不可用",
            sample_count=0,
            effective_sample_size=0.0,
            current_offer_count=current_offers,
            regime_shift=regime_shift,
        )

    scale = _weighted_mad(weighted_logs, anchor_log)
    scale = max(1.4826 * scale, math.log(1.05))
    weights = [weight for _value, weight in weighted_logs if weight > 0]
    effective_samples = _effective_sample_size(weights)
    anchor_price = max(1, round(math.exp(anchor_log)))

    spread_abnormal = _latest_spread_is_abnormal(active, current_low)
    current_z: float | None = None
    if current_low is not None:
        current_z = abs(math.log(current_low) - anchor_log) / scale

    direct_current = (
        current_low is not None
        and current_offers is not None
        and current_offers >= MIN_DIRECT_OFFER_COUNT
        and current_z is not None
        and current_z <= 1.5
        and not spread_abnormal
    )
    if direct_current:
        suggested = current_low
        basis = "API最近低价"
    elif (
        current_low is not None
        and current_offers is not None
        and current_offers >= MIN_DIRECT_OFFER_COUNT
        and current_z is not None
        and current_z < 3.0
        and not spread_abnormal
    ):
        current_weight = max(0.0, min(1.0, (3.0 - current_z) / 1.5))
        suggested = max(
            1,
            round(
                math.exp(
                    current_weight * math.log(current_low)
                    + (1.0 - current_weight) * anchor_log
                )
            ),
        )
        basis = "最近低价与稳健慢线"
    else:
        suggested = anchor_price
        basis = "新行情稳健估价" if regime_shift else "近期稳健估价"

    radius = 1.5 * scale * math.sqrt(1.0 + 1.0 / max(1.0, effective_samples))
    radius = max(math.log(1.10), min(math.log(3.0), radius))
    lower_price = max(1, round(math.exp(math.log(suggested) - radius)))
    upper_price = max(lower_price, round(math.exp(math.log(suggested) + radius)))

    fresh_history = reference_time - latest_timestamp <= 6.0 * 3600.0
    regime_established = not regime_shift or (
        len(active) >= 5 and latest_timestamp - active[0].timestamp >= 8.0 * 3600.0
    )
    if (
        direct_current
        and len(active) >= 8
        and effective_samples >= 6.0
        and fresh_history
        and regime_established
    ):
        confidence = "high"
    elif len(active) >= 4 and effective_samples >= 3.0 and fresh_history:
        confidence = "medium"
    else:
        confidence = "low"

    risks: list[str] = []
    if current_offers is None or current_offers < MIN_DIRECT_OFFER_COUNT:
        risks.append(_thin_offer_notice(current_offers) + "，建议价采用近期稳健估计")
    if spread_abnormal:
        risks.append("最低挂单明显脱离前排报价")
    elif current_z is not None and current_z >= 3.0:
        risks.append("API最近低价明显偏离近期市场分布")
    if regime_shift:
        risks.append("检测到近期价格区间切换，已按新行情估算")
    if not fresh_history:
        risks.append("历史价格更新不够新")
    if effective_samples < 3.0:
        risks.append("有效历史样本较少")

    return SmartPriceEstimate(
        suggested_price=suggested,
        lower_price=lower_price,
        upper_price=upper_price,
        confidence=confidence,
        basis=basis,
        risk_notice="；".join(risks[:2]),
        sample_count=len(active),
        effective_sample_size=effective_samples,
        current_offer_count=current_offers,
        regime_shift=regime_shift,
    )


def _clean_history_points(
    points: Iterable[Mapping[str, object]],
) -> list[_HistoryPoint]:
    clean: list[_HistoryPoint] = []
    for point in points:
        min_price = _positive_int(point.get("priceMin"))
        book_price = _positive_int(point.get("price"))
        timestamp = _timestamp_seconds(point.get("timestamp"))
        if min_price is None or timestamp is None:
            continue
        clean.append(
            _HistoryPoint(
                timestamp=timestamp,
                min_price=min_price,
                book_price=book_price or min_price,
                offer_count=_non_negative_int(point.get("offerCount")),
            )
        )
    clean.sort(key=lambda point: point.timestamp)
    return clean


def _detect_latest_regime_start(points: list[_HistoryPoint]) -> int | None:
    if len(points) < 11:
        return None

    segment_start = 0
    candidate_start: int | None = None
    direction = 0
    frozen_center = 0.0
    frozen_scale = 1.0
    cumulative = 0.0
    latest_regime_start: int | None = None

    for index in range(8, len(points)):
        current_log = math.log(points[index].book_price)
        if candidate_start is None:
            baseline = points[max(segment_start, index - 24) : index]
            stats = _robust_log_stats(point.book_price for point in baseline)
            if stats is None:
                continue
            center, scale = stats
            residual = (current_log - center) / scale
            if abs(residual) < 2.0:
                continue
            candidate_start = index
            direction = 1 if residual > 0 else -1
            frozen_center = center
            frozen_scale = scale
            cumulative = max(0.0, abs(residual) - 0.5)
            continue

        residual = direction * (current_log - frozen_center) / frozen_scale
        if residual <= 0.5:
            candidate_start = None
            direction = 0
            cumulative = 0.0
            continue

        cumulative += max(0.0, residual - 0.5)
        suffix = points[candidate_start : index + 1]
        if len(suffix) < 3:
            continue
        offers = [point.offer_count or 0 for point in suffix[-3:]]
        median_offers = statistics.median(offers)
        fast_book = statistics.median(point.book_price for point in suffix[-3:])
        effect = abs(math.log(fast_book) - frozen_center)
        if (
            cumulative >= 5.0
            and median_offers >= MIN_DIRECT_OFFER_COUNT
            and effect >= math.log(REGIME_MIN_EFFECT_RATIO)
        ):
            segment_start = candidate_start
            latest_regime_start = candidate_start
            candidate_start = None
            direction = 0
            cumulative = 0.0

    return latest_regime_start


def _latest_spread_is_abnormal(
    points: list[_HistoryPoint],
    current_low: int | None,
) -> bool:
    if not points:
        return False
    latest = points[-1]
    if latest.min_price <= 0 or latest.book_price < latest.min_price:
        return False
    if current_low is not None:
        similarity = max(current_low, latest.min_price) / min(current_low, latest.min_price)
        if similarity > 1.5:
            return False

    latest_spread = math.log(latest.book_price / latest.min_price)
    previous = [
        math.log(point.book_price / point.min_price)
        for point in points[:-1]
        if point.book_price >= point.min_price > 0
    ]
    stats = _robust_values(previous)
    if stats is None:
        return latest.book_price / latest.min_price >= 2.5
    center, scale = stats
    return latest_spread >= math.log(2.0) and (latest_spread - center) / scale >= 3.0


def _history_weight(point: _HistoryPoint, latest_timestamp: float) -> float:
    age_hours = max(0.0, (latest_timestamp - point.timestamp) / 3600.0)
    time_weight = math.pow(0.5, age_hours / HISTORY_HALF_LIFE_HOURS)
    if point.offer_count is None:
        liquidity_weight = 0.25
    else:
        liquidity_weight = max(0.10, min(1.0, point.offer_count / 10.0))
    return time_weight * liquidity_weight


def _weighted_median(values: list[tuple[float, float]]) -> float | None:
    ordered = sorted((value, weight) for value, weight in values if weight > 0)
    if not ordered:
        return None
    total = sum(weight for _value, weight in ordered)
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= total / 2.0:
            return value
    return ordered[-1][0]


def _weighted_mad(values: list[tuple[float, float]], center: float) -> float:
    result = _weighted_median(
        [(abs(value - center), weight) for value, weight in values]
    )
    return result or 0.0


def _effective_sample_size(weights: list[float]) -> float:
    if not weights:
        return 0.0
    total = sum(weights)
    squared = sum(weight * weight for weight in weights)
    return total * total / squared if squared > 0 else 0.0


def _robust_log_stats(values: Iterable[int]) -> tuple[float, float] | None:
    logs = [math.log(value) for value in values if value > 0]
    return _robust_values(logs)


def _robust_values(values: Iterable[float]) -> tuple[float, float] | None:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if len(clean) < 6:
        return None
    center = statistics.median(clean)
    mad = statistics.median(abs(value - center) for value in clean)
    return center, max(1.4826 * mad, math.log(1.05))


def _timestamp_seconds(value: object) -> float | None:
    if isinstance(value, (int, float)):
        timestamp = float(value)
        return timestamp / 1000.0 if timestamp > 10_000_000_000 else timestamp
    text = str(value or "").strip()
    if not text:
        return None
    try:
        numeric = float(text)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    return numeric / 1000.0 if numeric > 10_000_000_000 else numeric


def _positive_int(value: object) -> int | None:
    try:
        result = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result > 0 else None


def _finite_int(value: object) -> int | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    return int(number)


def _non_negative_int(value: object) -> int | None:
    try:
        result = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result >= 0 else None


def _thin_offer_notice(offers: int | None) -> str:
    if offers is None:
        return "API挂单深度未知，最近低价波动风险较高"
    return f"API当前仅{offers}个挂单，最近低价波动风险较高"
