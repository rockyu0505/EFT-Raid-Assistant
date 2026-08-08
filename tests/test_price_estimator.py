from __future__ import annotations

import time
import unittest

from app.price_estimator import (
    build_fast_price_estimate,
    classify_sale_region,
    estimate_smart_listing_price,
)


def _point(
    timestamp: float,
    minimum: int,
    *,
    book: int | None = None,
    offers: int = 20,
) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "priceMin": minimum,
        "price": book if book is not None else minimum,
        "offerCount": offers,
    }


class FastPriceEstimateTests(unittest.TestCase):
    def test_deep_market_uses_recent_low_when_references_agree(self) -> None:
        result = build_fast_price_estimate(105_000, 100_000, 10)

        self.assertEqual(result.listing_price, 105_000)
        self.assertEqual(result.label, "API最近低价")
        self.assertFalse(result.conservative)
        self.assertEqual(result.risk_notice, "")

    def test_large_divergence_keeps_recent_low_and_warns(self) -> None:
        result = build_fast_price_estimate(50_000, 143_700, 20)

        self.assertEqual(result.listing_price, 50_000)
        self.assertEqual(result.label, "API最近低价")
        self.assertTrue(result.conservative)
        self.assertAlmostEqual(result.divergence_ratio or 0.0, 2.874, places=3)
        self.assertIn("市场参考分歧较大", result.risk_notice)

    def test_thin_market_keeps_recent_low_and_warns(self) -> None:
        result = build_fast_price_estimate(120_000, 100_000, 9)

        self.assertEqual(result.listing_price, 120_000)
        self.assertTrue(result.conservative)
        self.assertIn("API当前仅9个挂单", result.risk_notice)
        self.assertIn("波动风险较高", result.risk_notice)


class SaleRegionTests(unittest.TestCase):
    def test_flea_is_better_only_when_the_lower_reference_clears_margin(self) -> None:
        result = classify_sale_region(90_000, 110_000, 80_000)

        self.assertEqual(result.region, "flea")
        self.assertEqual(result.flea_lower_net, 90_000)
        self.assertEqual(result.flea_upper_net, 110_000)

    def test_trader_is_better_only_when_it_clears_the_upper_reference(self) -> None:
        result = classify_sale_region(90_000, 110_000, 120_000)

        self.assertEqual(result.region, "trader")

    def test_straddled_or_small_differences_are_close(self) -> None:
        cases = (
            (90_000, 110_000, 100_000),
            (100_000, 101_000, 98_000),
            (100_000, 101_000, 105_000),
        )

        for recent, average, trader in cases:
            with self.subTest(recent=recent, average=average, trader=trader):
                self.assertEqual(
                    classify_sale_region(recent, average, trader).region,
                    "close",
                )

    def test_missing_trader_or_market_data_degrades_cleanly(self) -> None:
        self.assertEqual(classify_sale_region(10_000, 12_000, None).region, "unknown")
        self.assertEqual(classify_sale_region(None, None, 5_000).region, "unknown")
        self.assertEqual(classify_sale_region(None, None, None).region, "unknown")

    def test_exact_five_percent_difference_remains_close(self) -> None:
        self.assertEqual(classify_sale_region(105_000, 105_000, 100_000).region, "close")
        self.assertEqual(classify_sale_region(100_000, 100_000, 105_000).region, "close")


class SmartPriceEstimateTests(unittest.TestCase):
    def test_stable_deep_market_accepts_a_normal_current_low(self) -> None:
        now = time.time()
        history = [
            _point(
                now - (11 - index) * 3600,
                99_000 + (index % 3) * 1_000,
                book=101_000 + (index % 2) * 1_000,
                offers=24,
            )
            for index in range(12)
        ]

        result = estimate_smart_listing_price(
            history,
            current_last_low=101_000,
            current_offer_count=24,
            now=now,
        )

        self.assertEqual(result.suggested_price, 101_000)
        self.assertEqual(result.basis, "API最近低价")
        self.assertEqual(result.confidence, "high")
        self.assertFalse(result.regime_shift)

    def test_thin_current_book_falls_back_to_robust_history(self) -> None:
        now = time.time()
        history = [
            _point(now - (9 - index) * 3600, 98_000 + (index % 3) * 1_000)
            for index in range(10)
        ]

        result = estimate_smart_listing_price(
            history,
            current_last_low=250_000,
            current_offer_count=9,
            now=now,
        )

        self.assertLess(result.suggested_price or 0, 110_000)
        self.assertGreater(result.suggested_price or 0, 90_000)
        self.assertNotEqual(result.basis, "API最近低价")
        self.assertIn("API当前仅9个挂单", result.risk_notice)

    def test_confirmed_broad_shift_tracks_a_new_price_regime(self) -> None:
        now = time.time()
        old_market = [
            _point(
                now - (15 - index) * 3600,
                19_500 + (index % 2) * 500,
                book=20_000,
                offers=30,
            )
            for index in range(12)
        ]
        new_market = [
            _point(
                now - (3 - index) * 3600,
                58_000 + (index % 2) * 2_000,
                book=60_000,
                offers=28,
            )
            for index in range(4)
        ]

        result = estimate_smart_listing_price(
            old_market + new_market,
            current_last_low=59_000,
            current_offer_count=28,
            now=now,
        )

        self.assertTrue(result.regime_shift)
        self.assertGreater(result.suggested_price or 0, 50_000)
        self.assertLess(result.suggested_price or 0, 70_000)
        self.assertIn(result.confidence, {"medium", "high"})
        self.assertIn("价格区间切换", result.risk_notice)

    def test_single_low_offer_does_not_create_a_false_regime_shift(self) -> None:
        now = time.time()
        history = [
            _point(now - (10 - index) * 3600, 100_000, book=101_000, offers=20)
            for index in range(10)
        ]
        history.append(_point(now, 20_000, book=100_000, offers=2))

        result = estimate_smart_listing_price(
            history,
            current_last_low=20_000,
            current_offer_count=2,
            now=now,
        )

        self.assertFalse(result.regime_shift)
        self.assertGreater(result.suggested_price or 0, 80_000)
        self.assertIn("当前仅2个挂单", result.risk_notice)


if __name__ == "__main__":
    unittest.main()
