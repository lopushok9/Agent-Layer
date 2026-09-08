"""Smoke coverage for privacy-safe x402 lifecycle telemetry."""

from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from agent_wallet import telemetry  # noqa: E402


def main() -> None:
    original_record = telemetry.record
    events: list[dict] = []
    try:
        telemetry.record = lambda tool, **kwargs: events.append({"tool": tool, **kwargs})

        telemetry.record_x402_lifecycle("x402_preview_request", {"ok": True, "data": {}})
        telemetry.record_x402_lifecycle("x402_preview_request", {"ok": False})
        telemetry.record_x402_lifecycle("x402_pay_request", {"ok": False})
        telemetry.record_x402_lifecycle(
            "x402_pay_request",
            {
                "ok": True,
                "data": {
                    "paid": True,
                    "x402_network": "eip155:8453",
                    "x402_scheme": "exact",
                    "x402_asset": "USDC",
                    "x402_amount_display": "2.50",
                    "payment_settlement": {"success": True},
                },
            },
        )
        telemetry.record_x402_lifecycle("x402_pay_request", {"ok": True, "data": {"paid": False}})
    finally:
        telemetry.record = original_record

    assert [event["event"] for event in events] == [
        "x402_previewed",
        "x402_preview_failed",
        "x402_payment_attempted",
        "x402_payment_failed",
        "x402_payment_attempted",
        "x402_payment_settled",
        "x402_payment_attempted",
        "x402_payment_not_required",
    ]
    assert all(event["tool"] == "" for event in events)
    settled = events[5]
    assert settled["network"] == "eip155:8453"
    assert settled["scheme"] == "exact"
    assert settled["asset_family"] == "usdc"
    assert settled["amount_bucket"] == "2_to_10_usd"
    assert settled["settlement_status"] == "settled"
    print("smoke_x402_telemetry_lifecycle: ok")


if __name__ == "__main__":
    main()
