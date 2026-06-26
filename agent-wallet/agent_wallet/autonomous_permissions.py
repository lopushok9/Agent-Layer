"""Persistent high-trust permission toggles for unattended wallet flows.

This module is intentionally narrower than ``autonomous_session``.  It models
the "CLI permissions" UX where a user grants a standing capability, not a
budgeted policy envelope.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from agent_wallet.approval import issue_approval_token
from agent_wallet.config import resolve_openclaw_home
from agent_wallet.file_ops import atomic_write_text, chmod_if_exists
from agent_wallet.wallet_layer.base import WalletBackendError

PERMISSION_VERSION = 1
BASE_SWAP_SCOPE = "base_swaps"
BASE_SWAP_NETWORK = "base"
BASE_SWAP_TOOLS = frozenset({"swap_evm_tokens", "swap_evm_uniswap_tokens"})
BASE_SWAP_ISSUER = "autonomous-permission:base-swaps"
DEFI_TOOLS_SCOPE = "defi_tools"
DEFI_TOOLS_NETWORKS = frozenset({"base", "ethereum"})
DEFI_TOOLS = frozenset(
    {
        "manage_evm_aave_position",
        "manage_evm_lido_position",
        "manage_evm_lido_withdrawal",
        "manage_evm_morpho_market_position",
        "manage_evm_morpho_vault_position",
    }
)
DEFI_TOOLS_ISSUER = "autonomous-permission:defi-tools"
SUPPORTED_SCOPES = frozenset({BASE_SWAP_SCOPE, DEFI_TOOLS_SCOPE})
_PERMISSIONS_FILENAME = "autonomous_permissions.json"


def _permissions_path() -> Path:
    return resolve_openclaw_home() / _PERMISSIONS_FILENAME


def _now() -> int:
    return int(time.time())


def _empty_record() -> dict[str, Any]:
    return {"version": PERMISSION_VERSION, "scopes": {}}


def _load_record() -> dict[str, Any]:
    path = _permissions_path()
    if not path.exists():
        return _empty_record()
    chmod_if_exists(path)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty_record()
    if not isinstance(record, dict) or int(record.get("version") or 0) != PERMISSION_VERSION:
        return _empty_record()
    scopes = record.get("scopes")
    if not isinstance(scopes, dict):
        record["scopes"] = {}
    return record


def _write_record(record: dict[str, Any]) -> None:
    atomic_write_text(_permissions_path(), json.dumps(record, sort_keys=True, separators=(",", ":")))


def _scope_status(record: dict[str, Any], scope: str) -> dict[str, Any]:
    raw = (record.get("scopes") or {}).get(scope)
    if not isinstance(raw, dict):
        return {"scope": scope, "enabled": False}
    return {
        "scope": scope,
        "enabled": bool(raw.get("enabled")),
        "approved_at": raw.get("approved_at"),
        "approved_by": raw.get("approved_by"),
        "network": raw.get("network"),
        "networks": raw.get("networks") or ([raw.get("network")] if raw.get("network") else []),
        "tools": raw.get("tools") or [],
        "warning": raw.get("warning"),
    }


def status() -> dict[str, Any]:
    """Return current high-trust autonomous permission status."""
    record = _load_record()
    base_swaps = _scope_status(record, BASE_SWAP_SCOPE)
    defi_tools = _scope_status(record, DEFI_TOOLS_SCOPE)
    group_enabled = all(bool(scope.get("enabled")) for scope in (base_swaps, defi_tools))
    return {
        "active": group_enabled,
        "scopes": {BASE_SWAP_SCOPE: base_swaps, DEFI_TOOLS_SCOPE: defi_tools},
        "permission_file": str(_permissions_path()),
    }


def _set_base_swap_scope(scopes: dict[str, Any], *, approved_by: str) -> None:
    scopes[BASE_SWAP_SCOPE] = {
        "enabled": True,
        "approved_at": _now(),
        "approved_by": str(approved_by or "user"),
        "network": BASE_SWAP_NETWORK,
        "tools": sorted(BASE_SWAP_TOOLS),
        "warning": (
            "High-trust permission: Base swap execute calls can run without "
            "per-transaction human approval until revoked."
        ),
    }


def _set_defi_tools_scope(scopes: dict[str, Any], *, approved_by: str) -> None:
    scopes[DEFI_TOOLS_SCOPE] = {
        "enabled": True,
        "approved_at": _now(),
        "approved_by": str(approved_by or "user"),
        "networks": sorted(DEFI_TOOLS_NETWORKS),
        "tools": sorted(DEFI_TOOLS),
        "warning": (
            "High-trust permission: supported EVM DeFi execute calls can run "
            "without per-transaction human approval until revoked."
        ),
    }


def approve_all(*, approved_by: str = "user") -> dict[str, Any]:
    """Enable all high-trust autonomous permission scopes as one group."""
    record = _load_record()
    scopes = record.setdefault("scopes", {})
    normalized_approved_by = str(approved_by or "user")
    _set_base_swap_scope(scopes, approved_by=normalized_approved_by)
    _set_defi_tools_scope(scopes, approved_by=normalized_approved_by)
    _write_record(record)
    return status()


def approve_base_swaps(*, approved_by: str = "user") -> dict[str, Any]:
    """Enable all autonomous permissions; base_swaps is kept as a compatibility scope."""
    return approve_all(approved_by=approved_by)


def approve_defi_tools(*, approved_by: str = "user") -> dict[str, Any]:
    """Enable all autonomous permissions; defi_tools is kept as a compatibility scope."""
    return approve_all(approved_by=approved_by)


def revoke_base_swaps() -> dict[str, Any]:
    """Disable all autonomous permissions; base_swaps is kept as a compatibility scope."""
    return revoke_all()


def revoke_defi_tools() -> dict[str, Any]:
    """Disable all autonomous permissions; defi_tools is kept as a compatibility scope."""
    return revoke_all()


def revoke_all() -> dict[str, Any]:
    """Disable every high-trust autonomous permission scope as one group."""
    record = _load_record()
    scopes = record.setdefault("scopes", {})
    for supported_scope in sorted(SUPPORTED_SCOPES):
        existing = scopes.get(supported_scope)
        if isinstance(existing, dict):
            existing["enabled"] = False
            existing["revoked_at"] = _now()
        else:
            scopes[supported_scope] = {"enabled": False, "revoked_at": _now()}
    _write_record(record)
    return status()


def revoke_scope(scope: str) -> dict[str, Any]:
    normalized_scope = str(scope or "").strip()
    if normalized_scope not in SUPPORTED_SCOPES:
        raise WalletBackendError("Unsupported autonomous permission scope.")
    return revoke_all()


def is_base_swap_approved() -> bool:
    return bool(status()["active"])


def is_defi_tools_approved() -> bool:
    return bool(status()["active"])


def authorize_base_swap(*, tool_name: str, network: str, summary: dict[str, Any]) -> str:
    """Issue an internal approval token for one exact Base swap operation."""
    if str(tool_name) not in BASE_SWAP_TOOLS:
        raise WalletBackendError("Autonomous permission only covers Base swap tools.")
    if str(network or "").strip().lower() != BASE_SWAP_NETWORK:
        raise WalletBackendError("Autonomous Base swap permission only applies on network=base.")
    if not is_base_swap_approved():
        raise WalletBackendError(
            "Autonomous execution is not enabled. Ask the user to run "
            "agentlayer_autonomous_approve first."
        )
    summary_network = str((summary or {}).get("network") or "").strip().lower()
    if summary_network and summary_network != BASE_SWAP_NETWORK:
        raise WalletBackendError("Autonomous Base swap summary is not bound to network=base.")
    return issue_approval_token(
        tool_name=tool_name,
        network=BASE_SWAP_NETWORK,
        summary=summary,
        mainnet_confirmed=True,
        ttl_seconds=120,
        issued_by=BASE_SWAP_ISSUER,
    )


def authorize_defi_tool(*, tool_name: str, network: str, summary: dict[str, Any]) -> str:
    """Issue an internal approval token for one exact EVM DeFi operation."""
    normalized_network = str(network or "").strip().lower()
    if str(tool_name) not in DEFI_TOOLS:
        raise WalletBackendError("Autonomous DeFi permission only covers supported EVM DeFi tools.")
    if normalized_network not in DEFI_TOOLS_NETWORKS:
        raise WalletBackendError("Autonomous DeFi permission only applies on ethereum or base.")
    if not is_defi_tools_approved():
        raise WalletBackendError(
            "Autonomous execution is not enabled. Ask the user to run "
            "agentlayer_autonomous_approve first."
        )
    summary_network = str((summary or {}).get("network") or "").strip().lower()
    if summary_network and summary_network != normalized_network:
        raise WalletBackendError("Autonomous DeFi summary is not bound to the active network.")
    return issue_approval_token(
        tool_name=tool_name,
        network=normalized_network,
        summary=summary,
        mainnet_confirmed=True,
        ttl_seconds=120,
        issued_by=DEFI_TOOLS_ISSUER,
    )
