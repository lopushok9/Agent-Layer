"""Verified connector EVM intents fail closed before simulation or signing."""

from __future__ import annotations

import copy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.connectors.intent_policy import (  # noqa: E402
    ConnectorIntentPolicyError,
    validate_evm_transaction_intent,
)


WALLET = "0x" + "1" * 40
POOL = "0x" + "2" * 40
TOKEN = "0x" + "3" * 40


def _manifest() -> dict:
    return {
        "schema_version": 1,
        "id": "com.example.lending",
        "name": "Example Lending",
        "version": "1.0.0",
        "artifact_digest": "sha256:" + "a" * 64,
        "publisher": {"id": "example", "name": "Example"},
        "agentlayer": {"protocol_version": 1, "runtime_range": ">=0.1.101"},
        "trust": "verified_write",
        "transport": {"type": "https", "url": "https://connector.example.com/v1"},
        "permissions": {
            "wallet_address": True,
            "transaction_intents": True,
            "network_hosts": ["api.example.com"],
        },
        "chains": [
            {
                "chain": "evm",
                "chain_ids": [8453],
                "contracts": [
                    {
                        "chain_id": 8453,
                        "address": POOL,
                        "selectors": ["0x617ba037"],
                    }
                ],
            }
        ],
        "tools": [
            {
                "name": "supply",
                "description": "Build a lending supply intent.",
                "read_only": False,
                "risk_level": "high",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
            }
        ],
    }


def _intent() -> dict:
    expiry = datetime.now(timezone.utc) + timedelta(seconds=60)
    return {
        "protocol_version": 1,
        "kind": "evm_transaction_intent",
        "connector_id": "com.example.lending",
        "connector_version": "1.0.0",
        "artifact_digest": "sha256:" + "a" * 64,
        "tool": "supply",
        "quote_fingerprint": "sha256:" + "b" * 64,
        "expires_at": expiry.isoformat(),
        "chain_id": 8453,
        "from": WALLET,
        "calls": [
            {
                "to": POOL,
                "data": "0x617ba037" + "00" * 32,
                "value_wei": "0",
            }
        ],
        "approvals": [{"token": TOKEN, "spender": POOL, "amount_raw": "1000000"}],
        "expected_effects": [
            {"type": "asset", "asset": TOKEN, "direction": "debit", "amount": "1000000"},
            {
                "type": "position",
                "asset": "example-supply-position",
                "direction": "increase",
                "amount": "1000000",
            },
        ],
    }


def _expect_invalid(intent: dict, message: str, *, manifest: dict | None = None) -> None:
    try:
        validate_evm_transaction_intent(manifest or _manifest(), intent, wallet_address=WALLET)
    except ConnectorIntentPolicyError as exc:
        assert message in str(exc), exc
    else:
        raise AssertionError(f"intent should have failed: {message}")


def main() -> None:
    summary = validate_evm_transaction_intent(_manifest(), _intent(), wallet_address=WALLET)
    assert summary["validation"]["simulated"] is False
    assert summary["calls"][0]["selector"] == "0x617ba037"
    assert summary["approvals"][0]["amount_raw"] == "1000000"

    bad = _intent()
    bad["from"] = "0x" + "4" * 40
    _expect_invalid(bad, "does not match the wallet")

    bad = _intent()
    bad["chain_id"] = 1
    _expect_invalid(bad, "not allowed on EVM chain")

    bad = _intent()
    bad["calls"][0]["to"] = "0x" + "5" * 40
    _expect_invalid(bad, "unapproved contract")

    bad = _intent()
    bad["calls"][0]["data"] = "0xdeadbeef"
    _expect_invalid(bad, "unapproved selector")

    bad = _intent()
    bad["approvals"][0]["amount_raw"] = str((1 << 256) - 1)
    _expect_invalid(bad, "Unlimited")

    bad = _intent()
    bad["calls"][0]["data"] = "0x095ea7b3" + "00" * 64
    allow_approve = copy.deepcopy(_manifest())
    allow_approve["chains"][0]["contracts"][0]["selectors"].append("0x095ea7b3")
    _expect_invalid(bad, "declare approvals separately", manifest=allow_approve)

    bad = _intent()
    bad["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    _expect_invalid(bad, "expired")

    read_manifest = copy.deepcopy(_manifest())
    read_manifest["trust"] = "verified_read_only"
    read_manifest["permissions"]["transaction_intents"] = False
    read_manifest["tools"][0]["read_only"] = True
    _expect_invalid(_intent(), "Only verified_write", manifest=read_manifest)

    print("smoke_connector_evm_intent_policy: ok")


if __name__ == "__main__":
    main()

