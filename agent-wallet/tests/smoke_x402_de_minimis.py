"""Smoke coverage for the x402 de-minimis approval exemption."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _secret_test_utils import install_test_sealed_secrets  # noqa: E402
from agent_wallet import autonomous_permissions, autonomous_session
from agent_wallet.openclaw_adapter import OpenClawWalletAdapter
from agent_wallet.providers import x402
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletCapabilities


class FakeBackend(AgentWalletBackend):
    name = "fake_wallet"
    chain = "solana"
    network = "mainnet"
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
    def __init__(self, status_code: int, payload: dict | list, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeClient:
    """Always challenges with a fixed payment amount (raw base units)."""

    def __init__(
        self,
        amount_raw: str,
        *,
        asset: str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        extra_name: str = "USDC",
    ):
        self.amount_raw = amount_raw
        self.asset = asset
        self.extra_name = extra_name

    async def get(self, url: str, *, params=None):
        raise AssertionError(f"Unexpected GET {url}")

    async def request(self, method: str, url: str, *, headers=None, json=None, content=None, timeout=None):
        encoded = base64.b64encode(
            json_module.dumps(
                {
                    "x402Version": 2,
                    "accepts": [
                        {
                            "scheme": "exact",
                            "network": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
                            "asset": self.asset,
                            "amount": self.amount_raw,
                            "payTo": "Merchant11111111111111111111111111111111111",
                            "maxTimeoutSeconds": 60,
                            "extra": {"name": self.extra_name},
                        }
                    ],
                }
            ).encode("utf-8")
        ).decode("ascii")
        return FakeResponse(402, {"error": "payment required"}, headers={"PAYMENT-REQUIRED": encoded})


json_module = json


def _fake_pay_and_fetch_factory():
    async def fake_pay_and_fetch(*, backend, url, method="GET", headers=None, query=None, json_body=None, text_body=None, approved_preview=None):
        preview = dict(approved_preview or {})
        preview.update(
            {
                "mode": "execute",
                "paid": True,
                "broadcasted": True,
                "confirmed": True,
                "payment_settlement": {"success": True, "transaction": "solana-payment-tx"},
            }
        )
        return preview

    return fake_pay_and_fetch


async def _pay(adapter: OpenClawWalletAdapter, *, approval_token: str | None = None):
    args = {"url": "https://paid.example.com/report", "purpose": "buy a paid report"}
    if approval_token:
        args["approval_token"] = approval_token
    return await adapter.invoke("x402_pay_request", args)


def _unit_tests() -> None:
    usdc_under = {"x402_amount_display": "1.99"}
    usdc_at_boundary = {"x402_amount_display": "2.00"}
    usdc_over = {"x402_amount_display": "2.01"}
    unknown_asset = {"x402_amount_display": None}

    assert x402.de_minimis_usd_amount(usdc_under) == 1.99
    assert x402.is_de_minimis_payment(usdc_under) is True
    # Exactly at the threshold is not "below" it -- still requires approval.
    assert x402.is_de_minimis_payment(usdc_at_boundary) is False
    assert x402.is_de_minimis_payment(usdc_over) is False
    # Unknown/non-USDC asset: amount_display is None, so USD value is
    # unknowable here -- never exempt, regardless of the raw amount.
    assert x402.de_minimis_usd_amount(unknown_asset) is None
    assert x402.is_de_minimis_payment(unknown_asset) is False
    # Explicit threshold override still works.
    assert x402.is_de_minimis_payment(usdc_over, threshold_usd=3.0) is True


async def main() -> None:
    _unit_tests()

    install_test_sealed_secrets(
        Path("/tmp/openclaw-x402-de-minimis-smoke"),
        boot_key="test-boot-key-for-x402-de-minimis-smoke",
        approval_secret="x402-de-minimis-smoke-secret",
    )
    autonomous_permissions.revoke_all()
    assert autonomous_session.is_active() is False

    original_get_client = x402.get_client
    original_pay_and_fetch = x402.pay_and_fetch
    try:
        # Sub-threshold (1.9 USDC): must succeed with NO approval_token, no
        # active autonomous session, and no autonomous permission grant --
        # and on a mainnet backend, to prove this is independent of the
        # mainnet-confirmation gate too.
        x402.get_client = lambda: FakeClient("1900000")
        x402.pay_and_fetch = _fake_pay_and_fetch_factory()
        adapter = OpenClawWalletAdapter(FakeBackend())

        preview = await adapter.invoke("x402_preview_request", {"url": "https://paid.example.com/report"})
        assert preview.ok is True
        assert preview.data["confirmation_requirements"]["execute_requires_approval_token"] is False
        assert preview.data["de_minimis_payment"]["applied"] is True
        assert preview.data["de_minimis_payment"]["amount_usd"] == 1.9

        paid = await _pay(adapter)
        assert paid.ok is True
        assert paid.data["paid"] is True
        assert paid.data["confirmation_requirements"]["execute_requires_approval_token"] is False
        assert paid.data["de_minimis_payment"]["applied"] is True
        assert paid.data["de_minimis_payment"]["threshold_usd"] == x402.DE_MINIMIS_USD_THRESHOLD

        # At/above the threshold (2.00 USDC exactly): back to requiring
        # approval like any other write tool.
        x402.get_client = lambda: FakeClient("2000000")
        denied_at_boundary = await _pay(adapter)
        assert denied_at_boundary.ok is False

        # Unknown/non-USDC asset, tiny raw amount: still requires approval,
        # since amount_display (and therefore USD value) is unknown.
        x402.get_client = lambda: FakeClient(
            "1",
            asset="SomeOtherToken1111111111111111111111111111",
            extra_name="SomeOtherToken",
        )
        denied_unknown_asset = await _pay(adapter)
        assert denied_unknown_asset.ok is False
    finally:
        x402.get_client = original_get_client
        x402.pay_and_fetch = original_pay_and_fetch

    print("smoke_x402_de_minimis: ok")


if __name__ == "__main__":
    asyncio.run(main())
