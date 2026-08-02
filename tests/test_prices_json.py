from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.prices as prices
from app.prices import PriceLookupError, TarkovPriceClient


ITEM_ID = "5447a9cd4bdc2dbd208b4567"


def _item_document(price: int) -> dict[str, object]:
    return {
        "data": {
            "items": {
                ITEM_ID: {
                    "id": ITEM_ID,
                    "name": f"{ITEM_ID} Name",
                    "shortName": f"{ITEM_ID} ShortName",
                    "normalizedName": "colt-m4a1-556x45-assault-rifle",
                    "width": 1,
                    "height": 1,
                    "types": ["gun"],
                    "lastLowPrice": price,
                    "avg24hPrice": price + 1000,
                    "updated": "2026-08-01T15:08:01.000Z",
                    "sellToTrader": [
                        {
                            "trader": "5a7c2eca46aef81a7ca2145d",
                            "price": 10000,
                            "priceRUB": 10000,
                            "currency": "RUB",
                        }
                    ],
                }
            }
        },
        "translations": ["$.data.items.*.name", "$.data.items.*.shortName"],
    }


ENGLISH = {
    "data": {
        f"{ITEM_ID} Name": "Colt M4A1 5.56x45 assault rifle",
        f"{ITEM_ID} ShortName": "M4A1",
    }
}


CHINESE = {
    "data": {
        f"{ITEM_ID} Name": "柯尔特 M4A1 5.56x45 突击步枪",
        f"{ITEM_ID} ShortName": "M4A1",
    }
}


class JsonPriceClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.cache_directory = Path(self.temporary_directory.name) / "cache"
        self.cache_patch = patch.object(prices, "CACHE_DIR", self.cache_directory)
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)
        self.client = TarkovPriceClient(
            cache_path=self.cache_directory / "legacy.json",
            aliases_path=Path(self.temporary_directory.name) / "aliases.json",
            minimum_item_count=1,
        )

    def test_set_game_mode_reuses_the_loaded_in_memory_cache(self) -> None:
        loaded_items = [{"id": "loaded", "name": "Loaded item"}]
        self.client._items_by_mode["pve"] = loaded_items

        with patch.object(self.client, "_load_disk_cache") as load_disk_cache:
            selected = self.client.set_game_mode("pve")

        self.assertEqual(selected, "pve")
        self.assertIs(self.client._items_by_mode["pve"], loaded_items)
        load_disk_cache.assert_not_called()

    def test_set_game_mode_loads_from_disk_only_when_memory_is_empty(self) -> None:
        self.client._items_by_mode["pve"] = []

        with patch.object(self.client, "_load_disk_cache") as load_disk_cache:
            selected = self.client.set_game_mode("pve")

        self.assertEqual(selected, "pve")
        load_disk_cache.assert_called_once_with("pve")

    def test_json_refresh_is_default_and_merges_translations(self) -> None:
        documents = {
            "regular/items": (_item_document(27000), '"regular"'),
            "pve/items": (_item_document(31000), '"pve"'),
            "regular/items_en": (ENGLISH, '"en"'),
            "regular/items_zh": (CHINESE, '"zh"'),
        }

        with patch.object(
            self.client,
            "_fetch_json_document",
            side_effect=lambda path: documents[path],
        ) as fetch_json, patch.object(self.client, "_fetch_graphql_items") as fetch_graphql:
            counts = self.client.refresh_all_modes()

        self.assertEqual(counts, {"regular": 1, "pve": 1})
        self.assertEqual(fetch_json.call_count, 4)
        fetch_graphql.assert_not_called()
        item = self.client._items_by_mode["regular"][0]
        self.assertEqual(item["name"], "Colt M4A1 5.56x45 assault rifle")
        self.assertEqual(item["zhName"], "柯尔特 M4A1 5.56x45 突击步枪")
        self.assertEqual(item["sellFor"][0]["vendor"]["name"], "Mechanic")
        cache = json.loads(
            (self.cache_directory / "tarkov_items_regular.json").read_text(encoding="utf-8")
        )
        self.assertEqual(cache["source"], "https://json.tarkov.dev")
        self.assertEqual(cache["json_etags"]["regular/items"], '"regular"')

    def test_json_failure_preserves_existing_cache(self) -> None:
        old_regular = [{"id": "old-regular", "name": "Old PvP"}]
        old_pve = [{"id": "old-pve", "name": "Old PvE"}]
        self.client._items_by_mode["regular"] = old_regular
        self.client._items_by_mode["pve"] = old_pve

        with patch.object(
            self.client,
            "_fetch_json_document",
            side_effect=PriceLookupError("JSON offline"),
        ):
            with self.assertRaisesRegex(PriceLookupError, "JSON offline"):
                self.client.refresh_all_modes()

        self.assertIs(self.client._items_by_mode["regular"], old_regular)
        self.assertIs(self.client._items_by_mode["pve"], old_pve)

    def test_partial_json_response_does_not_commit_either_mode(self) -> None:
        old_regular = [{"id": "old-regular", "name": "Old PvP"}]
        old_pve = [{"id": "old-pve", "name": "Old PvE"}]
        self.client._items_by_mode["regular"] = old_regular
        self.client._items_by_mode["pve"] = old_pve
        documents = {
            "regular/items": (_item_document(27000), '"regular"'),
            "pve/items": ({"data": {"items": {}}}, '"pve"'),
            "regular/items_en": (ENGLISH, '"en"'),
            "regular/items_zh": (CHINESE, '"zh"'),
        }

        with patch.object(
            self.client,
            "_fetch_json_document",
            side_effect=lambda path: documents[path],
        ):
            with self.assertRaisesRegex(PriceLookupError, "数据不完整"):
                self.client.refresh_all_modes()

        self.assertIs(self.client._items_by_mode["regular"], old_regular)
        self.assertIs(self.client._items_by_mode["pve"], old_pve)

    def test_unchanged_etags_skip_large_json_downloads(self) -> None:
        self.client._items_by_mode["regular"] = [{"id": ITEM_ID}]
        self.client._items_by_mode["pve"] = [{"id": ITEM_ID}]
        self.client._json_etags = {
            "regular/items": '"regular"',
            "pve/items": '"pve"',
            "regular/items_en": '"en"',
            "regular/items_zh": '"zh"',
        }

        with patch.object(
            self.client,
            "_json_resource_unchanged",
            return_value=True,
        ) as head_check, patch.object(self.client, "_fetch_json_document") as fetch_json:
            counts = self.client.refresh_all_modes()

        self.assertEqual(counts, {"regular": 1, "pve": 1})
        self.assertEqual(head_check.call_count, 4)
        fetch_json.assert_not_called()

    def test_graphql_is_only_used_when_explicitly_requested(self) -> None:
        english_item = {
            "id": ITEM_ID,
            "name": "M4A1",
            "shortName": "M4A1",
            "normalizedName": "m4a1",
        }
        chinese_item = {"id": ITEM_ID, "name": "M4A1", "shortName": "M4A1"}

        def graphql_items(_mode: str, language: str) -> list[dict[str, object]]:
            return [english_item] if language == "en" else [chinese_item]

        with patch.object(
            self.client,
            "_fetch_graphql_items",
            side_effect=graphql_items,
        ) as fetch_graphql, patch.object(self.client, "_fetch_json_document") as fetch_json:
            counts = self.client.refresh_all_modes(source="graphql")

        self.assertEqual(counts, {"regular": 1, "pve": 1})
        self.assertEqual(fetch_graphql.call_count, 4)
        fetch_json.assert_not_called()

    def test_historical_prices_use_json_by_default(self) -> None:
        points = [
            {"price": 100, "priceMin": 90, "timestamp": 1},
            {"price": 200, "priceMin": 180, "timestamp": 2},
        ]
        with patch.object(
            self.client,
            "_fetch_historical_prices_json",
            return_value=points,
        ) as fetch_json, patch.object(
            self.client,
            "_fetch_historical_prices_graphql",
        ) as fetch_graphql:
            summary = self.client.historical_price_summary(ITEM_ID)

        self.assertEqual(summary.median_price, 150)
        fetch_json.assert_called_once()
        fetch_graphql.assert_not_called()

    def test_frozen_seed_cache_is_loaded_when_writable_cache_is_missing(self) -> None:
        root = Path(self.temporary_directory.name)
        writable_cache = root / "portable" / "cache"
        bundled_cache = root / "bundle" / "cache"
        bundled_cache.mkdir(parents=True)
        for mode in ("regular", "pve"):
            (bundled_cache / f"tarkov_items_{mode}.json").write_text(
                json.dumps(
                    {
                        "fetched_at": 1_786_000_000,
                        "source": "seed",
                        "game_mode": mode,
                        "items": [{"id": f"seed-{mode}", "name": mode}],
                    }
                ),
                encoding="utf-8",
            )

        with patch.object(prices, "CACHE_DIR", writable_cache), patch.object(
            prices, "RESOURCE_CACHE_DIR", bundled_cache
        ):
            client = TarkovPriceClient(
                cache_path=root / "missing-legacy.json",
                aliases_path=root / "aliases.json",
                minimum_item_count=1,
            )

        self.assertEqual(client._items_by_mode["regular"][0]["id"], "seed-regular")
        self.assertEqual(client._items_by_mode["pve"][0]["id"], "seed-pve")
        self.assertFalse(writable_cache.exists())


if __name__ == "__main__":
    unittest.main()
