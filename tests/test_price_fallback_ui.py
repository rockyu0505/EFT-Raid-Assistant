from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QMessageBox

from app.gui import MainWindow, PriceCacheRefreshResult


class PriceFallbackUiTests(unittest.TestCase):
    def test_json_failure_asks_before_scheduling_graphql(self) -> None:
        window = Mock()
        window._closing = False
        window._feature_enabled.return_value = True
        window.cache_status_label = Mock()

        with patch(
            "app.gui.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ) as question, patch(
            "app.gui.QTimer.singleShot",
            side_effect=lambda _delay, callback: callback(),
        ):
            MainWindow._on_cache_refresh_ready(
                window,
                PriceCacheRefreshResult(source="json", error="HTTP 503"),
            )

        question.assert_called_once()
        window._start_graphql_price_cache_fallback.assert_called_once_with()

    def test_graphql_is_not_started_when_user_declines(self) -> None:
        window = Mock()
        window._closing = False
        window._feature_enabled.return_value = True
        window.cache_status_label = Mock()

        with patch(
            "app.gui.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ), patch("app.gui.QTimer.singleShot") as single_shot:
            MainWindow._on_cache_refresh_ready(
                window,
                PriceCacheRefreshResult(source="json", error="offline"),
            )

        single_shot.assert_not_called()
        window._start_graphql_price_cache_fallback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
