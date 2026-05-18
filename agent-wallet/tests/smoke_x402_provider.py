"""Smoke coverage for x402 discovery and preview helpers."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.providers import x402
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletCapabilities


class FakeBackend(AgentWalletBackend):
    name = "fake_wallet"
    chain = "solana"
    network = "devnet"
    signer = object()

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
    def __init__(self, status_code: int, payload: dict | list | str, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        if isinstance(payload, str):
            self.text = payload
        else:
            self.text = json.dumps(payload)
        self.content = self.text.encode("utf-8")

    def json(self):
        if isinstance(self._payload, str):
            raise ValueError("not json")
        return self._payload


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    async def get(self, url: str, *, params=None):
        self.calls.append(("GET", url, params))
        if "api.cdp.coinbase.com" in url and url.endswith("/search"):
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
                    ],
                    "partialResults": False,
                    "searchMethod": "vector",
                },
            )
        if "api.cdp.coinbase.com" in url and url.endswith("/resources"):
            return FakeResponse(
                200,
                {
                    "items": [
                        {
                            "resource": "https://paid.example.com/report",
                            "type": "http",
                            "x402Version": 2,
                            "metadata": {"description": "Premium report endpoint"},
                            "lastUpdated": "2026-05-18T00:00:00Z",
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
                    ],
                    "pagination": {"limit": 100, "offset": 0, "total": 1},
                },
            )
        if "api.agentic.market" in url and url.endswith("/services/search"):
            return FakeResponse(
                200,
                {
                    "services": [
                        {
                            "id": "svc-1",
                            "name": "Example Service",
                            "description": "Example Agentic Market service",
                            "domain": "paid.example.com",
                            "category": "Data",
                            "networks": ["solana"],
                            "integrationType": "1P",
                            "isNew": False,
                            "endpoints": [
                                {
                                    "url": "https://paid.example.com/report",
                                    "description": "Premium report endpoint",
                                    "method": "POST",
                                    "pricing": {
                                        "amount": "0.10",
                                        "currency": "USDC",
                                        "network": "solana",
                                    },
                                }
                            ],
                        }
                    ]
                },
            )
        raise AssertionError(f"Unexpected GET url: {url}")

    async def request(self, method: str, url: str, *, headers=None, json=None, content=None):
        self.calls.append((method, url, None))
        if url == "https://paid.example.com/report?topic=solana":
            if headers and headers.get("PAYMENT-SIGNATURE") == "signed-payload":
                return FakeResponse(
                    200,
                    {"ok": True, "result": "paid"},
                    headers={"PAYMENT-RESPONSE": "settled"},
                )
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
        return FakeResponse(200, {"ok": True, "result": "free"})


json_module = json


async def main() -> None:
    original_get_client = x402.get_client
    original_create_payment_headers = x402._create_payment_headers
    original_extract_settlement_header = x402._extract_settlement_header
    fake_client = FakeClient()
    try:
        x402.get_client = lambda: fake_client
        async def fake_create_payment_headers(*, backend, payment_required_header, selected_payment):
            assert payment_required_header
            assert selected_payment["scheme"] == "exact"
            return {"PAYMENT-SIGNATURE": "signed-payload"}

        x402._create_payment_headers = fake_create_payment_headers
        x402._extract_settlement_header = lambda response: {
            "success": True,
            "transaction": "solana-payment-tx",
            "network": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",
            "payer": "Fake11111111111111111111111111111111111111111",
            "amount": "100000",
        }

        cdp = await x402.search_services(query="premium report", discovery_provider="cdp_bazaar")
        assert cdp["count"] == 1
        assert cdp["items"][0]["resource"] == "https://paid.example.com/report"
        assert cdp["items"][0]["accepts"][0]["amount_display"] == "0.1"

        market = await x402.search_services(query="example", discovery_provider="agentic_market")
        assert market["count"] == 1
        assert market["items"][0]["service_id"] == "svc-1"
        assert market["items"][0]["endpoints"][0]["method"] == "POST"

        details = await x402.get_service_details(
            reference="https://paid.example.com/report",
            discovery_provider="cdp_bazaar",
        )
        assert details["service"]["resource"] == "https://paid.example.com/report"

        preview = await x402.preview_request(
            backend=FakeBackend(),
            url="https://paid.example.com/report",
            method="POST",
            query={"topic": "solana"},
            json_body={"depth": "full"},
        )
        assert preview["payment_required"] is True
        assert preview["selected_payment"]["network"] == "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"
        assert preview["wallet"]["wallet_type_supported"] is True
        assert preview["accepted_payments"][0]["compatibility"]["wallet_network_matches"] is True
        assert preview["accepted_payments"][0]["compatibility"]["currently_executable"] is True
        assert preview["execute_available"] is True
        assert preview["request"]["body_hash"]
        assert preview["request"]["request_fingerprint"]

        prepared = await x402.prepare_request(
            backend=FakeBackend(),
            url="https://paid.example.com/report",
            method="POST",
            query={"topic": "solana"},
            json_body={"depth": "full"},
        )
        assert prepared["prepared"] is True
        assert prepared["payment_payload_withheld"] is True

        executed = await x402.execute_request(
            backend=FakeBackend(),
            url="https://paid.example.com/report",
            method="POST",
            query={"topic": "solana"},
            json_body={"depth": "full"},
        )
        assert executed["paid"] is True
        assert executed["confirmed"] is True
        assert executed["payment_settlement"]["transaction"] == "solana-payment-tx"
        assert executed["response_preview"]["result"] == "paid"

        free_preview = await x402.preview_request(
            backend=FakeBackend(),
            url="https://free.example.com/report",
            method="GET",
        )
        assert free_preview["payment_required"] is False
        assert free_preview["response_preview"]["ok"] is True
    finally:
        x402.get_client = original_get_client
        x402._create_payment_headers = original_create_payment_headers
        x402._extract_settlement_header = original_extract_settlement_header

    print("smoke_x402_provider: ok")


if __name__ == "__main__":
    asyncio.run(main())
