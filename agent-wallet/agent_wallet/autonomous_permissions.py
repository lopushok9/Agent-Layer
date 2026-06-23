"""Persistent high-trust permission toggles for unattended wallet flows.

This module is intentionally narrower than ``autonomous_session``.  It models
the "CLI permissions" UX where a user grants a standing capability, not a
budgeted policy envelope.  The first supported scope is Base swaps only.
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
        "tools": raw.get("tools") or [],
        "warning": raw.get("warning"),
    }


def status() -> dict[str, Any]:
    """Return current high-trust autonomous permission status."""
    record = _load_record()
    base_swaps = _scope_status(record, BASE_SWAP_SCOPE)
    return {
        "active": bool(base_swaps.get("enabled")),
        "scopes": {BASE_SWAP_SCOPE: base_swaps},
        "permission_file": str(_permissions_path()),
    }


def approve_base_swaps(*, approved_by: str = "user") -> dict[str, Any]:
    """Enable unattended Base swap execution for supported EVM swap tools."""
    record = _load_record()
    scopes = record.setdefault("scopes", {})
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
    _write_record(record)
    return status()


def revoke_base_swaps() -> dict[str, Any]:
    """Disable unattended Base swap execution."""
    record = _load_record()
    scopes = record.setdefault("scopes", {})
    existing = scopes.get(BASE_SWAP_SCOPE)
    if isinstance(existing, dict):
        existing["enabled"] = False
        existing["revoked_at"] = _now()
    else:
        scopes[BASE_SWAP_SCOPE] = {"enabled": False, "revoked_at": _now()}
    _write_record(record)
    return status()


def is_base_swap_approved() -> bool:
    return bool(status()["scopes"][BASE_SWAP_SCOPE].get("enabled"))


def authorize_base_swap(*, tool_name: str, network: str, summary: dict[str, Any]) -> str:
    """Issue an internal approval token for one exact Base swap operation."""
    if str(tool_name) not in BASE_SWAP_TOOLS:
        raise WalletBackendError("Autonomous permission only covers Base swap tools.")
    if str(network or "").strip().lower() != BASE_SWAP_NETWORK:
        raise WalletBackendError("Autonomous Base swap permission only applies on network=base.")
    if not is_base_swap_approved():
        raise WalletBackendError(
            "Autonomous Base swap permission is not enabled. Ask the user to run "
            "agentlayer_autonomous_approve for scope=base_swaps first."
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
