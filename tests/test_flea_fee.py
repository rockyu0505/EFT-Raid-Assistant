from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.config import DEFAULT_CONFIG
from app.gui import _build_price_view, _format_api_sample_age
from app.price_estimator import SmartPriceEstimate
from app.prices import calculate_flea_market_fee


class FleaMarketFeeTests(unittest.TestCase):
    def test_medical_tools_matches_all_in_game_measurements(self) -> None:
        observed = {
            1_000: 807,
            2_500: 489,
            5_000: 422,
            10_000: 572,
            15_000: 859,
            20_000: 1_244,
            25_000: 1_708,
            30_000: 2_244,
            100_000: 15_497,
        }

        for listing_price, expected_fee in observed.items():
            with self.subTest(listing_price=listing_price):
                self.assertEqual(
                    calculate_flea_market_fee(
                        7_500,
                        listing_price,
                        intelligence_center_level=3,
                        hideout_management_level=20,
                    ),
                    expected_fee,
                )

    def test_wd40_matches_all_in_game_measurements(self) -> None:
        observed = {
            1_000: 715,
            2_500: 440,
            5_000: 395,
            10_000: 565,
            15_000: 873,
            20_000: 1_281,
            25_000: 1_771,
            30_000: 2_335,
            100_000: 16_272,
        }

        for listing_price, expected_fee in observed.items():
            with self.subTest(listing_price=listing_price):
                self.assertEqual(
                    calculate_flea_market_fee(
                        6_958,
                        listing_price,
                        intelligence_center_level=3,
                        hideout_management_level=20,
                    ),
                    expected_fee,
                )

    def test_invalid_values_do_not_produce_a_fee(self) -> None:
        for base_price, listing_price in ((None, 10_000), (7_500, None), (0, 1), (1, 0)):
            with self.subTest(base_price=base_price, listing_price=listing_price):
                self.assertIsNone(calculate_flea_market_fee(base_price, listing_price))

    def test_price_view_compares_net_flea_value_with_best_trader(self) -> None:
        price = SimpleNamespace(
            game_mode="pve",
            name="Medical tools",
            short_name="MedTools",
            zh_name="医疗工具",
            confidence=1.0,
            best_vendor_name="Therapist",
            best_vendor_currency="RUB",
            best_vendor_price=3_825,
            best_vendor_price_rub=3_825,
            avg_24h_price=10_000,
            last_low_price=10_000,
            last_offer_count=20,
            base_price=7_500,
            slots=1,
            is_firearm=False,
        )

        view = _build_price_view(
            price,
            "zh",
            [],
            "slot",
            flea_intelligence_center_level=3,
            flea_hideout_management_level=20,
        )

        self.assertEqual(view.value_text, "跳蚤更优")
        self.assertEqual(
            view.secondary_value_text,
            "建议挂 10,000 RUB · 净到手 9,428 RUB",
        )
        self.assertIn("API最近低价 10,000 RUB · 24h均价 10,000 RUB", view.detail)
        self.assertNotIn("手续费", view.detail)
        self.assertNotIn("Therapist", view.detail)
        self.assertNotIn("/格", view.detail)
        self.assertIn("跳蚤更优", view.log_text)

    def test_price_view_recommends_trader_when_net_flea_is_lower(self) -> None:
        price = SimpleNamespace(
            game_mode="pve",
            name="Medical tools",
            short_name="MedTools",
            zh_name="医疗工具",
            confidence=1.0,
            best_vendor_name="Therapist",
            best_vendor_currency="RUB",
            best_vendor_price=5_000,
            best_vendor_price_rub=5_000,
            avg_24h_price=5_000,
            last_low_price=5_000,
            last_offer_count=20,
            base_price=7_500,
            slots=1,
            is_firearm=False,
        )

        view = _build_price_view(
            price,
            "zh",
            [],
            "slot",
            flea_intelligence_center_level=3,
            flea_hideout_management_level=20,
        )

        self.assertEqual(view.value_text, "商人更优 · Therapist")
        self.assertEqual(
            view.secondary_value_text,
            "建议挂 5,000 RUB · 净到手 4,578 RUB",
        )
        self.assertIn("Therapist收购 5,000 RUB", view.detail)

    def test_divergent_market_uses_floor_for_value_and_multi_slot_colour(self) -> None:
        price = SimpleNamespace(
            game_mode="pve",
            name="A pack of screws",
            short_name="Screws",
            zh_name="一包螺钉",
            best_vendor_name="Therapist",
            best_vendor_currency="RUB",
            best_vendor_price=25_000,
            best_vendor_price_rub=25_000,
            avg_24h_price=143_700,
            last_low_price=50_000,
            last_offer_count=20,
            base_price=30_000,
            slots=2,
            is_firearm=False,
        )

        view = _build_price_view(
            price,
            "zh",
            DEFAULT_CONFIG["price_value_tiers"],
            "slot",
        )

        self.assertEqual(view.value_text, "跳蚤更优")
        self.assertTrue(view.secondary_value_text.startswith("建议挂 50,000 RUB"))
        self.assertNotIn("保底", view.label_html)
        self.assertNotIn("/格", view.detail)
        self.assertIn("市场参考分歧较大", view.detail)
        self.assertEqual(view.card_border_color, view.tier_color)

    def test_smart_price_updates_advice_but_not_conservative_colour(self) -> None:
        price = SimpleNamespace(
            game_mode="pve",
            name="Medical tools",
            short_name="MedTools",
            zh_name="医疗工具",
            best_vendor_name="Therapist",
            best_vendor_currency="RUB",
            best_vendor_price=3_825,
            best_vendor_price_rub=3_825,
            avg_24h_price=10_000,
            last_low_price=10_000,
            last_offer_count=20,
            base_price=7_500,
            slots=1,
            is_firearm=False,
        )
        smart = SmartPriceEstimate(
            suggested_price=30_000,
            lower_price=25_000,
            upper_price=35_000,
            confidence="high",
            basis="新行情稳健估价",
            risk_notice="检测到近期价格区间切换，已按新行情估算",
            sample_count=8,
            effective_sample_size=6.5,
            current_offer_count=20,
            regime_shift=True,
        )

        view = _build_price_view(
            price,
            "zh",
            DEFAULT_CONFIG["price_value_tiers"],
            "slot",
            smart_estimate=smart,
        )

        self.assertEqual(view.value_text, "跳蚤更优")
        self.assertIn("建议挂 30,000 RUB", view.secondary_value_text)
        self.assertIn("智能可信度 高", view.detail)
        self.assertEqual(view.tier_label, "白")
        self.assertEqual(view.card_border_color, "#F2F2F2")

    def test_low_confidence_smart_price_still_drives_listing_and_net(self) -> None:
        price = SimpleNamespace(
            game_mode="pve",
            name="Medical tools",
            short_name="MedTools",
            zh_name="医疗工具",
            best_vendor_name="Therapist",
            best_vendor_currency="RUB",
            best_vendor_price=3_825,
            best_vendor_price_rub=3_825,
            avg_24h_price=10_000,
            last_low_price=10_000,
            last_offer_count=20,
            base_price=7_500,
            slots=1,
            is_firearm=False,
        )
        smart = SmartPriceEstimate(
            suggested_price=30_000,
            lower_price=10_000,
            upper_price=50_000,
            confidence="low",
            basis="近期稳健估价",
            risk_notice="有效历史样本较少",
            sample_count=3,
            effective_sample_size=2.0,
            current_offer_count=20,
        )

        view = _build_price_view(
            price,
            "zh",
            DEFAULT_CONFIG["price_value_tiers"],
            "slot",
            smart_estimate=smart,
        )

        self.assertIn("建议挂 30,000 RUB", view.secondary_value_text)
        self.assertIn("智能可信度 低", view.detail)
        self.assertIn("有效历史样本较少", view.detail)

    def test_sale_region_uses_both_fee_adjusted_market_references(self) -> None:
        price = SimpleNamespace(
            game_mode="pve",
            name="Medical tools",
            short_name="MedTools",
            zh_name="医疗工具",
            best_vendor_name="Therapist",
            best_vendor_currency="RUB",
            best_vendor_price=12_000,
            best_vendor_price_rub=12_000,
            avg_24h_price=15_000,
            last_low_price=10_000,
            last_offer_count=20,
            base_price=7_500,
            slots=1,
            is_firearm=False,
        )

        view = _build_price_view(
            price,
            "zh",
            DEFAULT_CONFIG["price_value_tiers"],
            "slot",
            flea_intelligence_center_level=3,
            flea_hideout_management_level=20,
        )

        self.assertEqual(view.value_text, "收益接近")
        self.assertIn("Therapist收购 12,000 RUB", view.detail)

    def test_colour_uses_lower_market_net_then_applies_trader_floor(self) -> None:
        price = SimpleNamespace(
            game_mode="pve",
            name="Medical tools",
            short_name="MedTools",
            zh_name="医疗工具",
            best_vendor_name="Therapist",
            best_vendor_currency="RUB",
            best_vendor_price=3_825,
            best_vendor_price_rub=3_825,
            avg_24h_price=10_000,
            last_low_price=15_000,
            last_offer_count=20,
            base_price=7_500,
            slots=1,
            is_firearm=False,
        )

        view = _build_price_view(
            price,
            "zh",
            DEFAULT_CONFIG["price_value_tiers"],
            "slot",
            flea_intelligence_center_level=3,
            flea_hideout_management_level=20,
        )

        self.assertEqual(view.tier_label, "白")
        self.assertEqual(view.card_border_color, "#F2F2F2")

    def test_api_sample_age_formats_relative_and_old_timestamps(self) -> None:
        now = 1_800_000_000.0

        self.assertEqual(_format_api_sample_age(now - 20, now), "API采样 刚刚")
        self.assertEqual(_format_api_sample_age(now - 25 * 60, now), "API采样 25分钟前")
        self.assertEqual(
            _format_api_sample_age(now - (3600 + 42 * 60), now),
            "API采样 1小时42分钟前",
        )
        self.assertTrue(_format_api_sample_age(now - 2 * 86400, now).startswith("API采样 "))

    def test_api_sample_age_rejects_non_finite_or_implausible_values(self) -> None:
        now = 1_800_000_000.0

        for value in ("nan", "inf", "-inf", -1, now + 2 * 86400):
            with self.subTest(value=value):
                self.assertEqual(_format_api_sample_age(value, now), "")

    def test_missing_fee_inputs_do_not_claim_trader_is_better(self) -> None:
        price = SimpleNamespace(
            game_mode="pve",
            name="Medical tools",
            short_name="MedTools",
            zh_name="医疗工具",
            best_vendor_name="Therapist",
            best_vendor_currency="RUB",
            best_vendor_price=12_000,
            best_vendor_price_rub=12_000,
            avg_24h_price=15_000,
            last_low_price=10_000,
            last_offer_count=20,
            base_price=None,
            slots=1,
            is_firearm=False,
        )

        view = _build_price_view(price, "zh", [], "slot")

        self.assertEqual(view.value_text, "出售判断数据不足")
        self.assertIn("Therapist收购 12,000 RUB", view.detail)
        self.assertIn("手续费数据不足", view.detail)

    def test_smart_listing_does_not_change_close_sale_region(self) -> None:
        price = SimpleNamespace(
            game_mode="pve",
            name="Medical tools",
            short_name="MedTools",
            zh_name="医疗工具",
            best_vendor_name="Therapist",
            best_vendor_currency="RUB",
            best_vendor_price=12_000,
            best_vendor_price_rub=12_000,
            avg_24h_price=15_000,
            last_low_price=10_000,
            last_offer_count=20,
            base_price=7_500,
            slots=1,
            is_firearm=False,
        )
        smart = SmartPriceEstimate(
            suggested_price=30_000,
            lower_price=25_000,
            upper_price=35_000,
            confidence="high",
            basis="近期稳健估价",
            risk_notice="",
            sample_count=10,
            effective_sample_size=8.0,
            current_offer_count=20,
        )

        view = _build_price_view(
            price,
            "zh",
            DEFAULT_CONFIG["price_value_tiers"],
            "slot",
            flea_intelligence_center_level=3,
            flea_hideout_management_level=20,
            smart_estimate=smart,
        )

        self.assertEqual(view.value_text, "收益接近")
        self.assertNotIn("倾向", view.label_html)
        self.assertNotIn("相差", view.detail)
        self.assertIn("建议挂 30,000 RUB", view.secondary_value_text)

    def test_ammo_view_replaces_price_with_ballistic_data(self) -> None:
        price = SimpleNamespace(
            name="5.56x45mm M855A1",
            short_name="M855A1",
            zh_name="5.56x45毫米 M855A1",
            ammo_properties={
                "damage": 49,
                "penetrationPower": 44,
                "armorDamage": 52,
                "initialSpeed": 945,
                "projectileCount": 1,
                "recoilModifier": 0.05,
                "accuracyModifier": -0.05,
                "tracer": True,
                "tracerColor": "red",
            },
            ammo_pack_count=None,
        )

        view = _build_price_view(price, "zh", [], "slot")

        self.assertEqual(view.value_text, "伤害 49 · 穿深 44")
        self.assertEqual(view.tier_color, "#B47CFF")
        self.assertEqual(view.card_border_color, "#B47CFF")
        self.assertIn("后座 +5%", view.detail)
        self.assertIn("精度 -5%", view.detail)
        self.assertIn("曳光弹", view.detail)
        self.assertNotIn("RUB", view.label_html)

    def test_ammo_pack_and_multi_projectile_rounds_show_counts(self) -> None:
        price = SimpleNamespace(
            name="12/70 buckshot pack",
            short_name="buckshot",
            zh_name="12/70 鹿弹包",
            ammo_name="12/70 buckshot",
            ammo_zh_name="12/70 鹿弹",
            ammo_pack_count=25,
            ammo_properties={
                "damage": 37,
                "penetrationPower": 3,
                "armorDamage": 20,
                "initialSpeed": 415,
                "projectileCount": 8,
                "recoilModifier": 0,
                "accuracyModifier": 0,
            },
        )

        view = _build_price_view(price, "zh", [], "slot")

        self.assertEqual(view.value_text, "伤害 37 × 8 · 穿深 3")
        self.assertIn("内含 25 发 12/70 鹿弹", view.secondary_value_text)
        self.assertEqual(view.tier_color, "#F5F7FA")

    def test_over_seventy_penetration_uses_spectrum_accent(self) -> None:
        price = SimpleNamespace(
            name="Special AP",
            short_name="AP",
            zh_name="特殊穿甲弹",
            ammo_pack_count=None,
            ammo_properties={
                "damage": 85,
                "penetrationPower": 79,
                "armorDamage": 90,
                "initialSpeed": 900,
                "projectileCount": 1,
            },
        )

        view = _build_price_view(price, "zh", [], "slot")

        self.assertEqual(view.tier_label, "特殊穿透")
        self.assertTrue(view.tier_accent.startswith("qlineargradient("))


if __name__ == "__main__":
    unittest.main()
