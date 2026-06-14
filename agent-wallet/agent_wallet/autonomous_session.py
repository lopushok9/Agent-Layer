"""Persistent autonomous-session store.

The OpenClaw wallet CLI is invoked as a fresh subprocess per tool call, so an
autonomous session (the "envelope" a human authorizes once, inside which the
agent may execute without per-transaction confirmation) cannot live in memory.
This module persists the session — its :class:`AutonomousSessionConfig`, start
time, operation count, and spend ledger — to a JSON file under
``OPENCLAW_HOME`` so the same limits are enforced across every subprocess.

Trust model:

* ``start_session`` writes the envelope. It is expected to be called only after
  a human authorizes the exact limits (the adapter gates the agent-facing
  ``start_autonomous_session`` tool behind a host-issued approval token, so the
  agent cannot widen its own permissions).
* ``stop_session`` removes the envelope and is always safe to call (it can only
  *reduce* what the agent may do).
* ``authorize_operation`` rehydrates the engine from the persisted record,
  evaluates the operation, persists the updated counters/spend, and returns a
  signed approval token — or raises :class:`WalletBackendError` on denial.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from agent_wallet.autonomous_policy import (
    AutonomousPolicyEngine,
    AutonomousSessionConfig,
    OperationRequest,
)
from agent_wallet.config import resolve_openclaw_home
from agent_wallet.spending_limits import SpendingConfig, SpendingLedger
from agent_wallet.wallet_layer.base import WalletBackendError

SESSION_VERSION = 1
_SESSION_FILENAME = "autonomous_session.json"
_lock = threading.Lock()


def _session_path() -> Path:
    return resolve_openclaw_home() / _SESSION_FILENAME


# ---------------------------------------------------------------------------
# Config (de)serialization
# ---------------------------------------------------------------------------

def config_to_dict(config: AutonomousSessionConfig) -> dict[str, Any]:
    cfg = config.normalized()
    return {
        "enabled": cfg.enabled,
        "allowed_tools": sorted(cfg.allowed_tools),
        "allowed_networks": sorted(cfg.allowed_networks),
        "allow_mainnet": cfg.allow_mainnet,
        "allowed_recipients": sorted(cfg.allowed_recipients),
        "allow_any_recipient": cfg.allow_any_recipient,
        "require_simulation": cfg.require_simulation,
        "spending": {
            "max_per_tx_lamports": cfg.spending.max_per_tx_lamports,
            "max_hourly_lamports": cfg.spending.max_hourly_lamports,
            "max_daily_lamports": cfg.spending.max_daily_lamports,
            "max_txs_per_minute": cfg.spending.max_txs_per_minute,
        },
        "max_operations": cfg.max_operations,
        "session_ttl_seconds": cfg.session_ttl_seconds,
        "approval_ttl_seconds": cfg.approval_ttl_seconds,
    }


def config_from_dict(data: dict[str, Any]) -> AutonomousSessionConfig:
    spending = data.get("spending") or {}
    return AutonomousSessionConfig(
        enabled=bool(data.get("enabled", False)),
        allowed_tools=frozenset(data.get("allowed_tools") or []),
        allowed_networks=frozenset(data.get("allowed_networks") or []),
        allow_mainnet=bool(data.get("allow_mainnet", False)),
        allowed_recipients=frozenset(data.get("allowed_recipients") or []),
        allow_any_recipient=bool(data.get("allow_any_recipient", False)),
        require_simulation=bool(data.get("require_simulation", True)),
        spending=SpendingConfig(
            max_per_tx_lamports=int(spending.get("max_per_tx_lamports", 0) or 0),
            max_hourly_lamports=int(spending.get("max_hourly_lamports", 0) or 0),
            max_daily_lamports=int(spending.get("max_daily_lamports", 0) or 0),
            max_txs_per_minute=int(spending.get("max_txs_per_minute", 0) or 0),
        ),
        max_operations=int(data.get("max_operations", 0) or 0),
        session_ttl_seconds=int(data.get("session_ttl_seconds", 0) or 0),
        approval_ttl_seconds=int(data.get("approval_ttl_seconds", 120) or 120),
    )


# ---------------------------------------------------------------------------
# Record persistence
# ---------------------------------------------------------------------------

def _load_record() -> dict[str, Any] | None:
    path = _session_path()
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or int(record.get("version") or 0) != SESSION_VERSION:
        return None
    return record


def _write_record(record: dict[str, Any]) -> None:
    path = _session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)  # atomic on POSIX


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_session(config: AutonomousSessionConfig) -> dict[str, Any]:
    """Persist a new autonomous session envelope and return its status."""
    if not config.enabled:
        raise WalletBackendError("Cannot start an autonomous session with enabled=false.")
    record = {
        "version": SESSION_VERSION,
        "started_at": time.time(),
        "operations": 0,
        "spend_entries": [],
        "config": config_to_dict(config),
    }
    with _lock:
        _write_record(record)
    return session_status()


def stop_session() -> dict[str, Any]:
    """Remove any active session. Always safe (only reduces permissions)."""
    with _lock:
        path = _session_path()
        existed = path.exists()
        try:
            path.unlink()
        except FileNotFoundError:
            existed = False
    return {"active": False, "stopped": existed}


def is_active() -> bool:
    record = _load_record()
    return bool(record and (record.get("config") or {}).get("enabled"))


def session_status() -> dict[str, Any]:
    """Return a non-secret view of the current session for the agent/host."""
    record = _load_record()
    if not record:
        return {"active": False}
    cfg = record.get("config") or {}
    started_at = float(record.get("started_at") or 0.0)
    ttl = int(cfg.get("session_ttl_seconds", 0) or 0)
    status: dict[str, Any] = {
        "active": bool(cfg.get("enabled")),
        "started_at": started_at,
        "operations": int(record.get("operations") or 0),
        "max_operations": int(cfg.get("max_operations", 0) or 0),
        "allow_mainnet": bool(cfg.get("allow_mainnet", False)),
        "allowed_tools": cfg.get("allowed_tools") or [],
        "allowed_networks": cfg.get("allowed_networks") or [],
        "allow_any_recipient": bool(cfg.get("allow_any_recipient", False)),
        "require_simulation": bool(cfg.get("require_simulation", True)),
        "spending": cfg.get("spending") or {},
    }
    if ttl > 0:
        status["expires_at"] = started_at + ttl
        status["expired"] = (time.time() - started_at) > ttl
    return status


def authorize_operation(op: OperationRequest) -> str:
    """Authorize *op* against the persisted session, returning an approval token.

    Raises :class:`WalletBackendError` if there is no active session or the
    operation is denied by the policy gate.
    """
    with _lock:
        record = _load_record()
        if not record:
            raise WalletBackendError(
                "No active autonomous session. A host must start one with "
                "start_autonomous_session before unattended execution is allowed."
            )
        config = config_from_dict(record.get("config") or {})

        # Fail closed: if spend caps are configured but the spend amount for
        # this operation could not be determined, deny rather than approve.
        spend_caps_set = any(
            v > 0
            for v in (
                config.spending.max_per_tx_lamports,
                config.spending.max_hourly_lamports,
                config.spending.max_daily_lamports,
            )
        )
        if op.spend_amount is None and spend_caps_set:
            raise WalletBackendError(
                "autonomous policy denied operation: spend amount could not be "
                "verified while spend limits are configured."
            )

        ledger = SpendingLedger(
            config.spending,
            clock=time.time,
            entries=[(float(ts), int(amt)) for ts, amt in record.get("spend_entries") or []],
        )
        engine = AutonomousPolicyEngine(
            config,
            ledger=ledger,
            clock=time.time,
            started_at=float(record.get("started_at") or time.time()),
            operations_used=int(record.get("operations") or 0),
        )
        decision = engine.evaluate(op)
        if not decision.approved or not decision.approval_token:
            raise WalletBackendError(f"autonomous policy denied operation: {decision.reason}")

        record["operations"] = engine.snapshot()["operations"]
        record["spend_entries"] = [[ts, amt] for ts, amt in engine.export_spend()]
        _write_record(record)
        return decision.approval_token
