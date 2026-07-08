"""Smoke coverage for x402 discovery and preview helpers."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.exceptions import ProviderError
from agent_wallet.providers import x402
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletCapabilities


class FakeBackend(AgentWalletBackend):
    name = "fake_wallet"
    chain = "solana"
    network = "mainnet"
    signer = object()
    rpc_url = "gateway::auto::mainnet::https://agent-layer.example.com/v1/rpc"
    rpc_urls = [rpc_url]

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


class FakeEvmBackend(AgentWalletBackend):
    name = "fake_evm_wallet"
    chain = "evm"
    network = "ethereum"

    async def get_address(self) -> str | None:
        return "0x1111111111111111111111111111111111111111"

    async def get_balance(self, address: str | None = None) -> dict[str, object]:
        return {"address": address or "0x1111111111111111111111111111111111111111"}

    def sign_x402_evm_exact_typed_data(
        self,
        *,
        domain: dict[str, object],
        types: dict[str, object],
        primary_type: str,
        message: dict[str, object],
    ) -> bytes:
        assert domain["chainId"] == 1
        assert primary_type == "TransferWithAuthorization"
        assert message["from"] == "0x1111111111111111111111111111111111111111"
        return bytes.fromhex("33" * 65)

    def get_capabilities(self) -> WalletCapabilities:
        return WalletCapabilities(
            backend=self.name,
            chain=self.chain,
            custody_model="local_service_vault",
            sign_only=False,
            has_signer=True,
            can_sign_transaction=False,
            can_send_transaction=False,
        )


class MainnetFakeEvmBackend(FakeEvmBackend):
    network = "base"

    def sign_x402_evm_exact_typed_data(
        self,
        *,
        domain: dict[str, object],
        types: dict[str, object],
        primary_type: str,
        message: dict[str, object],
    ) -> bytes:
        assert domain["chainId"] == 8453
        assert primary_type == "TransferWithAuthorization"
        assert message["from"] == "0x1111111111111111111111111111111111111111"
        return bytes.fromhex("44" * 65)


class SiwxFakeEvmBackend(MainnetFakeEvmBackend):
    last_message: str | None = None

    async def sign_message(self, message: bytes | str) -> str:
        SiwxFakeEvmBackend.last_message = message if isinstance(message, str) else message.decode("utf-8")
        return "0x" + "77" * 65


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


class FakeSdkPaymentRequirement:
    def __init__(self, raw: dict[str, object]):
        self.scheme = str(raw["scheme"])
        self.network = str(raw["network"])
        self.asset = str(raw["asset"])
        self.amount = str(raw["amount"])
        self.pay_to = str(raw["payTo"])
        self.max_timeout_seconds = int(raw["maxTimeoutSeconds"])
        self.extra = dict(raw.get("extra") or {})
        self._raw = dict(raw)

    def model_dump(self, *, by_alias: bool = False, exclude_none: bool = False):
        if by_alias:
            return dict(self._raw)
        return {
            "scheme": self.scheme,
            "network": self.network,
            "asset": self.asset,
            "amount": self.amount,
            "pay_to": self.pay_to,
            "max_timeout_seconds": self.max_timeout_seconds,
            "extra": dict(self.extra),
        }

    def model_copy(self, *, update=None, deep: bool = False):
        clone = FakeSdkPaymentRequirement(self._raw)
        if update:
            for key, value in update.items():
                setattr(clone, key, value)
        return clone


class FakeSdkPaymentRequired:
    def __init__(self, requirements: "FakeSdkPaymentRequirement | list[FakeSdkPaymentRequirement]"):
        self.x402_version = 2
        self.accepts = requirements if isinstance(requirements, list) else [requirements]

    def model_copy(self, *, update=None, deep: bool = False):
        copied = FakeSdkPaymentRequired(list(self.accepts))
        if isinstance(update, dict) and "accepts" in update:
            copied.accepts = list(update["accepts"])
        return copied


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    async def get(self, url: str, *, params=None):
        self.calls.append(("GET", url, params))
        if "api.cdp.coinbase.com" in url and isinstance(params, dict):
            # CDP rejects blank query parameters with HTTP 400; unset filters
            # must be omitted from the request entirely.
            for name, value in params.items():
                assert value is not None and str(value) != "", (
                    f"CDP Bazaar request must not send empty param {name!r}"
                )
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
                                    "network": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
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
                                    "network": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
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

    async def request(self, method: str, url: str, *, headers=None, json=None, content=None, timeout=None):
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
                                "network": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
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
        if url == "https://paid-base.example.com/report?topic=base":
            if headers and headers.get("PAYMENT-SIGNATURE") == "signed-evm-payload":
                return FakeResponse(
                    200,
                    {"ok": True, "result": "paid-evm"},
                    headers={"PAYMENT-RESPONSE": "settled-evm"},
                )
            encoded = base64.b64encode(
                json_module.dumps(
                    {
                        "x402Version": 2,
                        "accepts": [
                            {
                                "scheme": "exact",
                                "network": "eip155:8453",
                                "asset": "0x833589fCD6EDb6E08f4c7C32D4f71b54bdA02913",
                                "amount": "100000",
                                "payTo": "0x9999999999999999999999999999999999999999",
                                "maxTimeoutSeconds": 60,
                                "extra": {
                                    "name": "USD Coin",
                                    "version": "2",
                                    "assetTransferMethod": "eip3009",
                                },
                            }
                        ],
                    }
                ).encode("utf-8")
            ).decode("ascii")
            return FakeResponse(402, {"error": "payment required"}, headers={"PAYMENT-REQUIRED": encoded})
        if url == "https://paid-base-mainnet.example.com/report?topic=base":
            if headers and headers.get("PAYMENT-SIGNATURE") == "signed-evm-mainnet-payload":
                return FakeResponse(
                    200,
                    {"ok": True, "result": "paid-evm-mainnet"},
                    headers={"PAYMENT-RESPONSE": "settled-evm-mainnet"},
                )
            encoded = base64.b64encode(
                json_module.dumps(
                    {
                        "x402Version": 2,
                        "accepts": [
                            {
                                "scheme": "exact",
                                "network": "eip155:8453",
                                "asset": "0x833589fCD6EDb6E08f4c7C32D4f71b54bdA02913",
                                "amount": "250000",
                                "payTo": "0x9999999999999999999999999999999999999999",
                                "maxTimeoutSeconds": 60,
                                "extra": {
                                    "name": "USD Coin",
                                    "version": "2",
                                    "assetTransferMethod": "eip3009",
                                },
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
    original_load_x402_solana_sdk = x402._load_x402_solana_sdk
    original_build_solana_sdk_signer = x402._build_solana_sdk_signer
    original_load_x402_evm_sdk = x402._load_x402_evm_sdk
    fake_client = FakeClient()
    try:
        raw_requirement = {
            "scheme": "exact",
            "network": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
            "asset": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount": "100000",
            "payTo": "Merchant11111111111111111111111111111111111",
            "maxTimeoutSeconds": 60,
            "extra": {"name": "USDC"},
        }

        class FakeSdkClient:
            async def create_payment_payload(self, payment_required, resource=None, extensions=None):
                assert payment_required.accepts[0].network == raw_requirement["network"]
                return {"payload": "signed"}

        class FakeSdkHttpBase:
            def encode_payment_signature_header(self, payment_payload):
                assert payment_payload == {"payload": "signed"}
                return {"PAYMENT-SIGNATURE": "signed-sdk-payload"}

        def fake_decode_payment_required_header(_header_value: str):
            return FakeSdkPaymentRequired(FakeSdkPaymentRequirement(raw_requirement))

        def fake_register_exact_svm_client(client, signer, networks, rpc_url=None):
            assert networks == raw_requirement["network"]
            assert signer is not None
            assert rpc_url == "https://api.mainnet-beta.solana.com"

        x402._load_x402_solana_sdk = lambda: {
            "decode_payment_required_header": fake_decode_payment_required_header,
            "x402Client": FakeSdkClient,
            "x402HTTPClientBase": FakeSdkHttpBase,
            "register_exact_svm_client": fake_register_exact_svm_client,
        }
        x402._build_solana_sdk_signer = lambda backend: object()
        headers = await x402._create_payment_headers(
            backend=FakeBackend(),
            payment_required_header="dummy-header",
            selected_payment={
                "scheme": "exact",
                "network": raw_requirement["network"],
                "asset": raw_requirement["asset"],
                "amount": raw_requirement["amount"],
                "pay_to": raw_requirement["payTo"],
                "raw": dict(raw_requirement),
            },
        )
        assert headers["PAYMENT-SIGNATURE"] == "signed-sdk-payload"

        x402._load_x402_solana_sdk = original_load_x402_solana_sdk
        x402._build_solana_sdk_signer = original_build_solana_sdk_signer
        x402.get_client = lambda: fake_client
        async def fake_create_payment_headers(*, backend, payment_required_header, selected_payment):
            assert payment_required_header
            assert selected_payment["scheme"] == "exact"
            if getattr(backend, "chain", "") == "evm":
                if getattr(backend, "network", "") == "base":
                    assert selected_payment["network"] == "eip155:8453"
                    return {"PAYMENT-SIGNATURE": "signed-evm-mainnet-payload"}
                assert selected_payment["network"] == "eip155:1"
                return {"PAYMENT-SIGNATURE": "signed-evm-payload"}
            return {"PAYMENT-SIGNATURE": "signed-payload"}

        x402._create_payment_headers = fake_create_payment_headers
        def fake_extract_settlement_header(response):
            marker = response.headers.get("PAYMENT-RESPONSE")
            if marker == "settled-evm-mainnet":
                return {
                    "success": True,
                    "transaction": "evm-mainnet-payment-tx",
                    "network": "eip155:8453",
                    "payer": "0x1111111111111111111111111111111111111111",
                    "amount": "250000",
                }
            if marker == "settled-evm":
                return {
                    "success": True,
                    "transaction": "evm-payment-tx",
                    "network": "eip155:1",
                    "payer": "0x1111111111111111111111111111111111111111",
                    "amount": "100000",
                }
            return {
                "success": True,
                "transaction": "solana-payment-tx",
                "network": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
                "payer": "Fake11111111111111111111111111111111111111111",
                "amount": "100000",
            }

        x402._extract_settlement_header = fake_extract_settlement_header

        x402._discovery_cache.clear()
        cdp = await x402.search_services(query="premium report", discovery_provider="cdp_bazaar")
        assert cdp["count"] == 1
        assert cdp["items"][0]["resource"] == "https://paid.example.com/report"
        assert cdp["items"][0]["accepts"][0]["amount_display"] == "0.1"

        calls_before_cached_search = len(fake_client.calls)
        cdp_cached = await x402.search_services(
            query="premium report", discovery_provider="cdp_bazaar"
        )
        assert cdp_cached == cdp
        assert len(fake_client.calls) == calls_before_cached_search, (
            "repeated discovery search must be served from cache without an API call"
        )
        cdp_cached["items"].clear()
        cdp_fresh_copy = await x402.search_services(
            query="premium report", discovery_provider="cdp_bazaar"
        )
        assert cdp_fresh_copy["count"] == 1 and cdp_fresh_copy["items"], (
            "cache hits must hand out independent copies"
        )

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
        assert preview["selected_payment"]["network"] == "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
        assert preview["wallet"]["wallet_type_supported"] is True
        assert preview["accepted_payments"][0]["compatibility"]["wallet_network_matches"] is True
        assert preview["accepted_payments"][0]["compatibility"]["currently_executable"] is True
        assert preview["execute_available"] is True
        assert preview["request"]["body_hash"]
        assert preview["request"]["request_fingerprint"]

        executed = await x402.pay_and_fetch(
            backend=FakeBackend(),
            url="https://paid.example.com/report",
            method="POST",
            query={"topic": "solana"},
            json_body={"depth": "full"},
        )
        assert executed["mode"] == "execute"
        assert executed["paid"] is True
        assert executed["confirmed"] is True
        assert executed["reused_approved_preview"] is False
        assert executed["payment_settlement"]["transaction"] == "solana-payment-tx"
        assert executed["response_preview"]["result"] == "paid"

        paid = await x402.pay_and_fetch(
            backend=FakeBackend(),
            url="https://paid.example.com/report",
            method="POST",
            query={"topic": "solana"},
            json_body={"depth": "full"},
        )
        assert paid["paid"] is True
        assert paid["payment_settlement"]["transaction"] == "solana-payment-tx"

        evm_preview = await x402.preview_request(
            backend=FakeEvmBackend(),
            url="https://paid-base.example.com/report",
            method="POST",
            query={"topic": "base"},
            json_body={"depth": "full"},
        )
        assert evm_preview["payment_required"] is True
        assert evm_preview["selected_payment"]["network"] == "eip155:8453"
        assert evm_preview["accepted_payments"][0]["compatibility"]["wallet_network_matches"] is False
        assert evm_preview["accepted_payments"][0]["compatibility"]["currently_executable"] is False
        assert evm_preview["wallet"]["execution_modes"] == []

        evm_mainnet_preview = await x402.preview_request(
            backend=MainnetFakeEvmBackend(),
            url="https://paid-base-mainnet.example.com/report",
            method="POST",
            query={"topic": "base"},
            json_body={"depth": "full"},
        )
        assert evm_mainnet_preview["payment_required"] is True
        assert evm_mainnet_preview["selected_payment"]["network"] == "eip155:8453"
        assert evm_mainnet_preview["accepted_payments"][0]["compatibility"]["currently_executable"] is True
        assert evm_mainnet_preview["wallet"]["execution_modes"] == ["evm_exact"]

        evm_mainnet_executed = await x402.pay_and_fetch(
            backend=MainnetFakeEvmBackend(),
            url="https://paid-base-mainnet.example.com/report",
            method="POST",
            query={"topic": "base"},
            json_body={"depth": "full"},
        )
        assert evm_mainnet_executed["paid"] is True
        assert evm_mainnet_executed["confirmed"] is True
        assert evm_mainnet_executed["payment_settlement"]["transaction"] == "evm-mainnet-payment-tx"
        assert evm_mainnet_executed["response_preview"]["result"] == "paid-evm-mainnet"

        # Reusing the approval-time preview must skip the unpaid 402 probe:
        # exactly one HTTP call (the paid request) instead of two.
        reuse_preview = await x402.preview_request(
            backend=MainnetFakeEvmBackend(),
            url="https://paid-base-mainnet.example.com/report",
            method="POST",
            query={"topic": "base"},
            json_body={"depth": "full"},
        )
        calls_before_reuse = len(fake_client.calls)
        reused = await x402.pay_and_fetch(
            backend=MainnetFakeEvmBackend(),
            url="https://paid-base-mainnet.example.com/report",
            method="POST",
            query={"topic": "base"},
            json_body={"depth": "full"},
            approved_preview=reuse_preview,
        )
        assert reused["paid"] is True
        assert reused["reused_approved_preview"] is True
        assert reused["payment_settlement"]["transaction"] == "evm-mainnet-payment-tx"
        assert len(fake_client.calls) == calls_before_reuse + 1, (
            "approved preview reuse must skip the unpaid probe"
        )

        # A preview for a different request body (fingerprint mismatch) must be
        # ignored: fresh probe + paid call.
        calls_before_mismatch = len(fake_client.calls)
        mismatched = await x402.pay_and_fetch(
            backend=MainnetFakeEvmBackend(),
            url="https://paid-base-mainnet.example.com/report",
            method="POST",
            query={"topic": "base"},
            json_body={"depth": "shallow"},
            approved_preview=reuse_preview,
        )
        assert mismatched["paid"] is True
        assert mismatched["reused_approved_preview"] is False
        assert len(fake_client.calls) == calls_before_mismatch + 2, (
            "fingerprint mismatch must fall back to a fresh probe"
        )

        free_preview = await x402.preview_request(
            backend=FakeBackend(),
            url="https://free.example.com/report",
            method="GET",
        )
        assert free_preview["payment_required"] is False
        assert free_preview["response_preview"]["ok"] is True

        free_paid = await x402.pay_and_fetch(
            backend=FakeBackend(),
            url="https://free.example.com/report",
            method="GET",
        )
        assert free_paid["payment_required"] is False
        assert free_paid["paid"] is False

        try:
            x402._validate_request_execution_policy(
                request=x402._build_request_metadata(
                    url="https://x402.alchemy.com/data/v1/assets/tokens/by-address",
                    method="POST",
                    json_body={"addresses": []},
                ),
                backend=FakeBackend(),
            )
            raise AssertionError("Alchemy x402 gateway should be rejected without auth headers.")
        except ProviderError as exc:
            assert exc.provider == "x402-validate"
            assert "wallet-auth headers" in str(exc)

        # --- upto scheme: prefer upto over exact, fall back when incomplete ---
        x402._create_payment_headers = original_create_payment_headers
        exact_base_requirement = {
            "scheme": "exact",
            "network": "eip155:8453",
            "asset": "0x833589fCD6EDb6E08f4c7C32D4f71b54bdA02913",
            "amount": "500000",
            "payTo": "0x9999999999999999999999999999999999999999",
            "maxTimeoutSeconds": 60,
            "extra": {"name": "USD Coin", "version": "2", "assetTransferMethod": "eip3009"},
        }
        upto_base_requirement = {
            "scheme": "upto",
            "network": "eip155:8453",
            "asset": "0x833589fCD6EDb6E08f4c7C32D4f71b54bdA02913",
            "amount": "500000",
            "payTo": "0x9999999999999999999999999999999999999999",
            "maxTimeoutSeconds": 999_999_999,
            "extra": {
                "name": "USD Coin",
                "version": "2",
                "facilitatorAddress": "0x8888888888888888888888888888888888888888",
            },
        }

        mainnet_evm_backend = MainnetFakeEvmBackend()
        both_offered = [
            x402.normalize_payment_requirement(exact_base_requirement, source="payment_required"),
            x402.normalize_payment_requirement(upto_base_requirement, source="payment_required"),
        ]
        preferred = x402._select_preferred_requirement(both_offered, mainnet_evm_backend)
        assert preferred is not None and preferred["scheme"] == "upto", (
            "upto must be preferred over exact when a merchant offers both"
        )

        upto_missing_facilitator = dict(upto_base_requirement)
        upto_missing_facilitator["extra"] = {"name": "USD Coin", "version": "2"}
        fallback_offered = [
            x402.normalize_payment_requirement(exact_base_requirement, source="payment_required"),
            x402.normalize_payment_requirement(upto_missing_facilitator, source="payment_required"),
        ]
        fallback = x402._select_preferred_requirement(fallback_offered, mainnet_evm_backend)
        assert fallback is not None and fallback["scheme"] == "exact", (
            "upto without facilitatorAddress must fall back to exact rather than crash at sign time"
        )

        # x402_validate_payment_requirement must accept upto (previously exact-only)
        validated = x402._validate_payment_requirement(
            preferred, backend=mainnet_evm_backend, request_url="https://paid-base-mainnet.example.com/report"
        )
        assert validated["scheme"] == "upto"

        # _create_payment_headers must register both schemes and cap the upto deadline
        class RegisteringFakeEvmSdkClient:
            def __init__(self) -> None:
                self.registrations: list[tuple[str, str]] = []

            def register(self, network, scheme):
                self.registrations.append((network, scheme.scheme))
                return self

            async def create_payment_payload(self, payment_required, resource=None, extensions=None):
                assert len(payment_required.accepts) == 1
                selected = payment_required.accepts[0]
                assert selected.scheme == "upto"
                assert selected.max_timeout_seconds == x402.MAX_UPTO_DEADLINE_SECONDS, (
                    "upto deadline must be capped before signing"
                )
                return {"payload": "signed-upto"}

        class FakeUptoSchemeStub:
            def __init__(self, signer):
                self.scheme = "upto"
                self.signer = signer

        class FakeHttpBaseStub:
            def encode_payment_signature_header(self, payment_payload):
                assert payment_payload == {"payload": "signed-upto"}
                return {"PAYMENT-SIGNATURE": "signed-upto-payload"}

        def fake_register_exact_evm_client(client, signer, networks=None, policies=None):
            client.register(networks, type("ExactSchemeStub", (), {"scheme": "exact"})())
            return client

        def fake_decode_payment_required_header_evm(_header_value: str):
            return FakeSdkPaymentRequired(
                [
                    FakeSdkPaymentRequirement(exact_base_requirement),
                    FakeSdkPaymentRequirement(upto_base_requirement),
                ]
            )

        evm_client_holder: dict[str, RegisteringFakeEvmSdkClient] = {}

        def make_fake_evm_client() -> RegisteringFakeEvmSdkClient:
            client = RegisteringFakeEvmSdkClient()
            evm_client_holder["client"] = client
            return client

        x402._load_x402_evm_sdk = lambda: {
            "decode_payment_required_header": fake_decode_payment_required_header_evm,
            "x402Client": make_fake_evm_client,
            "x402HTTPClientBase": FakeHttpBaseStub,
            "register_exact_evm_client": fake_register_exact_evm_client,
            "UptoEvmScheme": FakeUptoSchemeStub,
        }

        upto_headers = await x402._create_payment_headers(
            backend=mainnet_evm_backend,
            payment_required_header="dummy-header-upto",
            selected_payment=preferred,
        )
        assert upto_headers["PAYMENT-SIGNATURE"] == "signed-upto-payload"
        registered = evm_client_holder["client"].registrations
        assert ("eip155:8453", "exact") in registered
        assert ("eip155:8453", "upto") in registered
        x402._load_x402_evm_sdk = original_load_x402_evm_sdk

        # --- SIWx: EVM signer reaches sign_message via the correct call path ---
        from types import SimpleNamespace

        from x402.extensions.sign_in_with_x import parse_siwx_header

        # Real SIWx-gated servers generate a fresh nonce/issuedAt per 402
        # response (see x402.extensions.sign_in_with_x.server); mirror that
        # shape rather than the bare declare_siwx_extension() static template.
        siwx_extensions = {
            "sign-in-with-x": {
                "info": {
                    "domain": "paid-base-mainnet.example.com",
                    "uri": "https://paid-base-mainnet.example.com/report",
                    "version": "1",
                    "nonce": "testnonce1234567890abcdef",
                    "issuedAt": "2026-07-08T00:00:00Z",
                    "resources": ["https://paid-base-mainnet.example.com/report"],
                },
                "supportedChains": [{"chainId": "eip155:8453", "type": "eip191"}],
            }
        }
        siwx_payment_required = SimpleNamespace(extensions=siwx_extensions)
        siwx_backend = SiwxFakeEvmBackend()
        siwx_evm_signer = x402._build_evm_sdk_signer(
            siwx_backend, "0x1111111111111111111111111111111111111111"
        )
        siwx_headers = await x402._maybe_attach_siwx_header(
            payment_required=siwx_payment_required,
            signer=siwx_evm_signer,
            headers={"PAYMENT-SIGNATURE": "existing-payment-signature"},
        )
        assert siwx_headers["PAYMENT-SIGNATURE"] == "existing-payment-signature"
        assert "sign-in-with-x" in siwx_headers
        assert SiwxFakeEvmBackend.last_message is not None, (
            "the SDK must reach our keyword-based sign_message(message=..., account=...), "
            "not the eth_account positional fallback -- see _NoEthAccountSentinel"
        )
        assert "paid-base-mainnet.example.com" in SiwxFakeEvmBackend.last_message
        decoded_siwx = parse_siwx_header(siwx_headers["sign-in-with-x"])
        assert decoded_siwx.address == "0x1111111111111111111111111111111111111111"
        assert decoded_siwx.domain == "paid-base-mainnet.example.com"
        assert decoded_siwx.signature == "0x" + "77" * 65

        # A merchant declaring no SIWx extension must leave headers untouched.
        plain_payment_required = SimpleNamespace(extensions=None)
        plain_headers = await x402._maybe_attach_siwx_header(
            payment_required=plain_payment_required,
            signer=siwx_evm_signer,
            headers={"PAYMENT-SIGNATURE": "unchanged"},
        )
        assert plain_headers == {"PAYMENT-SIGNATURE": "unchanged"}

        # --- SIWx: Solana signer needs no new wiring, .keypair is enough ---
        from solders.keypair import Keypair

        class SolanaSiwxSigner:
            def __init__(self) -> None:
                self._keypair = Keypair()
                self.address = str(self._keypair.pubkey())

            def export_keypair_bytes(self) -> bytes:
                return bytes(self._keypair)

        class SolanaSiwxBackend(FakeBackend):
            signer = SolanaSiwxSigner()

            async def get_address(self) -> str | None:
                return self.signer.address

        solana_siwx_backend = SolanaSiwxBackend()
        solana_siwx_signer = x402._build_solana_sdk_signer(solana_siwx_backend)
        solana_siwx_payment_required = SimpleNamespace(
            extensions={
                "sign-in-with-x": {
                    "info": {
                        "domain": "paid.example.com",
                        "uri": "https://paid.example.com/report",
                        "version": "1",
                        "nonce": "testnonce1234567890abcdef",
                        "issuedAt": "2026-07-08T00:00:00Z",
                        "resources": ["https://paid.example.com/report"],
                    },
                    "supportedChains": [
                        {"chainId": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp", "type": "ed25519"}
                    ],
                }
            }
        )
        solana_siwx_headers = await x402._maybe_attach_siwx_header(
            payment_required=solana_siwx_payment_required,
            signer=solana_siwx_signer,
            headers={"PAYMENT-SIGNATURE": "solana-payment-signature"},
        )
        assert solana_siwx_headers["PAYMENT-SIGNATURE"] == "solana-payment-signature"
        decoded_solana_siwx = parse_siwx_header(solana_siwx_headers["sign-in-with-x"])
        assert decoded_solana_siwx.address == solana_siwx_backend.signer.address
        assert decoded_solana_siwx.chain_id == "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
    finally:
        x402.get_client = original_get_client
        x402._create_payment_headers = original_create_payment_headers
        x402._extract_settlement_header = original_extract_settlement_header
        x402._load_x402_solana_sdk = original_load_x402_solana_sdk
        x402._build_solana_sdk_signer = original_build_solana_sdk_signer
        x402._load_x402_evm_sdk = original_load_x402_evm_sdk

    print("smoke_x402_provider: ok")


if __name__ == "__main__":
    asyncio.run(main())
