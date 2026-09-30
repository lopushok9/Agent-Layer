"""Smoke coverage: every request to laso.finance carries the X-Laso-Partner header,
including the paid retry after the initial HTTP 402, and no other host gets it."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.providers import x402
from smoke_x402_provider import FakeBackend

PARTNER_VALUE = "zyMjC5KIn9fKaypAz2VR"
REQUIREMENT = {
    "scheme": "exact",
    "network": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
    "asset": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "amount": "5000000",
    "payTo": "Merchant11111111111111111111111111111111111",
    "maxTimeoutSeconds": 60,
    "extra": {"name": "USDC"},
}


class Response:
    def __init__(self, status_code: int, headers: dict[str, str], body: dict) -> None:
        self.status_code = status_code
        self.headers = headers
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def request(self, method, url, *, headers=None, json=None, content=None, timeout=None):
        self.calls.append((url, dict(headers or {})))
        if "PAYMENT-SIGNATURE" in (headers or {}):
            return Response(200, {"content-type": "application/json"}, {"card_id": "c1"})
        payment_required = base64.b64encode(
            _json({"x402Version": 2, "accepts": [REQUIREMENT]}).encode()
        ).decode()
        return Response(402, {"PAYMENT-REQUIRED": payment_required}, {})


def _json(value) -> str:
    return json.dumps(value)


async def main() -> None:
    original_get_client = x402.get_client
    original_create_payment_headers = x402._create_payment_headers
    original_extract = x402._extract_settlement_header_safe
    client = RecordingClient()
    try:
        x402.get_client = lambda: client

        async def fake_create_payment_headers(**_kwargs):
            return {"PAYMENT-SIGNATURE": "signed"}

        x402._create_payment_headers = fake_create_payment_headers
        x402._extract_settlement_header_safe = lambda response: None

        result = await x402.pay_and_fetch(
            backend=FakeBackend(),
            url="https://laso.finance/get-card",
            query={"amount": 5, "format": "json"},
            headers={"Authorization": "Bearer t"},
        )
        assert result["paid"] is True
        assert len(client.calls) == 2, client.calls
        probe_headers, paid_headers = client.calls[0][1], client.calls[1][1]
        for sent in (probe_headers, paid_headers):
            assert sent["X-Laso-Partner"] == PARTNER_VALUE
            assert sent["Authorization"] == "Bearer t"
        assert paid_headers["PAYMENT-SIGNATURE"] == "signed"

        client.calls.clear()
        await x402.preview_request(backend=FakeBackend(), url="https://paid.example.com/report")
        assert "X-Laso-Partner" not in client.calls[0][1]

        client.calls.clear()
        await x402.preview_request(backend=FakeBackend(), url="https://notlaso.finance/x")
        assert "X-Laso-Partner" not in client.calls[0][1]
    finally:
        x402.get_client = original_get_client
        x402._create_payment_headers = original_create_payment_headers
        x402._extract_settlement_header_safe = original_extract

    print("smoke_x402_laso_partner_header: ok")


if __name__ == "__main__":
    asyncio.run(main())
