"""Payment orchestration: x402 first, fiat card fallback through Airwallex Issuing.

Flow for an agent purchase:
  1. probe the merchant URL; an HTTP 402 with x402 terms selects the stablecoin rail,
     anything else selects the card rail;
  2. the Treasury policy decides in code: auto-approve, operator approval, or deny;
  3. approved card payments get a single-use virtual card whose limit equals the
     approved amount (rail-enforced), sealed into the CardVault;
  4. settlement is reconciled from Airwallex Issuing transactions.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from agent_wallet.airwallex.client import AirwallexClient, AirwallexError
from agent_wallet.airwallex.issuing import Issuing, safe_card, seal_card_into_vault
from agent_wallet.airwallex import treasury as T
from agent_wallet.wallet_layer.base import WalletBackendError


async def probe_x402(url: str) -> dict[str, Any] | None:
    """Return normalized x402 terms if the merchant answers HTTP 402, else None."""
    from agent_wallet.providers import x402 as x402_provider

    if not url.startswith("https://") and not url.startswith("http://127.0.0.1") and not url.startswith("http://localhost"):
        raise WalletBackendError("merchant_url must be HTTPS.")
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
            response = await client.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError:
        return None
    if response.status_code != 402:
        return None
    header = response.headers.get("PAYMENT-REQUIRED")
    try:
        decoded = x402_provider._decode_payment_required(header) if header else x402_provider._decode_payment_required_body(response)
    except Exception:
        decoded = None
    if not decoded or not decoded.get("accepts"):
        return None
    accepts = [x402_provider.normalize_payment_requirement(req, source="payment_required", resource_url=url)
               for req in decoded["accepts"] if isinstance(req, dict)]
    return {"x402_version": decoded.get("x402_version"), "accepts": accepts[:5]}


class TreasuryService:
    def __init__(self, user_id: str | None = None, *, treasury: T.Treasury | None = None,
                 issuing: Issuing | None = None):
        if user_id is None:
            from agent_wallet.config import resolve_card_vault_user_id
            user_id = resolve_card_vault_user_id()
        self.user_id = user_id
        self.treasury = treasury or T.Treasury()
        self._issuing = issuing

    @property
    def issuing(self) -> Issuing:
        if self._issuing is None:
            self._issuing = Issuing(AirwallexClient())
        return self._issuing

    # ---- agent entry point ----------------------------------------------
    async def request_payment(self, *, agent_id: str, merchant: str, amount: Any, purpose: str,
                              currency: str = "USD", merchant_url: str | None = None, mcc: str | None = None,
                              accepts_x402: bool | None = None) -> dict[str, Any]:
        x402_terms = None
        if accepts_x402 is not False and merchant_url:
            x402_terms = await probe_x402(merchant_url)
        agent = self.treasury.agent_summary(agent_id)
        rail = "x402" if x402_terms and "x402" in agent["rails"] else "card"
        payment = self.treasury.open_payment(agent_id=agent_id, merchant=merchant, amount=amount, currency=currency,
                                             rail=rail, purpose=purpose, mcc=mcc, merchant_url=merchant_url, x402=x402_terms)
        routing = {"rail": rail, "reason": "merchant answered HTTP 402 with x402 terms" if rail == "x402"
                   else ("merchant does not accept x402; using a policy-bound Airwallex card" if merchant_url
                         else "no x402 endpoint given; using a policy-bound Airwallex card")}
        if payment["status"] == T.APPROVED:
            result = await self.execute(payment["payment_id"], actor=agent_id)
            return {"routing": routing, **result}
        return {"routing": routing, **self._agent_view(payment)}

    async def execute(self, payment_id: str, *, actor: str) -> dict[str, Any]:
        payment = self.treasury.get_payment(payment_id)
        if payment["status"] != T.APPROVED:
            raise WalletBackendError("Only approved payments can be executed (this one is %s)." % payment["status"])
        if payment["rail"] == "x402":
            payment = self.treasury.transition(payment_id, T.X402_READY, actor=actor, allowed_from={T.APPROVED})
            view = self._agent_view(payment)
            view["next_step"] = ("Budget reserved. Pay with x402_preview_request + x402_pay_request on merchant_url, "
                                 "then call treasury_record_x402 with the outcome.")
            return view
        return await self._issue_card(payment, actor=actor)

    async def _issue_card(self, payment: dict[str, Any], *, actor: str) -> dict[str, Any]:
        state = self.treasury.read()
        amount = Decimal(payment["amount"])
        currency = payment["currency"]
        balances = await self.issuing.client.request("GET", "/api/v1/balances/current")
        available = next((Decimal(str(b.get("available_amount", 0))) for b in balances if b.get("currency") == currency), Decimal("0"))
        floor = Decimal(state["account"]["reserve_floor"])
        if available - amount < floor:
            self.treasury.transition(payment["payment_id"], T.PENDING_APPROVAL, actor="treasury", allowed_from={T.APPROVED},
                                     note="Account balance would fall below the reserve floor.",
                                     decision={"outcome": "needs_approval", "reasons": ["below_reserve_floor"]})
            return self._agent_view(self.treasury.get_payment(payment["payment_id"]))
        agent = state["agents"][payment["agent_id"]]
        mccs = [payment["mcc"]] if payment.get("mcc") else (agent.get("allowed_mcc") or None)
        card = await self.issuing.create_card(
            agent_id=payment["agent_id"], payment_id=payment["payment_id"], amount=amount, currency=currency,
            merchant_categories=mccs, ttl_minutes=int(state["account"].get("card_ttl_minutes", 60)))
        card_id = card["card_id"]
        for _ in range(10):
            if card.get("card_status") == "ACTIVE":
                break
            await _sleep(1.5)
            card = await self.issuing.get_card(card_id)
        vault_info: dict[str, Any] = {"vault_reference": None}
        try:
            details = await self.issuing.sensitive_details(card_id)
            vault_info = seal_card_into_vault(self.user_id, card=card, details=details, agent_id=payment["agent_id"],
                                              payment_id=payment["payment_id"], amount=amount, currency=currency)
            del details
        except Exception as exc:  # vault unavailable: card stays usable only through server-side simulation
            vault_info = {"vault_reference": None, "vault_error": str(exc)[:200] if isinstance(exc, WalletBackendError) else type(exc).__name__}
        summary = safe_card(card)
        payment = self.treasury.transition(
            payment["payment_id"], T.CARD_ISSUED, actor=actor, allowed_from={T.APPROVED},
            card_id=card_id, card_last4=(summary.get("masked_card_number") or "")[-4:],
            card_active_to=summary.get("active_to"), vault_reference=vault_info.get("vault_reference"),
            card_controls={k: summary[k] for k in ("allowed_transaction_count", "transaction_limits", "allowed_merchant_categories", "active_to")})
        view = self._agent_view(payment)
        view["card"] = {"last4": payment["card_last4"], "limit": payment["amount"], "currency": currency,
                        "single_use": True, "expires_at": payment["card_active_to"],
                        "allowed_mcc": summary.get("allowed_merchant_categories"),
                        "vault_reference": payment.get("vault_reference"),
                        "details_stored_in_vault": bool(vault_info.get("details_stored"))}
        if vault_info.get("vault_error"):
            view["card"]["vault_error"] = vault_info["vault_error"]
        view["next_step"] = ("Use the card only through use_saved_card(vault_reference=...) for checkout; PAN/CVV never "
                             "reach the agent. In the sandbox, treasury_simulate_charge runs the merchant authorization.")
        return view

    # ---- operator actions -------------------------------------------------
    async def approve(self, payment_id: str, *, note: str | None = None, amount_override: Any = None) -> dict[str, Any]:
        self.treasury.resolve_approval(payment_id, approve=True, note=note, amount_override=amount_override)
        return await self.execute(payment_id, actor="operator")

    def deny(self, payment_id: str, *, note: str | None = None) -> dict[str, Any]:
        return self._agent_view(self.treasury.resolve_approval(payment_id, approve=False, note=note))

    async def cancel(self, payment_id: str, *, actor: str) -> dict[str, Any]:
        payment = self.treasury.get_payment(payment_id)
        if payment.get("card_id") and payment["status"] == T.CARD_ISSUED:
            await self.issuing.update_status(payment["card_id"], "CLOSED")
        return self._agent_view(self.treasury.transition(payment_id, T.CANCELLED, actor=actor,
                                                         allowed_from={T.PENDING_APPROVAL, T.APPROVED, T.CARD_ISSUED, T.X402_READY}))

    async def freeze_agent(self, agent_id: str) -> dict[str, Any]:
        """Pause an agent and freeze every live card it holds."""
        self.treasury.upsert_agent(agent_id, status="paused")
        frozen = []
        for payment in self.treasury.list_payments(agent_id=agent_id, status=T.CARD_ISSUED, limit=500):
            await self.issuing.update_status(payment["card_id"], "INACTIVE")
            frozen.append(payment["card_last4"])
        return {"agent_id": agent_id, "status": "paused", "frozen_cards": frozen}

    # ---- settlement -------------------------------------------------------
    async def simulate_charge(self, payment_id: str, *, amount: Any = None, mcc: str | None = None,
                              merchant_name: str | None = None) -> dict[str, Any]:
        """Sandbox: the merchant runs an authorization against the agent's card."""
        payment = self.treasury.get_payment(payment_id)
        replay = payment["status"] == T.SETTLED and payment.get("card_id")
        if payment["status"] != T.CARD_ISSUED and not replay:
            raise WalletBackendError("No live card for this payment (status %s)." % payment["status"])
        charge = T.money(amount if amount is not None else payment["amount"])
        mcc = mcc or payment.get("mcc") or ((payment.get("card_controls") or {}).get("allowed_merchant_categories") or ["5734"])[0]
        tx = await self.issuing.simulate_authorization(card_id=payment["card_id"], amount=charge, currency=payment["currency"],
                                                       merchant_category_code=mcc, merchant_name=merchant_name or payment["merchant"])
        result = {"process_result": tx.get("process_result"), "failure_reason": tx.get("failure_reason"),
                  "amount": T._fmt(charge), "currency": payment["currency"], "mcc": mcc,
                  "card_transaction_id": tx.get("card_transaction_id")}
        attempts = list(payment.get("charge_attempts") or []) + [{**result, "at": time.time()}]
        if replay:
            # A merchant re-using a settled single-use card: show what the rail says, keep the ledger as is.
            if tx.get("process_result") == "APPROVED":
                raise WalletBackendError("Unexpected: a settled single-use card approved another charge; freeze the agent.")
            payment = self.treasury.transition(payment_id, T.SETTLED, actor="merchant", allowed_from={T.SETTLED},
                                               charge_attempts=attempts, failure_reason=tx.get("failure_reason"))
        elif tx.get("process_result") == "APPROVED":
            payment = self.treasury.transition(payment_id, T.SETTLED, actor="merchant", allowed_from={T.CARD_ISSUED},
                                               settled_amount=T._fmt(charge), charge_attempts=attempts,
                                               card_transaction_id=tx.get("card_transaction_id"))
        else:
            payment = self.treasury.transition(payment_id, T.CARD_ISSUED, actor="merchant", allowed_from={T.CARD_ISSUED},
                                               charge_attempts=attempts, failure_reason=tx.get("failure_reason"))
        return {"charge": result, **self._agent_view(payment)}

    def record_x402(self, payment_id: str, *, outcome: str, amount: Any = None, transaction: str | None = None) -> dict[str, Any]:
        payment = self.treasury.get_payment(payment_id)
        if outcome == "settled":
            paid = T.money(amount if amount is not None else payment["amount"])
            if paid > Decimal(payment["amount"]):
                raise WalletBackendError("x402 settlement exceeds the approved amount; escalate to the operator.")
            payment = self.treasury.transition(payment_id, T.SETTLED, actor=payment["agent_id"], allowed_from={T.X402_READY},
                                               settled_amount=T._fmt(paid), x402_transaction=transaction)
        elif outcome == "failed":
            payment = self.treasury.transition(payment_id, T.CANCELLED, actor=payment["agent_id"], allowed_from={T.X402_READY},
                                               note="x402 payment failed; reservation released.")
        else:
            raise WalletBackendError("outcome must be settled or failed.")
        return self._agent_view(payment)

    async def sync(self) -> dict[str, Any]:
        """Reconcile live cards with Airwallex: settle approved charges, expire unused cards."""
        updated = []
        now = datetime.now(timezone.utc)
        for payment in self.treasury.list_payments(status=T.CARD_ISSUED, limit=500):
            txs = await self.issuing.transactions(card_id=payment["card_id"])
            approved = [t for t in txs if t.get("status") in {"APPROVED", "PENDING", "CLEARED", "SETTLED"}
                        and t.get("transaction_type") in {None, "AUTHORIZATION", "CLEARING"}]
            if approved:
                total = sum((Decimal(str(t.get("transaction_amount") or t.get("billing_amount") or 0)) for t in approved), Decimal("0"))
                self.treasury.transition(payment["payment_id"], T.SETTLED, actor="airwallex-sync", allowed_from={T.CARD_ISSUED},
                                         settled_amount=T._fmt(min(total, Decimal(payment["amount"]))))
                updated.append({"payment_id": payment["payment_id"], "status": T.SETTLED})
                continue
            active_to = payment.get("card_active_to")
            if active_to:
                try:
                    expires = datetime.fromisoformat(active_to.replace("Z", "+00:00"))
                except ValueError:
                    expires = None
                if expires and expires < now:
                    try:
                        await self.issuing.update_status(payment["card_id"], "CLOSED")
                    except AirwallexError:
                        pass
                    self.treasury.transition(payment["payment_id"], T.EXPIRED, actor="airwallex-sync", allowed_from={T.CARD_ISSUED},
                                             note="Card expired unused; reservation released.")
                    updated.append({"payment_id": payment["payment_id"], "status": T.EXPIRED})
        return {"updated": updated}

    async def idle_funds(self) -> dict[str, Any]:
        """Cash that is neither reserved for agents nor part of the reserve floor: candidate for the yield vault."""
        dash = self.treasury.dashboard()
        currency = dash["account"]["currency"]
        balances = await self.issuing.client.request("GET", "/api/v1/balances/current")
        available = next((Decimal(str(b.get("available_amount", 0))) for b in balances if b.get("currency") == currency), Decimal("0"))
        reserved = Decimal(dash["totals"]["reserved"])
        unspent_budgets = Decimal(dash["totals"]["available"])
        floor = Decimal(dash["account"]["reserve_floor"])
        idle = max(Decimal("0"), available - reserved - unspent_budgets - floor)
        return {"currency": currency, "airwallex_available": T._fmt(available), "reserved_on_cards": T._fmt(reserved),
                "committed_agent_budgets": T._fmt(unspent_budgets), "reserve_floor": T._fmt(floor),
                "idle_for_yield": T._fmt(idle),
                "suggestion": "Idle cash can be moved to the yield vault (Morpho USDC on Base via the wallet's vault tools) "
                              "and withdrawn when agents need budget."}

    @staticmethod
    def _agent_view(payment: dict[str, Any]) -> dict[str, Any]:
        keys = ("payment_id", "agent_id", "merchant", "amount", "currency", "rail", "status", "decision", "mcc",
                "card_last4", "card_active_to", "vault_reference", "settled_amount", "failure_reason", "operator_note")
        view = {k: payment.get(k) for k in keys if payment.get(k) is not None}
        if payment["status"] == T.PENDING_APPROVAL:
            view["next_step"] = "Waiting for the operator: `treasury approvals` then `treasury approve <payment_id>`."
        elif payment["status"] == T.DENIED:
            view["next_step"] = "Denied. Do not retry the same purchase; explain the exception to the user."
        return view


async def _sleep(seconds: float) -> None:
    import asyncio
    await asyncio.sleep(seconds)
