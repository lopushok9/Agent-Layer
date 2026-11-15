"""Operator-controlled shared account: per-agent budgets, policy decisions,
payment ledger, approval queue and audit log.

All amounts, limits and state transitions live here in code. The model only
proposes a purchase and explains exceptions; it never decides whether money moves.
State is a single JSON file guarded by an exclusive file lock.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator

from agent_wallet.airwallex.client import treasury_home
from agent_wallet.file_ops import atomic_write_text
from agent_wallet.wallet_layer.base import WalletBackendError

AGENT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
MCC = re.compile(r"^[0-9]{4}$")
CURRENCIES = {"USD", "EUR", "GBP", "SGD", "AUD", "HKD", "CNY", "CAD", "JPY", "NZD", "CHF"}

# Payment states
PENDING_APPROVAL = "pending_approval"
APPROVED = "approved"            # approved, card not issued yet (or issuance failed and may be retried)
CARD_ISSUED = "card_issued"      # funds reserved on a single-use card
X402_READY = "x402_ready"        # funds reserved; agent pays via x402 tools
SETTLED = "settled"
DECLINED = "declined"            # merchant charge declined by the card rail
DENIED = "denied"                # operator or policy denied
EXPIRED = "expired"
CANCELLED = "cancelled"
RESERVING = {APPROVED, CARD_ISSUED, X402_READY}
TERMINAL = {SETTLED, DECLINED, DENIED, EXPIRED, CANCELLED}

DEFAULT_STATE: dict[str, Any] = {
    "version": 1,
    "account": {"name": "Shared agent account", "currency": "USD", "reserve_floor": "1000.00", "card_ttl_minutes": 60},
    "agents": {},
    "payments": {},
    "events": [],
}


def money(value: Any, *, field: str = "amount") -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise WalletBackendError("%s must be a decimal amount." % field) from None
    if not amount.is_finite() or amount < 0 or amount > Decimal("1000000") or amount.as_tuple().exponent < -2:
        raise WalletBackendError("%s must be between 0 and 1,000,000 with at most two decimals." % field)
    return amount.quantize(Decimal("0.01"))


def _fmt(amount: Decimal) -> str:
    return format(amount.quantize(Decimal("0.01")), "f")


class Treasury:
    def __init__(self, path: Path | None = None):
        self.path = path or Path(os.getenv("AGENTLAYER_TREASURY_STATE") or (treasury_home() / "state.json"))

    # ---- storage -------------------------------------------------------
    @contextmanager
    def _locked(self, write: bool) -> Iterator[dict[str, Any]]:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = self.path.with_suffix(".lock")
        with open(lock_path, "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX if write else fcntl.LOCK_SH)
            state = json.loads(self.path.read_text()) if self.path.is_file() else json.loads(json.dumps(DEFAULT_STATE))
            yield state
            if write:
                state["events"] = state["events"][-500:]
                atomic_write_text(self.path, json.dumps(state, indent=1, sort_keys=True))

    def read(self) -> dict[str, Any]:
        with self._locked(False) as state:
            return state

    @staticmethod
    def _event(state: dict[str, Any], kind: str, actor: str, **data: Any) -> None:
        state["events"].append({"at": time.time(), "kind": kind, "actor": actor, **data})

    # ---- operator: agents & account -------------------------------------
    def configure_account(self, *, reserve_floor: Any = None, card_ttl_minutes: int | None = None, name: str | None = None) -> dict[str, Any]:
        with self._locked(True) as state:
            account = state["account"]
            if reserve_floor is not None:
                account["reserve_floor"] = _fmt(money(reserve_floor, field="reserve_floor"))
            if card_ttl_minutes is not None:
                if not 5 <= int(card_ttl_minutes) <= 24 * 60:
                    raise WalletBackendError("card_ttl_minutes must be between 5 and 1440.")
                account["card_ttl_minutes"] = int(card_ttl_minutes)
            if name:
                account["name"] = str(name)[:80]
            self._event(state, "account_updated", "operator", account=dict(account))
            return dict(account)

    def upsert_agent(self, agent_id: str, *, name: str | None = None, budget: Any = None, per_tx_limit: Any = None,
                     auto_approve_limit: Any = None, allowed_mcc: list[str] | None = None,
                     rails: list[str] | None = None, status: str | None = None) -> dict[str, Any]:
        if not AGENT_ID.match(agent_id or ""):
            raise WalletBackendError("agent_id must be lowercase letters, digits, '-' or '_' (max 48).")
        with self._locked(True) as state:
            agent = state["agents"].get(agent_id) or {
                "agent_id": agent_id, "name": agent_id, "budget": "0.00", "per_tx_limit": "0.00",
                "auto_approve_limit": "0.00", "allowed_mcc": [], "rails": ["x402", "card"], "status": "active",
                "created_at": time.time(),
            }
            before = dict(agent)
            if name is not None:
                agent["name"] = str(name)[:80]
            for key, value in (("budget", budget), ("per_tx_limit", per_tx_limit), ("auto_approve_limit", auto_approve_limit)):
                if value is not None:
                    agent[key] = _fmt(money(value, field=key))
            if allowed_mcc is not None:
                if any(not MCC.match(code) for code in allowed_mcc):
                    raise WalletBackendError("allowed_mcc entries must be 4-digit merchant category codes.")
                agent["allowed_mcc"] = sorted(set(allowed_mcc))
            if rails is not None:
                if not rails or set(rails) - {"x402", "card"}:
                    raise WalletBackendError("rails must be a non-empty subset of x402, card.")
                agent["rails"] = sorted(set(rails))
            if status is not None:
                if status not in {"active", "paused"}:
                    raise WalletBackendError("status must be active or paused.")
                agent["status"] = status
            if money(agent["auto_approve_limit"]) > money(agent["per_tx_limit"]):
                raise WalletBackendError("auto_approve_limit cannot exceed per_tx_limit.")
            state["agents"][agent_id] = agent
            self._event(state, "agent_updated", "operator", agent_id=agent_id,
                        changes={k: agent[k] for k in agent if before.get(k) != agent[k]})
            return dict(agent)

    # ---- accounting ------------------------------------------------------
    @staticmethod
    def _usage(state: dict[str, Any], agent_id: str) -> dict[str, Decimal]:
        spent = reserved = Decimal("0")
        for payment in state["payments"].values():
            if payment["agent_id"] != agent_id:
                continue
            if payment["status"] == SETTLED:
                spent += money(payment.get("settled_amount") or payment["amount"])
            elif payment["status"] in RESERVING:
                reserved += money(payment["amount"])
        return {"spent": spent, "reserved": reserved}

    def agent_summary(self, agent_id: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
        state = state or self.read()
        agent = state["agents"].get(agent_id)
        if not agent:
            raise WalletBackendError("Unknown agent %r. The operator must register it first." % agent_id)
        usage = self._usage(state, agent_id)
        budget = money(agent["budget"])
        return {**agent, "spent": _fmt(usage["spent"]), "reserved": _fmt(usage["reserved"]),
                "available": _fmt(max(Decimal("0"), budget - usage["spent"] - usage["reserved"])),
                "currency": state["account"]["currency"]}

    # ---- policy decision (pure) -----------------------------------------
    @staticmethod
    def decide(agent: dict[str, Any], usage: dict[str, Decimal], *, amount: Decimal, rail: str,
               mcc: str | None) -> dict[str, Any]:
        reasons: list[str] = []
        if agent["status"] != "active":
            return {"outcome": "deny", "reasons": ["agent_paused"]}
        if rail not in agent["rails"]:
            return {"outcome": "deny", "reasons": ["rail_not_allowed:" + rail]}
        if amount <= 0:
            return {"outcome": "deny", "reasons": ["non_positive_amount"]}
        available = money(agent["budget"]) - usage["spent"] - usage["reserved"]
        if amount > available:
            reasons.append("over_budget")
        if amount > money(agent["per_tx_limit"]):
            reasons.append("over_per_transaction_limit")
        if rail == "card" and agent["allowed_mcc"] and mcc not in agent["allowed_mcc"]:
            reasons.append("merchant_category_not_allowed")
        if reasons:
            return {"outcome": "needs_approval", "reasons": reasons}
        if amount > money(agent["auto_approve_limit"]):
            return {"outcome": "needs_approval", "reasons": ["above_auto_approve_limit"]}
        return {"outcome": "auto_approve", "reasons": ["within_policy"]}

    # ---- payments --------------------------------------------------------
    def open_payment(self, *, agent_id: str, merchant: str, amount: Any, currency: str, rail: str,
                     purpose: str, mcc: str | None = None, merchant_url: str | None = None,
                     x402: dict[str, Any] | None = None) -> dict[str, Any]:
        amount_d = money(amount)
        currency = (currency or "USD").upper()
        if currency not in CURRENCIES:
            raise WalletBackendError("Unsupported currency %s." % currency)
        if mcc is not None and not MCC.match(mcc):
            raise WalletBackendError("mcc must be a 4-digit merchant category code.")
        if not purpose or len(purpose) > 300:
            raise WalletBackendError("A purpose of up to 300 characters is required.")
        with self._locked(True) as state:
            if currency != state["account"]["currency"]:
                raise WalletBackendError("Budgets are kept in %s; request in that currency." % state["account"]["currency"])
            agent = state["agents"].get(agent_id)
            if not agent:
                raise WalletBackendError("Unknown agent %r. The operator must register it first." % agent_id)
            decision = self.decide(agent, self._usage(state, agent_id), amount=amount_d, rail=rail, mcc=mcc)
            payment_id = str(uuid.uuid4())
            status = {"auto_approve": APPROVED, "needs_approval": PENDING_APPROVAL, "deny": DENIED}[decision["outcome"]]
            payment = {
                "payment_id": payment_id, "agent_id": agent_id, "merchant": str(merchant)[:120],
                "merchant_url": merchant_url, "amount": _fmt(amount_d), "currency": currency, "rail": rail,
                "mcc": mcc, "purpose": purpose, "status": status, "decision": decision,
                "created_at": time.time(), "updated_at": time.time(), "x402": x402,
            }
            state["payments"][payment_id] = payment
            self._event(state, "payment_requested", agent_id, payment_id=payment_id, amount=payment["amount"],
                        merchant=payment["merchant"], rail=rail, decision=decision)
            return dict(payment)

    def get_payment(self, payment_id: str) -> dict[str, Any]:
        payment = self.read()["payments"].get(payment_id)
        if not payment:
            raise WalletBackendError("Unknown payment_id.")
        return payment

    def transition(self, payment_id: str, new_status: str, *, actor: str, allowed_from: set[str],
                   **fields: Any) -> dict[str, Any]:
        with self._locked(True) as state:
            payment = state["payments"].get(payment_id)
            if not payment:
                raise WalletBackendError("Unknown payment_id.")
            if payment["status"] not in allowed_from:
                raise WalletBackendError("Payment is %s; cannot move to %s." % (payment["status"], new_status))
            previous = payment["status"]
            payment.update(fields)
            payment["status"] = new_status
            payment["updated_at"] = time.time()
            self._event(state, "payment_" + new_status, actor, payment_id=payment_id, previous=previous,
                        **{k: v for k, v in fields.items() if k in {"note", "failure_reason", "settled_amount", "card_last4"}})
            return dict(payment)

    def resolve_approval(self, payment_id: str, *, approve: bool, note: str | None = None,
                         amount_override: Any = None) -> dict[str, Any]:
        fields: dict[str, Any] = {"operator_note": (note or "")[:300]}
        if amount_override is not None:
            fields["amount"] = _fmt(money(amount_override))
        return self.transition(payment_id, APPROVED if approve else DENIED, actor="operator",
                               allowed_from={PENDING_APPROVAL}, **fields)

    def list_payments(self, *, agent_id: str | None = None, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        payments = sorted(self.read()["payments"].values(), key=lambda p: p["created_at"], reverse=True)
        out = [p for p in payments if (not agent_id or p["agent_id"] == agent_id) and (not status or p["status"] == status)]
        return out[:limit]

    def dashboard(self) -> dict[str, Any]:
        state = self.read()
        agents = [self.agent_summary(agent_id, state) for agent_id in sorted(state["agents"])]
        totals = {key: _fmt(sum((money(a[key]) for a in agents), Decimal("0"))) for key in ("budget", "spent", "reserved", "available")}
        pending = [p for p in state["payments"].values() if p["status"] == PENDING_APPROVAL]
        return {"account": state["account"], "agents": agents, "totals": totals,
                "pending_approvals": sorted(pending, key=lambda p: p["created_at"]),
                "recent_events": state["events"][-15:]}
