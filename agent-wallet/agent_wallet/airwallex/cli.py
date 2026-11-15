"""Operator CLI for the shared agent account.

    python -m agent_wallet.airwallex.cli status
    python -m agent_wallet.airwallex.cli agent set research-bot --budget 200 --per-tx 50 --auto 25 --mcc 5734 7372
    python -m agent_wallet.airwallex.cli approvals
    python -m agent_wallet.airwallex.cli approve <payment_id> [--amount 40] [--note "ok"]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from typing import Any

from agent_wallet.airwallex import treasury as T
from agent_wallet.airwallex.client import AirwallexClient, save_credentials
from agent_wallet.airwallex.service import TreasuryService
from agent_wallet.wallet_layer.base import WalletBackendError

BOLD, DIM, RED, GREEN, YELLOW, CYAN, RESET = "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[36m", "\033[0m"
STATUS_COLOR = {T.SETTLED: GREEN, T.CARD_ISSUED: CYAN, T.X402_READY: CYAN, T.PENDING_APPROVAL: YELLOW,
                T.DENIED: RED, T.DECLINED: RED, T.EXPIRED: DIM, T.CANCELLED: DIM, T.APPROVED: CYAN}


def _c(text: Any, color: str) -> str:
    return f"{color}{text}{RESET}" if sys.stdout.isatty() else str(text)


def _table(rows: list[list[Any]], header: list[str]) -> str:
    cells = [header] + [[str(c) for c in r] for r in rows]
    widths = [max(len(_strip(r[i])) for r in cells) for i in range(len(header))]
    lines = ["  ".join(_c(h.ljust(w), BOLD) for h, w in zip(header, widths))]
    for r in cells[1:]:
        lines.append("  ".join(c + " " * (w - len(_strip(c))) for c, w in zip(r, widths)))
    return "\n".join(lines)


def _strip(text: str) -> str:
    import re
    return re.sub(r"\033\[[0-9;]*m", "", text)


def _when(ts: float | None) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M:%S") if ts else "-"


def _status(s: str) -> str:
    return _c(s, STATUS_COLOR.get(s, ""))


def print_dashboard(service: TreasuryService) -> None:
    dash = service.treasury.dashboard()
    acct = dash["account"]
    print(_c(f"{acct['name']}  ·  budgets in {acct['currency']}  ·  reserve floor {acct['reserve_floor']}", BOLD))
    rows = []
    for a in dash["agents"]:
        rows.append([a["agent_id"], _c(a["status"], GREEN if a["status"] == "active" else RED), a["budget"], a["spent"],
                     a["reserved"], a["available"], a["per_tx_limit"], a["auto_approve_limit"],
                     ",".join(a["rails"]), ",".join(a["allowed_mcc"]) or "any"])
    print(_table(rows, ["agent", "status", "budget", "spent", "reserved", "available", "per-tx", "auto≤", "rails", "mcc"]))
    t = dash["totals"]
    print(_c(f"total  budget {t['budget']}  spent {t['spent']}  reserved {t['reserved']}  available {t['available']}", DIM))
    if dash["pending_approvals"]:
        print()
        print(_c(f"{len(dash['pending_approvals'])} payment(s) waiting for approval — run `treasury approvals`", YELLOW))


def print_payments(payments: list[dict[str, Any]]) -> None:
    rows = [[_when(p["created_at"]), p["payment_id"][:8], p["agent_id"], p["merchant"][:28], p["amount"], p["rail"],
             _status(p["status"]), p.get("card_last4") or "", ",".join((p.get("decision") or {}).get("reasons", []))]
            for p in payments]
    print(_table(rows, ["time", "id", "agent", "merchant", "amount", "rail", "status", "card", "decision"]) if rows else "No payments.")


def _resolve(service: TreasuryService, prefix: str) -> str:
    matches = [pid for pid in service.treasury.read()["payments"] if pid.startswith(prefix)]
    if len(matches) != 1:
        raise WalletBackendError("Payment id prefix %r matches %d payments." % (prefix, len(matches)))
    return matches[0]


async def run(args: argparse.Namespace) -> int:
    service = TreasuryService(args.user_id)
    cmd = args.command
    if cmd == "connect":
        import os
        client_id = args.client_id or os.getenv("AIRWALLEX_CLIENT_ID") or os.getenv("clientid_aw")
        api_key = args.api_key or os.getenv("AIRWALLEX_API_KEY") or os.getenv("airwallex")
        if not (client_id and api_key):
            raise WalletBackendError("Provide --client-id/--api-key or AIRWALLEX_CLIENT_ID/AIRWALLEX_API_KEY in the environment.")
        path = save_credentials(client_id, api_key, environment=args.environment)
        account = await AirwallexClient().request("GET", "/api/v1/account")
        print(f"Connected Airwallex {args.environment} account {account.get('id')} (credentials in {path}, mode 0600).")
    elif cmd == "status":
        print_dashboard(service)
    elif cmd == "account":
        print(json.dumps(service.treasury.configure_account(reserve_floor=args.reserve_floor, card_ttl_minutes=args.card_ttl,
                                                            name=args.name), indent=1))
    elif cmd == "agent":
        agent = service.treasury.upsert_agent(args.agent_id, name=args.name, budget=args.budget, per_tx_limit=args.per_tx,
                                              auto_approve_limit=args.auto, allowed_mcc=args.mcc, rails=args.rails)
        print(f"Agent {agent['agent_id']}: budget {agent['budget']}, per-tx {agent['per_tx_limit']}, auto-approve ≤ {agent['auto_approve_limit']}, "
              f"rails {','.join(agent['rails'])}, mcc {','.join(agent['allowed_mcc']) or 'any'}")
    elif cmd == "pause":
        print(json.dumps(await service.freeze_agent(args.agent_id), indent=1))
    elif cmd == "resume":
        service.treasury.upsert_agent(args.agent_id, status="active")
        print(f"Agent {args.agent_id} resumed. Frozen cards stay frozen; new purchases get new cards.")
    elif cmd == "approvals":
        pending = service.treasury.list_payments(status=T.PENDING_APPROVAL)
        if not pending:
            print("No payments waiting for approval.")
        for p in pending:
            summary = service.treasury.agent_summary(p["agent_id"])
            print(_c(f"{p['payment_id']}", BOLD))
            print(f"  agent     {p['agent_id']} (available {summary['available']} of {summary['budget']})")
            print(f"  merchant  {p['merchant']}  {p.get('merchant_url') or ''}")
            print(f"  amount    {p['amount']} {p['currency']} via {p['rail']}  mcc {p.get('mcc') or '-'}")
            print(f"  purpose   {p['purpose']}")
            print(f"  why       {_c(', '.join(p['decision']['reasons']), YELLOW)}")
    elif cmd == "approve":
        result = await service.approve(_resolve(service, args.payment_id), note=args.note, amount_override=args.amount)
        print(json.dumps(result, indent=1))
    elif cmd == "deny":
        print(json.dumps(service.deny(_resolve(service, args.payment_id), note=args.note), indent=1))
    elif cmd == "cancel":
        print(json.dumps(await service.cancel(_resolve(service, args.payment_id), actor="operator"), indent=1))
    elif cmd == "payments":
        print_payments(service.treasury.list_payments(agent_id=args.agent, limit=args.limit))
    elif cmd == "show":
        print(json.dumps(service.treasury.get_payment(_resolve(service, args.payment_id)), indent=1, default=str))
    elif cmd == "charge":
        result = await service.simulate_charge(_resolve(service, args.payment_id), amount=args.amount, mcc=args.mcc)
        ch = result["charge"]
        color = GREEN if ch["process_result"] == "APPROVED" else RED
        print(_c(f"Airwallex: {ch['process_result']} {ch.get('failure_reason') or ''}  {ch['amount']} {ch['currency']} mcc {ch['mcc']}", color))
        print(f"payment status: {_status(result['status'])}")
    elif cmd == "checkout":
        result = await service.checkout(_resolve(service, args.payment_id), args.url)
        ch = result["charge"]
        color = GREEN if ch["process_result"] == "APPROVED" else RED
        print(_c(f"{ch.get('merchant')}: {ch['process_result']} {ch.get('failure_reason') or ''}  {ch['amount']} {ch['currency']} mcc {ch['mcc']}  {ch.get('order_id') or ''}", color))
        print(f"payment status: {_status(result['status'])}")
    elif cmd == "request":
        result = await service.request_payment(agent_id=args.agent_id, merchant=args.merchant, amount=args.amount,
                                               purpose=args.purpose, merchant_url=args.url, mcc=args.mcc)
        print(json.dumps(result, indent=1))
    elif cmd == "sync":
        print(json.dumps(await service.sync(), indent=1))
    elif cmd == "idle":
        print(json.dumps(await service.idle_funds(), indent=1))
    elif cmd == "events":
        for e in service.treasury.read()["events"][-args.limit:]:
            extra = {k: v for k, v in e.items() if k not in {"at", "kind", "actor"}}
            print(f"{_when(e['at'])}  {e['actor']:<14} {e['kind']:<22} {json.dumps(extra, default=str)[:140]}")
    elif cmd == "balances":
        balances = await AirwallexClient().request("GET", "/api/v1/balances/current")
        rows = [[b["currency"], b.get("available_amount"), b.get("pending_amount"), b.get("total_amount")]
                for b in balances if b.get("total_amount")]
        print(_table(rows, ["currency", "available", "pending", "total"]))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="treasury", description="Operator console for the AgentLayer shared agent account (Airwallex).")
    p.add_argument("--user-id", default=None)
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("connect", help="Save Airwallex API credentials (sandbox by default)")
    c.add_argument("--client-id"); c.add_argument("--api-key")
    c.add_argument("--environment", default="sandbox", choices=["sandbox", "production"])
    sub.add_parser("status", help="Budgets, spend and reservations per agent")
    sub.add_parser("balances", help="Airwallex account balances")
    db = sub.add_parser("dashboard", help="Local operator web dashboard (127.0.0.1)")
    db.add_argument("--port", type=int, default=8787)
    a = sub.add_parser("account", help="Shared account settings")
    a.add_argument("--reserve-floor"); a.add_argument("--card-ttl", type=int); a.add_argument("--name")
    g = sub.add_parser("agent", help="Create or update an agent's budget and policy")
    g.add_argument("agent_id"); g.add_argument("--name"); g.add_argument("--budget"); g.add_argument("--per-tx")
    g.add_argument("--auto", help="auto-approve purchases up to this amount"); g.add_argument("--mcc", nargs="*")
    g.add_argument("--rails", nargs="+", choices=["x402", "card"])
    for name in ("pause", "resume"):
        s = sub.add_parser(name, help=f"{name} an agent" + (" and freeze its live cards" if name == "pause" else ""))
        s.add_argument("agent_id")
    sub.add_parser("approvals", help="Payments waiting for the operator")
    ap = sub.add_parser("approve"); ap.add_argument("payment_id"); ap.add_argument("--amount"); ap.add_argument("--note")
    dn = sub.add_parser("deny"); dn.add_argument("payment_id"); dn.add_argument("--note")
    cn = sub.add_parser("cancel"); cn.add_argument("payment_id")
    pm = sub.add_parser("payments"); pm.add_argument("--agent"); pm.add_argument("--limit", type=int, default=30)
    sh = sub.add_parser("show"); sh.add_argument("payment_id")
    ch = sub.add_parser("charge", help="Sandbox: simulate the merchant's card authorization")
    ch.add_argument("payment_id"); ch.add_argument("--amount"); ch.add_argument("--mcc")
    co = sub.add_parser("checkout", help="Sandbox: pay a local test merchant's checkout form with the payment's card")
    co.add_argument("payment_id"); co.add_argument("--url", required=True)
    rq = sub.add_parser("request", help="Act as an agent: request a purchase")
    rq.add_argument("agent_id"); rq.add_argument("--merchant", required=True); rq.add_argument("--amount", required=True)
    rq.add_argument("--purpose", required=True); rq.add_argument("--url"); rq.add_argument("--mcc")
    sub.add_parser("sync", help="Reconcile cards with Airwallex Issuing transactions")
    sub.add_parser("idle", help="Idle cash available for the yield vault")
    ev = sub.add_parser("events", help="Audit log"); ev.add_argument("--limit", type=int, default=25)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "dashboard":
        from agent_wallet.airwallex.dashboard import serve
        serve(args.port, args.user_id)
        return 0
    try:
        return asyncio.run(run(args))
    except WalletBackendError as exc:
        print(_c("error: " + str(exc), RED), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
