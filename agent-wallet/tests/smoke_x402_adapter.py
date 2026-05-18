"""Smoke coverage for x402 OpenClaw adapter surface."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.openclaw_adapter import OpenClawWalletAdapter
from agent_wallet.providers import x402
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletCapabilities


class FakeBackend(AgentWalletBackend):
    name = "fake_wallet"
    chain = "solana"
    network = "devnet"

    async def get_address(self) -> str | None:
        return "Fake11111111111111111111111111111111111111111"

    async def get_balance(self, address: str | None = None) -> dict[str, object]:
        return {"address": address or "Fake11111111111111111111111111111111111111111"}

    def get_capabilities(self) -> WalletCapabilities:
        return WalletCapabilities(
            backend=self.name,
            chain=self.chain,
            custody_model="local",
            sign_only=False,
            has_signer=True,
            can_sign_transaction=True,
            can_send_transaction=True,
        )


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | list, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeClient:
    async def get(self, url: str, *, params=None):
        if url.endswith("/search"):
            return FakeResponse(
                200,
                {
                    "resources": [
                        {
                            "resource": "https://paid.example.com/report",
                            "type": "http",
                            "x402Version": 2,
                            "description": "Premium report endpoint",
                            "lastUpdated": "2026-05-18T00:00:00Z",
                            "accepts": [],
                        }
                    ],
                    "partialResults": False,
                    "searchMethod": "vector",
                },
            )
        raise AssertionError(f"Unexpected GET {url}")

    async def request(self, method: str, url: str, *, headers=None, json=None, content=None):
        encoded = base64.b64encode(
            json_module.dumps(
                {
                    "x402Version": 2,
                    "accepts": [
                        {
                            "scheme": "exact",
                            "network": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",
                            "asset": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                            "amount": "100000",
                            "payTo": "Merchant11111111111111111111111111111111111",
                            "maxTimeoutSeconds": 60,
                            "extra": {"name": "USDC"},
                        }
                    ],
                }
            ).encode("utf-8")
        ).decode("ascii")
        return FakeResponse(402, {"error": "payment required"}, headers={"PAYMENT-REQUIRED": encoded})


json_module = json


async def main() -> None:
    original_get_client = x402.get_client
    try:
        x402.get_client = lambda: FakeClient()
        adapter = OpenClawWalletAdapter(FakeBackend())
        tool_names = {tool.name for tool in adapter.list_tools()}
        assert "x402_search_services" in tool_names
        assert "x402_get_service_details" in tool_names
        assert "x402_preview_request" in tool_names

        search = await adapter.invoke(
            "x402_search_services",
            {"query": "premium", "discovery_provider": "cdp_bazaar"},
        )
        assert search.ok is True
        assert search.data["count"] == 1

        preview = await adapter.invoke(
            "x402_preview_request",
            {"url": "https://paid.example.com/report", "method": "GET"},
        )
        assert preview.ok is True
        assert preview.data["payment_required"] is True
        assert preview.data["selected_payment"]["amount_display"] == "0.1"
    finally:
        x402.get_client = original_get_client

    print("smoke_x402_adapter: ok")


if __name__ == "__main__":
    asyncio.run(main())
