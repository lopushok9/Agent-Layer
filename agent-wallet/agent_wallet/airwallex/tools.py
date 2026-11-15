"""Agent-facing treasury tools. Operator actions (approve, limits, pause) are
deliberately CLI-only: an agent can request and spend, never approve itself."""
from __future__ import annotations

import os
from typing import Any

from agent_wallet.models import AgentToolResult, AgentToolSpec
from agent_wallet.wallet_layer.base import WalletBackendError

_AGENT = {"type": "string", "pattern": "^[a-z0-9][a-z0-9_-]{0,47}$",
          "description": "Your agent id as registered by the operator. Omit when the host binds AGENTLAYER_AGENT_ID."}
_PAYMENT = {"type": "string", "pattern": "^[0-9a-f-]{36}$"}
_AMOUNT = {"type": "string", "pattern": "^[0-9]{1,6}(\\.[0-9]{1,2})?$"}


def tool_specs() -> list[AgentToolSpec]:
    return [
        AgentToolSpec(
            name="treasury_my_budget",
            description="Read your budget on the operator's shared Airwallex account: budget, spent, reserved, available, per-transaction and auto-approve limits, allowed rails and merchant categories. Read-only.",
            input_schema={"type": "object", "properties": {"agent_id": _AGENT}, "additionalProperties": False},
            read_only=True,
        ),
        AgentToolSpec(
            name="treasury_request_payment",
            description=("Request a business purchase from the shared account. The treasury probes merchant_url: if it answers HTTP 402 "
                         "with x402 terms the stablecoin rail is used, otherwise a single-use Airwallex virtual card is issued whose limit "
                         "equals the approved amount, restricted to the merchant category and expiring shortly. Policy is enforced in code: "
                         "within your auto-approve limit it executes at once; otherwise it waits for the human operator. Card details go "
                         "straight into the encrypted vault; you receive only last4 and a vault_reference for use_saved_card."),
            input_schema={"type": "object", "properties": {
                "agent_id": _AGENT,
                "merchant": {"type": "string", "maxLength": 120},
                "amount": _AMOUNT,
                "currency": {"type": "string", "enum": ["USD"], "default": "USD"},
                "purpose": {"type": "string", "maxLength": 300},
                "merchant_url": {"type": "string", "maxLength": 2048, "description": "Endpoint or checkout URL; used to detect x402."},
                "mcc": {"type": "string", "pattern": "^[0-9]{4}$", "description": "Merchant category code, e.g. 5734 software, 7372 cloud, 5817 digital goods."},
                "accepts_x402": {"type": "boolean", "description": "Set false to skip the x402 probe."},
            }, "required": ["merchant", "amount", "purpose"], "additionalProperties": False},
            read_only=False, requires_explicit_user_intent=False, risk_level="medium",
        ),
        AgentToolSpec(
            name="treasury_payment_status",
            description="Status of one of your treasury payments (pending_approval, card_issued, x402_ready, settled, denied, expired). Read-only.",
            input_schema={"type": "object", "properties": {"payment_id": _PAYMENT}, "required": ["payment_id"], "additionalProperties": False},
            read_only=True,
        ),
        AgentToolSpec(
            name="treasury_simulate_charge",
            description="Sandbox only: have the merchant run its card authorization against the card issued for payment_id. Airwallex approves or declines by the card's own controls (amount, category, single use, expiry).",
            input_schema={"type": "object", "properties": {"payment_id": _PAYMENT, "amount": _AMOUNT,
                                                           "mcc": {"type": "string", "pattern": "^[0-9]{4}$"}},
                          "required": ["payment_id"], "additionalProperties": False},
            read_only=False, risk_level="low",
        ),
        AgentToolSpec(
            name="treasury_record_x402",
            description="Report the outcome of an x402 payment you made for an x402_ready treasury payment: settled (with amount and transaction hash) or failed (releases the reservation).",
            input_schema={"type": "object", "properties": {"payment_id": _PAYMENT, "outcome": {"type": "string", "enum": ["settled", "failed"]},
                                                           "amount": _AMOUNT, "transaction": {"type": "string", "maxLength": 200}},
                          "required": ["payment_id", "outcome"], "additionalProperties": False},
            read_only=False, risk_level="low",
        ),
        AgentToolSpec(
            name="treasury_cancel_payment",
            description="Cancel one of your treasury payments that has not settled. Closes its card at Airwallex and releases the reserved budget.",
            input_schema={"type": "object", "properties": {"payment_id": _PAYMENT}, "required": ["payment_id"], "additionalProperties": False},
            read_only=False, risk_level="low",
        ),
    ]


TOOL_NAMES = frozenset(spec.name for spec in tool_specs())


def _agent_id(args: dict[str, Any]) -> str:
    bound = os.getenv("AGENTLAYER_AGENT_ID")
    given = args.get("agent_id")
    if bound and given and given != bound:
        raise WalletBackendError("This session is bound to agent %r." % bound)
    agent_id = bound or given
    if not agent_id:
        raise WalletBackendError("agent_id is required (or set AGENTLAYER_AGENT_ID for this host).")
    return agent_id


async def invoke(tool_name: str, args: dict[str, Any], *, user_id: str | None) -> AgentToolResult:
    from agent_wallet.airwallex.service import TreasuryService

    service = TreasuryService(user_id)
    if tool_name == "treasury_my_budget":
        return AgentToolResult(tool=tool_name, ok=True, data=service.treasury.agent_summary(_agent_id(args)))
    if tool_name == "treasury_request_payment":
        data = await service.request_payment(
            agent_id=_agent_id(args), merchant=args["merchant"], amount=args["amount"], purpose=args["purpose"],
            currency=args.get("currency", "USD"), merchant_url=args.get("merchant_url"), mcc=args.get("mcc"),
            accepts_x402=args.get("accepts_x402"))
        return AgentToolResult(tool=tool_name, ok=True, data=data)
    payment = service.treasury.get_payment(args["payment_id"])
    bound = os.getenv("AGENTLAYER_AGENT_ID")
    if bound and payment["agent_id"] != bound:
        raise WalletBackendError("This payment belongs to another agent.")
    if tool_name == "treasury_payment_status":
        return AgentToolResult(tool=tool_name, ok=True, data=service._agent_view(payment))
    if tool_name == "treasury_simulate_charge":
        data = await service.simulate_charge(args["payment_id"], amount=args.get("amount"), mcc=args.get("mcc"))
        return AgentToolResult(tool=tool_name, ok=True, data=data)
    if tool_name == "treasury_record_x402":
        data = service.record_x402(args["payment_id"], outcome=args["outcome"], amount=args.get("amount"),
                                   transaction=args.get("transaction"))
        return AgentToolResult(tool=tool_name, ok=True, data=data)
    if tool_name == "treasury_cancel_payment":
        return AgentToolResult(tool=tool_name, ok=True, data=await service.cancel(args["payment_id"], actor=payment["agent_id"]))
    raise WalletBackendError("Unknown treasury tool.")
