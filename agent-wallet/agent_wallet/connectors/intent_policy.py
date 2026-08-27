"""Fail-closed local policy for unsigned write-capable connector intents."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from agent_wallet.connectors.manifest import DIGEST_PATTERN, validate_connector_manifest


EVM_ADDRESS_PATTERN = re.compile(r"^0x[0-9a-fA-F]{40}$")
HEX_DATA_PATTERN = re.compile(r"^0x(?:[0-9a-fA-F]{2})*$")
UINT_PATTERN = re.compile(r"^(0|[1-9][0-9]*)$")
ERC20_APPROVE_SELECTOR = "0x095ea7b3"
MAX_UINT256 = (1 << 256) - 1
MAX_INTENT_LIFETIME_SECONDS = 300


class ConnectorIntentPolicyError(ValueError):
    """Raised when a connector write intent is unsafe or incorrectly bound."""


def _require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConnectorIntentPolicyError(f"{field} must be an object.")
    return value


def _require_uint(value: Any, field: str, *, positive: bool = False) -> int:
    if not isinstance(value, str) or not UINT_PATTERN.fullmatch(value):
        raise ConnectorIntentPolicyError(f"{field} must be an unsigned integer string.")
    number = int(value)
    if number >= 1 << 256:
        raise ConnectorIntentPolicyError(f"{field} exceeds uint256.")
    if positive and number <= 0:
        raise ConnectorIntentPolicyError(f"{field} must be greater than zero.")
    return number


def _require_address(value: Any, field: str) -> str:
    if not isinstance(value, str) or not EVM_ADDRESS_PATTERN.fullmatch(value):
        raise ConnectorIntentPolicyError(f"{field} must be an EVM address.")
    return value.lower()


def _validate_expiry(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ConnectorIntentPolicyError("expires_at is required.")
    try:
        expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConnectorIntentPolicyError("expires_at is invalid.") from exc
    if expiry.tzinfo is None:
        raise ConnectorIntentPolicyError("expires_at must include a timezone.")
    remaining = (expiry.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds()
    if remaining <= 0:
        raise ConnectorIntentPolicyError("Connector intent has expired.")
    if remaining > MAX_INTENT_LIFETIME_SECONDS:
        raise ConnectorIntentPolicyError("Connector intent expiry exceeds the allowed lifetime.")
    return value


def _evm_contract_policy(manifest: dict[str, Any], chain_id: int) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for raw_policy in manifest.get("chains") or []:
        if not isinstance(raw_policy, dict) or raw_policy.get("chain") != "evm":
            continue
        chain_ids = raw_policy.get("chain_ids")
        if not isinstance(chain_ids, list) or chain_id not in chain_ids:
            continue
        for raw_contract in raw_policy.get("contracts") or []:
            if not isinstance(raw_contract, dict) or raw_contract.get("chain_id") != chain_id:
                continue
            address = _require_address(raw_contract.get("address"), "manifest contract address")
            selectors = raw_contract.get("selectors")
            if not isinstance(selectors, list) or not selectors:
                raise ConnectorIntentPolicyError("Manifest contract selectors are missing.")
            result[address] = {str(selector).lower() for selector in selectors}
    if not result:
        raise ConnectorIntentPolicyError(f"Connector is not allowed on EVM chain {chain_id}.")
    return result


def _write_tool(manifest: dict[str, Any], tool_name: Any) -> dict[str, Any]:
    if not isinstance(tool_name, str):
        raise ConnectorIntentPolicyError("tool is required.")
    for tool in manifest["tools"]:
        if isinstance(tool, dict) and tool.get("name") == tool_name:
            if tool.get("read_only") is True:
                raise ConnectorIntentPolicyError("A read-only connector tool cannot return an intent.")
            return tool
    raise ConnectorIntentPolicyError(f"Connector write tool is not declared: {tool_name}.")


def validate_evm_transaction_intent(
    manifest_payload: dict[str, Any],
    intent_payload: dict[str, Any],
    *,
    wallet_address: str,
) -> dict[str, Any]:
    """Validate an unsigned EVM intent and return an approval-safe summary.

    This function does not simulate, sign, approve, or broadcast. Its output is
    suitable as input to the later simulation and preview binding layers.
    """

    manifest = validate_connector_manifest(manifest_payload)
    intent = _require_object(intent_payload, "intent")
    if manifest["trust"] != "verified_write":
        raise ConnectorIntentPolicyError("Only verified_write connectors may return intents.")
    if manifest["permissions"].get("transaction_intents") is not True:
        raise ConnectorIntentPolicyError("Connector is not permitted to return transaction intents.")
    if intent.get("protocol_version") != 1 or intent.get("kind") != "evm_transaction_intent":
        raise ConnectorIntentPolicyError("Unsupported EVM connector intent version or kind.")
    if intent.get("connector_id") != manifest["id"]:
        raise ConnectorIntentPolicyError("Connector intent id does not match the manifest.")
    if intent.get("connector_version") != manifest["version"]:
        raise ConnectorIntentPolicyError("Connector intent version does not match the manifest.")
    if intent.get("artifact_digest") != manifest.get("artifact_digest"):
        raise ConnectorIntentPolicyError("Connector intent artifact digest does not match.")
    quote_fingerprint = intent.get("quote_fingerprint")
    if not isinstance(quote_fingerprint, str) or not DIGEST_PATTERN.fullmatch(quote_fingerprint):
        raise ConnectorIntentPolicyError("quote_fingerprint must be a lowercase sha256 digest.")
    tool = _write_tool(manifest, intent.get("tool"))
    expires_at = _validate_expiry(intent.get("expires_at"))

    chain_id = intent.get("chain_id")
    if not isinstance(chain_id, int) or isinstance(chain_id, bool) or chain_id <= 0:
        raise ConnectorIntentPolicyError("chain_id must be a positive integer.")
    contract_policy = _evm_contract_policy(manifest, chain_id)
    expected_wallet = _require_address(wallet_address, "wallet_address")
    intent_from = _require_address(intent.get("from"), "from")
    if intent_from != expected_wallet:
        raise ConnectorIntentPolicyError("Connector intent from address does not match the wallet.")

    calls = intent.get("calls")
    if not isinstance(calls, list) or not 1 <= len(calls) <= 16:
        raise ConnectorIntentPolicyError("calls must contain between 1 and 16 entries.")
    normalized_calls: list[dict[str, Any]] = []
    for index, raw_call in enumerate(calls):
        call = _require_object(raw_call, f"calls[{index}]")
        target = _require_address(call.get("to"), f"calls[{index}].to")
        selectors = contract_policy.get(target)
        if selectors is None:
            raise ConnectorIntentPolicyError(f"calls[{index}] targets an unapproved contract.")
        data = call.get("data")
        if not isinstance(data, str) or not HEX_DATA_PATTERN.fullmatch(data) or len(data) < 10:
            raise ConnectorIntentPolicyError(f"calls[{index}].data must contain EVM calldata.")
        selector = data[:10].lower()
        if selector == ERC20_APPROVE_SELECTOR:
            raise ConnectorIntentPolicyError(
                "Connector intents must declare approvals separately from protocol calls."
            )
        if selector not in selectors:
            raise ConnectorIntentPolicyError(f"calls[{index}] uses an unapproved selector.")
        value_wei = _require_uint(call.get("value_wei"), f"calls[{index}].value_wei")
        normalized_calls.append(
            {
                "to": target,
                "selector": selector,
                "value_wei": str(value_wei),
                "calldata_bytes": (len(data) - 2) // 2,
            }
        )

    approvals = intent.get("approvals")
    if not isinstance(approvals, list) or len(approvals) > 16:
        raise ConnectorIntentPolicyError("approvals must be an array of at most 16 entries.")
    normalized_approvals: list[dict[str, str]] = []
    for index, raw_approval in enumerate(approvals):
        approval = _require_object(raw_approval, f"approvals[{index}]")
        token = _require_address(approval.get("token"), f"approvals[{index}].token")
        spender = _require_address(approval.get("spender"), f"approvals[{index}].spender")
        if spender not in contract_policy:
            raise ConnectorIntentPolicyError(f"approvals[{index}] uses an unapproved spender.")
        amount = _require_uint(
            approval.get("amount_raw"), f"approvals[{index}].amount_raw", positive=True
        )
        if amount == MAX_UINT256:
            raise ConnectorIntentPolicyError("Unlimited connector token approvals are prohibited.")
        normalized_approvals.append(
            {
                "token": token,
                "spender": spender,
                "amount_raw": str(amount),
            }
        )

    effects = intent.get("expected_effects")
    if not isinstance(effects, list) or not 1 <= len(effects) <= 64:
        raise ConnectorIntentPolicyError("expected_effects must contain between 1 and 64 entries.")
    normalized_effects: list[dict[str, Any]] = []
    for index, raw_effect in enumerate(effects):
        effect = _require_object(raw_effect, f"expected_effects[{index}]")
        effect_type = effect.get("type")
        if effect_type not in {"asset", "debt", "position", "protocol_fee", "network_fee"}:
            raise ConnectorIntentPolicyError(f"expected_effects[{index}].type is unsupported.")
        direction = effect.get("direction")
        if direction not in {"debit", "credit", "increase", "decrease"}:
            raise ConnectorIntentPolicyError(f"expected_effects[{index}].direction is unsupported.")
        asset = effect.get("asset")
        if not isinstance(asset, str) or not asset.strip() or len(asset) > 128:
            raise ConnectorIntentPolicyError(f"expected_effects[{index}].asset is invalid.")
        amount = _require_uint(effect.get("amount"), f"expected_effects[{index}].amount")
        normalized_effects.append(
            {
                "type": effect_type,
                "asset": asset.strip(),
                "direction": direction,
                "amount": str(amount),
                **(
                    {"recipient": str(effect["recipient"])}
                    if isinstance(effect.get("recipient"), str) and effect["recipient"]
                    else {}
                ),
            }
        )

    return {
        "operation": "AgentLayer connector EVM transaction",
        "connector_id": str(manifest["id"]),
        "connector_version": str(manifest["version"]),
        "artifact_digest": str(manifest["artifact_digest"]),
        "tool": str(tool["name"]),
        "chain": "evm",
        "chain_id": chain_id,
        "from": expected_wallet,
        "quote_fingerprint": quote_fingerprint,
        "expires_at": expires_at,
        "calls": normalized_calls,
        "approvals": normalized_approvals,
        "expected_effects": normalized_effects,
        "validation": {
            "verified_connector": True,
            "wallet_bound": True,
            "targets_allowlisted": True,
            "selectors_allowlisted": True,
            "approvals_bounded": True,
            "simulated": False,
        },
    }

