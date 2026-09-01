"""Smoke tests for the send-response builders in wallet_layer/wdk_evm.py.

Every send builder reshapes the daemon's JSON through an explicit field
allow-list, so a field the daemon reports is invisible to the agent unless the
builder names it. These tests pin the four fields this branch added --
`confirmed`, `confirmation_status`, `tx_hash`, `duplicate_warning` -- for both
nesting levels the daemon uses: top-level (native/token transfer) and inside
`result` (the buffered-defi family: Aave/Morpho/Lido/swaps).

`tx_hash` was the residual gap from the final whole-branch review: the daemon
always emits it at the top level of every send response, but every builder
was still silent on it (they only forwarded the hash nested inside `result`,
under the key `hash`, not `tx_hash`) -- so the `next_step` hint that quotes
`data.get("tx_hash")` printed "Transaction None was submitted...". These
tests assert `tx_hash` reaches the top level of the agent-facing response
directly, not just nested inside `result`.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.wallet_layer.wdk_evm import WdkEvmLocalWalletBackend  # noqa: E402

ADDRESS = "0x1111111111111111111111111111111111111111"
RECIPIENT = "0x2222222222222222222222222222222222222222"
TOKEN = "0x3333333333333333333333333333333333333333"
VAULT = "0x4444444444444444444444444444444444444444"
DUPLICATE = {
    "tx_hash": "0x" + "a" * 64,
    "status": "submitted",
    "broadcast_at": "2026-08-31T10:00:00.000Z",
}


class _StubClient:
    """Stands in for WdkEvmLocalClient, returning one canned daemon payload."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((path, body))
        return self.payload


def _backend(payload: dict[str, Any]) -> WdkEvmLocalWalletBackend:
    backend = WdkEvmLocalWalletBackend(
        service_url="http://127.0.0.1:1",
        wallet_id="test-wallet",
        network="base",
        address=ADDRESS,
    )
    backend.client = _StubClient(payload)
    return backend


def _check_native_transfer() -> None:
    backend = _backend(
        {
            "network": "base",
            "chainId": 8453,
            "result": {"hash": "0x" + "b" * 64, "fee": "21000000000000"},
            "tx_hash": "0x" + "b" * 64,
            "confirmed": True,
            "confirmation_status": "confirmed",
            "duplicate_warning": DUPLICATE,
        }
    )
    sent = asyncio.run(
        backend.send_evm_native_transfer(recipient=RECIPIENT, amount_wei="1000000000000000")
    )
    assert sent["confirmed"] is True, "native transfer must report the daemon's confirmed flag"
    assert sent["confirmation_status"] == "confirmed"
    assert sent["tx_hash"] == "0x" + "b" * 64, "native transfer must forward the daemon's top-level tx_hash"
    assert sent["duplicate_warning"] == DUPLICATE

    unconfirmed = _backend(
        {
            "network": "base",
            "chainId": 8453,
            "result": {"hash": "0x" + "b" * 64},
            "tx_hash": "0x" + "b" * 64,
            "confirmed": False,
            "confirmation_status": "submitted",
        }
    )
    pending = asyncio.run(
        unconfirmed.send_evm_native_transfer(recipient=RECIPIENT, amount_wei="1")
    )
    assert pending["confirmed"] is False
    assert pending["confirmation_status"] == "submitted"
    assert pending["tx_hash"] == "0x" + "b" * 64, (
        "an unconfirmed native transfer must still surface a usable tx_hash "
        "-- this is what the next_step hint quotes"
    )
    assert pending["duplicate_warning"] is None


def _check_token_transfer() -> None:
    backend = _backend(
        {
            "network": "base",
            "chainId": 8453,
            "result": {"hash": "0x" + "c" * 64, "fee": "45000000000000"},
            "tx_hash": "0x" + "c" * 64,
            "tokenMetadata": {"address": TOKEN, "symbol": "USDC", "decimals": 6},
            "amountFormatted": "5",
            "confirmed": True,
            "confirmation_status": "confirmed",
            "duplicate_warning": DUPLICATE,
        }
    )
    sent = asyncio.run(
        backend.send_evm_token_transfer(
            token_address=TOKEN,
            recipient=RECIPIENT,
            amount_raw="5000000",
        )
    )
    assert sent["confirmed"] is True, "token transfer must report the daemon's confirmed flag"
    assert sent["confirmation_status"] == "confirmed"
    assert sent["tx_hash"] == "0x" + "c" * 64, "token transfer must forward the daemon's top-level tx_hash"
    assert sent["duplicate_warning"] == DUPLICATE


def _check_morpho_vault_operation() -> None:
    # The buffered-defi family nests duplicate_warning inside `result`, which
    # the builder already forwards wholesale -- assert it survives the reshape.
    backend = _backend(
        {
            "network": "base",
            "chainId": 8453,
            "address": ADDRESS,
            "protocol": "morpho",
            "surface": "vault",
            "operation": "withdraw",
            "target": {"type": "vault", "address": VAULT},
            "operationRequest": {"token": TOKEN, "amount": "5000000"},
            "result": {"hash": "0x" + "d" * 64, "duplicate_warning": DUPLICATE},
            "tx_hash": "0x" + "d" * 64,
            "confirmed": False,
            "confirmation_status": "submitted",
        }
    )
    sent = asyncio.run(
        backend.send_evm_morpho_vault_operation(
            operation="withdraw",
            token_address=TOKEN,
            vault_address=VAULT,
            amount_raw="5000000",
        )
    )
    assert sent["confirmed"] is False
    assert sent["confirmation_status"] == "submitted"
    assert sent["tx_hash"] == "0x" + "d" * 64, (
        "the incident operation must surface a usable tx_hash even when unconfirmed"
    )
    assert sent["result"]["duplicate_warning"] == DUPLICATE


def main() -> None:
    _check_native_transfer()
    _check_token_transfer()
    _check_morpho_vault_operation()
    print("smoke_wdk_evm_send_confirmation_fields: ok")


if __name__ == "__main__":
    main()
