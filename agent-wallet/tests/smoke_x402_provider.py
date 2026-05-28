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
    network = "devnet"
    signer = object()
    rpc_url = "gateway::auto::devnet::https://agent-layer.example.com/v1/rpc"
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
    network = "base-sepolia"

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
        assert domain["chainId"] == 84532
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


class FakeSdkPaymentRequired:
    def __init__(self, requirement: FakeSdkPaymentRequirement):
        self.x402_version = 2
        self.accepts = [requirement]

    def model_copy(self, *, update=None, deep: bool = False):
        copied = FakeSdkPaymentRequired(self.accepts[0])
        if isinstance(update, dict) and "accepts" in update:
            copied.accepts = list(update["accepts"])
        return copied


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
                                "network": "eip155:84532",
                                "asset": "0x036CbD53842c5426634e7929541ec2318f3dCf7e",
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
    fake_client = FakeClient()
    try:
        raw_requirement = {
            "scheme": "exact",
            "network": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",
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
            assert rpc_url == "https://api.devnet.solana.com"

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
                assert selected_payment["network"] == "eip155:84532"
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
                    "network": "eip155:84532",
                    "payer": "0x1111111111111111111111111111111111111111",
                    "amount": "100000",
                }
            return {
                "success": True,
                "transaction": "solana-payment-tx",
                "network": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",
                "payer": "Fake11111111111111111111111111111111111111111",
                "amount": "100000",
            }

        x402._extract_settlement_header = fake_extract_settlement_header

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
        assert evm_preview["selected_payment"]["network"] == "eip155:84532"
        assert evm_preview["accepted_payments"][0]["compatibility"]["wallet_network_matches"] is True
        assert evm_preview["accepted_payments"][0]["compatibility"]["currently_executable"] is True
        assert evm_preview["wallet"]["execution_modes"] == ["evm_exact"]

        evm_prepared = await x402.prepare_request(
            backend=FakeEvmBackend(),
            url="https://paid-base.example.com/report",
            method="POST",
            query={"topic": "base"},
            json_body={"depth": "full"},
        )
        assert evm_prepared["prepared"] is True
        assert evm_prepared["x402_asset"] == "0x036CbD53842c5426634e7929541ec2318f3dCf7e"

        evm_executed = await x402.execute_request(
            backend=FakeEvmBackend(),
            url="https://paid-base.example.com/report",
            method="POST",
            query={"topic": "base"},
            json_body={"depth": "full"},
        )
        assert evm_executed["paid"] is True
        assert evm_executed["confirmed"] is True
        assert evm_executed["payment_settlement"]["transaction"] == "evm-payment-tx"
        assert evm_executed["response_preview"]["result"] == "paid-evm"

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

        evm_mainnet_executed = await x402.execute_request(
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
    finally:
        x402.get_client = original_get_client
        x402._create_payment_headers = original_create_payment_headers
        x402._extract_settlement_header = original_extract_settlement_header
        x402._load_x402_solana_sdk = original_load_x402_solana_sdk
        x402._build_solana_sdk_signer = original_build_solana_sdk_signer

    print("smoke_x402_provider: ok")


if __name__ == "__main__":
    asyncio.run(main())
