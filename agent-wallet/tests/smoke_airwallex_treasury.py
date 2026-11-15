"""Offline smoke test: treasury policy, ledger, routing and adapter tools (no network)."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TMP = tempfile.mkdtemp()
os.environ["OPENCLAW_HOME"] = TMP
os.environ.pop("AGENTLAYER_AGENT_ID", None)

from agent_wallet.airwallex import service as S  # noqa: E402
from agent_wallet.airwallex import treasury as T  # noqa: E402
from agent_wallet.wallet_layer.base import WalletBackendError  # noqa: E402


class FakeClient:
    is_sandbox = True

    async def request(self, method: str, path: str, **_: Any) -> Any:
        assert path == "/api/v1/balances/current"
        return [{"currency": "USD", "available_amount": 1500}]


class FakeIssuing:
    def __init__(self) -> None:
        self.client = FakeClient()
        self.cards: dict[str, dict[str, Any]] = {}
        self.status_updates: list[tuple[str, str]] = []

    async def create_card(self, *, agent_id, payment_id, amount, currency, merchant_categories, ttl_minutes, **_):
        card_id = "card-%d" % (len(self.cards) + 1)
        card = {"card_id": card_id, "card_status": "ACTIVE", "card_number": "************%04d" % (1000 + len(self.cards)),
                "authorization_controls": {"allowed_transaction_count": "SINGLE", "allowed_merchant_categories": merchant_categories or [],
                                           "transaction_limits": {"currency": currency, "limits": [{"amount": float(amount), "interval": "PER_TRANSACTION"}]},
                                           "active_to": "2999-01-01T00:00:00+00:00"},
                "limit": Decimal(amount), "mcc": merchant_categories or [], "used": False, "metadata": {"agent_id": agent_id}}
        self.cards[card_id] = card
        return card

    async def get_card(self, card_id):
        return self.cards[card_id]

    async def sensitive_details(self, card_id):
        return {"card_number": "4111111111111111", "cvv": "123", "expiry_month": 12, "expiry_year": 2030}

    async def simulate_authorization(self, *, card_id, amount, currency, merchant_category_code, **_):
        card = self.cards[card_id]
        if card["used"]:
            return {"process_result": "DECLINED", "failure_reason": "CARD_CLOSED"}
        if amount > card["limit"]:
            return {"process_result": "DECLINED", "failure_reason": "LIMIT_EXCEEDED"}
        if card["mcc"] and merchant_category_code not in card["mcc"]:
            return {"process_result": "DECLINED", "failure_reason": "MERCHANT_CATEGORY_NOT_ALLOWED"}
        card["used"] = True
        return {"process_result": "APPROVED", "card_transaction_id": "tx-" + card_id}

    async def update_status(self, card_id, status):
        self.status_updates.append((card_id, status))
        return {}


sealed: list[str] = []


def fake_seal(user_id, *, card, details, **_):
    assert "card_number" in details  # PAN only flows into the vault
    sealed.append(card["card_id"])
    return {"vault_reference": "a" * 32, "last4": details["card_number"][-4:], "details_stored": True}


S.seal_card_into_vault = fake_seal  # never touch the real Keychain in tests


async def main() -> None:
    fake = FakeIssuing()
    treasury = T.Treasury(Path(TMP) / "state.json")
    svc = S.TreasuryService("test-user", treasury=treasury, issuing=fake)
    treasury.upsert_agent("research-bot", budget="100", per_tx_limit="50", auto_approve_limit="25", allowed_mcc=["5734"])

    # auto-approved card purchase, card limit equals the amount, PAN never returned
    r = await svc.request_payment(agent_id="research-bot", merchant="DataCo", amount="20", purpose="dataset", mcc="5734")
    assert r["status"] == T.CARD_ISSUED and r["card"]["limit"] == "20.00", r
    assert "card_number" not in repr(r) and "4111111111111111" not in repr(r)
    assert fake.cards["card-1"]["limit"] == Decimal("20.00")
    assert treasury.agent_summary("research-bot")["reserved"] == "20.00"

    # rail enforces: overcharge and wrong category decline, exact amount settles, reuse declines
    assert (await svc.simulate_charge(r["payment_id"], amount="21"))["charge"]["failure_reason"] == "LIMIT_EXCEEDED"
    assert (await svc.simulate_charge(r["payment_id"], amount="5", mcc="7995"))["charge"]["failure_reason"] == "MERCHANT_CATEGORY_NOT_ALLOWED"
    ok = await svc.simulate_charge(r["payment_id"], amount="20")
    assert ok["status"] == T.SETTLED
    summary = treasury.agent_summary("research-bot")
    assert summary["spent"] == "20.00" and summary["reserved"] == "0.00" and summary["available"] == "80.00", summary

    # above auto-approve: waits for operator, no card issued until approval
    p = await svc.request_payment(agent_id="research-bot", merchant="GPU", amount="40", purpose="compute", mcc="5734")
    assert p["status"] == T.PENDING_APPROVAL and p["decision"]["reasons"] == ["above_auto_approve_limit"]
    assert len(fake.cards) == 1
    approved = await svc.approve(p["payment_id"], note="ok")
    assert approved["status"] == T.CARD_ISSUED and len(fake.cards) == 2

    # over budget and over per-tx and wrong category reasons
    q = await svc.request_payment(agent_id="research-bot", merchant="Big", amount="60", purpose="x", mcc="7995")
    assert set(q["decision"]["reasons"]) == {"over_budget", "over_per_transaction_limit", "merchant_category_not_allowed"}, q
    svc.deny(q["payment_id"], note="no")
    try:
        await svc.approve(q["payment_id"])
        raise AssertionError("denied payment must not be approvable")
    except WalletBackendError:
        pass

    # cancel releases reservation and closes the card
    c = await svc.cancel(approved["payment_id"], actor="research-bot")
    assert c["status"] == T.CANCELLED and fake.status_updates[-1] == ("card-2", "CLOSED")
    assert treasury.agent_summary("research-bot")["reserved"] == "0.00"

    # pause: no spending
    await svc.freeze_agent("research-bot")
    d = await svc.request_payment(agent_id="research-bot", merchant="X", amount="1", purpose="x")
    assert d["status"] == T.DENIED and d["decision"]["reasons"] == ["agent_paused"]

    # reserve floor: 1500 available, floor 1000 -> 600 card goes to approval
    treasury.upsert_agent("ops-bot", budget="1000", per_tx_limit="900", auto_approve_limit="900")
    f = await svc.request_payment(agent_id="ops-bot", merchant="Vendor", amount="600", purpose="invoice")
    assert f["status"] == T.PENDING_APPROVAL and f["decision"]["reasons"] == ["below_reserve_floor"], f

    # x402 rail via probe
    async def fake_probe(url):
        return {"x402_version": 1, "accepts": [{"scheme": "exact"}]}
    S.probe_x402 = fake_probe
    x = await svc.request_payment(agent_id="ops-bot", merchant="Data API", amount="0.05", purpose="quote", merchant_url="https://x.example/q")
    assert x["routing"]["rail"] == "x402" and x["status"] == T.X402_READY
    try:
        svc.record_x402(x["payment_id"], outcome="settled", amount="0.06")
        raise AssertionError("overpayment must be refused")
    except WalletBackendError:
        pass
    assert svc.record_x402(x["payment_id"], outcome="settled", amount="0.05")["status"] == T.SETTLED

    # adapter exposes agent tools but no operator tools, and dispatches
    from agent_wallet.openclaw_adapter import OpenClawWalletAdapter
    from tests.smoke_connector_openclaw_adapter import FakeBackend
    adapter = OpenClawWalletAdapter(FakeBackend(), user_id="test-user")
    names = {t.name for t in adapter.list_tools()}
    assert {"treasury_request_payment", "treasury_my_budget", "treasury_simulate_charge"} <= names
    assert not any("approve" in n for n in names if n.startswith("treasury_"))
    os.environ["AGENTLAYER_TREASURY_STATE"] = str(Path(TMP) / "state.json")
    res = await adapter.invoke("treasury_my_budget", {"agent_id": "ops-bot"})
    assert res.ok and res.data["spent"] == "0.05", res
    os.environ["AGENTLAYER_AGENT_ID"] = "ops-bot"
    res = await adapter.invoke("treasury_my_budget", {"agent_id": "research-bot"})
    assert not res.ok, "bound agent must not read another agent"
    print("smoke_airwallex_treasury: ok")


if __name__ == "__main__":
    asyncio.run(main())
