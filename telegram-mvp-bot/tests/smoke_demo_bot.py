from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentlayer_demo_bot.logic import build_preview, compare_text
from agentlayer_demo_bot.models import ParsedIntent
from agentlayer_demo_bot.parsing import fallback_parse_intent
from agentlayer_demo_bot.storage import Storage


class DemoBotSmokeTest(unittest.TestCase):
    def test_fallback_swap_parse(self) -> None:
        parsed = fallback_parse_intent("Обмени 10000 RUB на USDT")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.intent, "swap")
        self.assertEqual(parsed.payment_asset, "RUB")
        self.assertEqual(parsed.target_asset, "USDT")
        self.assertEqual(parsed.amount, 10000.0)

    def test_build_preview(self) -> None:
        balances = {"RUB": 500000.0, "USDT": 5000.0, "BTC": 0.0, "SOL": 0.0, "A7A5": 0.0, "TSLAX": 0.0, "NVDAX": 0.0}
        preview = build_preview(
            ParsedIntent(
                intent="buy_asset",
                amount=50000.0,
                payment_asset="RUB",
                target_asset="TSLAX",
            ),
            balances,
        )
        self.assertAlmostEqual(preview.fee_amount, 300.0)
        self.assertGreater(preview.to_amount, 2.0)
        self.assertAlmostEqual(preview.balances_after["RUB"], 450000.0)

    def test_fallback_greeting_parse(self) -> None:
        parsed = fallback_parse_intent("Привет, что ты умеешь?")
        self.assertIsNotNone(parsed)
        self.assertIn(parsed.intent, {"help", "portfolio", "balance", "history", "compare", "buy_asset", "swap", "unknown", "chat"})

    def test_storage_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = Storage(f"{tmpdir}/demo.sqlite3")
            user_id = storage.get_or_create_user(123, "demo")
            balances = storage.get_balances(user_id)
            self.assertEqual(balances["RUB"], 500000.0)
            self.assertEqual(balances["USDT"], 5000.0)

    def test_compare_text(self) -> None:
        text = compare_text(100000.0, "RUB", "BTC", "SOL")
        self.assertIn("BTC", text)
        self.assertIn("SOL", text)


if __name__ == "__main__":
    unittest.main()
