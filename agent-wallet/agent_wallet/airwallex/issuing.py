"""Airwallex Issuing: per-agent single-purpose virtual cards.

The rail enforces the decision made in code: a card's limit equals the approved
amount, it is single-use, expires shortly and can be restricted to merchant
categories. Sensitive details are fetched once and sealed into the local
CardVault; callers receive only masked metadata and a vault reference.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from agent_wallet.airwallex.client import AirwallexClient, AirwallexError

DEFAULT_CARDHOLDER_EMAIL = "agents@agentlayer.example"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")


def safe_card(card: dict[str, Any]) -> dict[str, Any]:
    controls = card.get("authorization_controls") or {}
    return {
        "card_id": card.get("card_id"),
        "card_status": card.get("card_status"),
        "masked_card_number": card.get("card_number"),
        "brand": card.get("brand"),
        "form_factor": card.get("form_factor"),
        "nickname": card.get("nick_name") or card.get("nickname"),
        "metadata": card.get("metadata"),
        "allowed_transaction_count": controls.get("allowed_transaction_count"),
        "transaction_limits": controls.get("transaction_limits"),
        "allowed_merchant_categories": controls.get("allowed_merchant_categories") or [],
        "active_to": controls.get("active_to"),
        "created_at": card.get("created_at"),
    }


class Issuing:
    def __init__(self, client: AirwallexClient | None = None):
        self.client = client or AirwallexClient()

    async def ensure_cardholder(self, email: str | None = None) -> str:
        """Reuse a READY DELEGATE cardholder or create one (email only, READY at once)."""
        email = email or os.getenv("AIRWALLEX_CARDHOLDER_EMAIL") or DEFAULT_CARDHOLDER_EMAIL
        listing = await self.client.request("GET", "/api/v1/issuing/cardholders", params={"page_size": 100})
        for holder in listing.get("items", []):
            if holder.get("type") == "DELEGATE" and holder.get("status") == "READY":
                return holder["cardholder_id"]
        created = await self.client.request("POST", "/api/v1/issuing/cardholders/create",
                                            json_body={"type": "DELEGATE", "email": email})
        if created.get("status") != "READY":
            raise AirwallexError("Cardholder was created but is %s, not READY." % created.get("status"))
        return created["cardholder_id"]

    async def create_card(self, *, agent_id: str, payment_id: str, amount: Decimal, currency: str,
                          merchant_categories: list[str] | None = None, ttl_minutes: int = 60,
                          single_use: bool = True, created_by: str = "AgentLayer Treasury") -> dict[str, Any]:
        cardholder_id = await self.ensure_cardholder()
        now = datetime.now(timezone.utc)
        controls: dict[str, Any] = {
            "allowed_transaction_count": "SINGLE" if single_use else "MULTIPLE",
            "transaction_limits": {"currency": currency, "limits": [
                {"amount": float(amount), "interval": "PER_TRANSACTION"},
                {"amount": float(amount), "interval": "ALL_TIME"},
            ]},
            "allowed_currencies": [currency],
            "active_from": _iso(now - timedelta(minutes=1)),
            "active_to": _iso(now + timedelta(minutes=ttl_minutes)),
        }
        if merchant_categories:
            controls["allowed_merchant_categories"] = list(merchant_categories)
        body = {
            "request_id": payment_id,  # one payment == one card, retries are idempotent
            "cardholder_id": cardholder_id,
            "created_by": created_by,
            "form_factor": "VIRTUAL",
            "is_personalized": False,
            "program": {"purpose": "COMMERCIAL"},
            "authorization_controls": controls,
            "nick_name": ("agent:%s" % agent_id)[:32],
            "metadata": {"agent_id": agent_id, "payment_id": payment_id, "issuer": "agentlayer-treasury"},
        }
        card = await self.client.request("POST", "/api/v1/issuing/cards/create", json_body=body)
        return card

    async def get_card(self, card_id: str) -> dict[str, Any]:
        return await self.client.request("GET", "/api/v1/issuing/cards/" + card_id)

    async def list_cards(self, *, page_size: int = 50) -> list[dict[str, Any]]:
        data = await self.client.request("GET", "/api/v1/issuing/cards", params={"page_size": max(10, page_size)})
        return data.get("items", [])

    async def remaining_limits(self, card_id: str) -> dict[str, Any]:
        return await self.client.request("GET", "/api/v1/issuing/cards/%s/limits" % card_id)

    async def update_status(self, card_id: str, status: str) -> dict[str, Any]:
        if status not in {"ACTIVE", "INACTIVE", "CLOSED"}:
            raise AirwallexError("Card status must be ACTIVE, INACTIVE (frozen) or CLOSED.")
        return await self.client.request("POST", "/api/v1/issuing/cards/%s/update" % card_id,
                                         json_body={"card_status": status})

    async def transactions(self, *, card_id: str | None = None, page_size: int = 50) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"page_size": max(10, page_size)}
        if card_id:
            params["card_id"] = card_id
        data = await self.client.request("GET", "/api/v1/issuing/transactions", params=params)
        return data.get("items", [])

    async def sensitive_details(self, card_id: str) -> dict[str, Any]:
        """PAN/CVV. Only for sealing into the vault; never return this to an agent."""
        return await self.client.request("GET", "/api/v1/issuing/cards/%s/details" % card_id)

    async def simulate_authorization(self, *, card_id: str, amount: Decimal, currency: str,
                                     merchant_category_code: str = "5734", merchant_name: str = "Agent merchant",
                                     single_phase: bool = True) -> dict[str, Any]:
        if not self.client.is_sandbox:
            raise AirwallexError("Authorization simulation exists only in the Airwallex sandbox.")
        body = {
            "card_id": card_id,
            "transaction_amount": float(amount),
            "transaction_currency": currency,
            "merchant_category_code": merchant_category_code,
            "merchant_info": merchant_name[:43].ljust(43),
            "auth_code": "%06d" % (uuid.uuid4().int % 1000000),
            "single_phase": single_phase,
        }
        return await self.client.request("POST", "/api/v1/simulation/issuing/create", json_body=body)


def seal_card_into_vault(user_id: str | None, *, card: dict[str, Any], details: dict[str, Any],
                         agent_id: str, payment_id: str, amount: Decimal, currency: str) -> dict[str, Any]:
    """Seal Airwallex card details into the CardVault in the same record shape the
    Laso flow uses, so use_saved_card / Kernel checkout work unchanged."""
    from agent_wallet.card_catalog import CardCatalog
    from agent_wallet.card_vault import CardVault

    vault = CardVault(user_id)
    vault.ensure_system()
    vault.check_ready()
    record = {
        "type": "airwallex-card",
        "provider": "airwallex",
        "card_type": "Airwallex Virtual Commercial",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "state": "response_saved",
        "agent_id": agent_id,
        "payment_id": payment_id,
        "order": {"card": {
            "card_id": card.get("card_id"),
            "status": "ready",
            "card_details": {
                "card_number": str(details.get("card_number")),
                "cvv": str(details.get("cvv")),
                "exp_month": int(details.get("expiry_month")),
                "exp_year": int(details.get("expiry_year")),
                "available_balance": format(amount, "f"),
                "name_on_card": details.get("name_on_card"),
            },
            "currency": currency,
        }},
    }
    reference = vault.deposit(record)
    state = CardCatalog(vault).track(reference, record)
    return {"vault_reference": reference, "last4": state.get("entry", {}).get("last4"),
            "details_stored": state.get("entry", {}).get("details_stored") is True}
