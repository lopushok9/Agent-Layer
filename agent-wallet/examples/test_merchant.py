"""A local test merchant that takes card payments on the Airwallex sandbox.

    PYTHONPATH=agent-wallet python agent-wallet/examples/test_merchant.py     # http://127.0.0.1:8800

It is a small web shop with a card checkout form. On submit, its backend plays the card network:
it finds the Airwallex-issued card by number, checks expiry and CVC against the card's details, and
authorizes the item's price and merchant category with the Airwallex sandbox
(`POST /api/v1/simulation/issuing/create`, single phase: authorize and clear).
Airwallex then applies the issued card's own controls: limit, merchant category, single use,
expiry. The charge shows up under Issuing transactions in the sandbox web app.

Sandbox stand-in for a real acquirer: the merchant uses the same sandbox credentials as the treasury,
because the simulation only authorizes cards owned by that account. A wrong expiry or CVC is sent as
a declined authorization. The card number is never logged or shown, only the last 4 digits.
"""
from __future__ import annotations

import asyncio
import html
import json
import os
import re
import time
import uuid
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from agent_wallet.airwallex.client import AirwallexClient
from agent_wallet.airwallex.issuing import Issuing

MERCHANT = "Northwind Data Store"
CATALOG = {
    "dataset": ("Market dataset, monthly", Decimal("19.99"), "5734"),
    "gpu": ("GPU compute, 20 h burst", Decimal("45.00"), "7372"),
    "seat": ("Design tool seat", Decimal("12.00"), "5734"),
    "dataset-pro": ("Market dataset PRO (upsell)", Decimal("24.00"), "5734"),
    "casino": ("Casino credits", Decimal("5.00"), "7995"),
}
ORDERS: list[dict] = []
LOOP = asyncio.new_event_loop()

CSS = """<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;600&display=swap" rel="stylesheet">
<style>*{box-sizing:border-box;border-radius:0}body{margin:0;background:#fff;color:#000;font:14px/1.5 "IBM Plex Sans",Helvetica,Arial,sans-serif}
header{padding:18px 32px;border-bottom:2px solid #000;display:flex;justify-content:space-between;align-items:baseline}
h1{font-size:15px;margin:0;text-transform:uppercase;letter-spacing:.06em}.m{font:11px "IBM Plex Mono",Menlo,monospace;text-transform:uppercase;letter-spacing:.06em;color:#6b6b6b}
main{max-width:860px;margin:32px auto;padding:0 32px}table{width:100%;border-collapse:collapse;border:1px solid #000}
td,th{padding:12px 14px;border-bottom:1px solid #d9d9d9;text-align:left}th{font:500 10px "IBM Plex Mono",Menlo,monospace;text-transform:uppercase;letter-spacing:.08em;color:#6b6b6b;border-bottom:1px solid #000}
.n{font-family:"IBM Plex Mono",Menlo,monospace}a.b,button{display:inline-block;background:#000;color:#fff;border:1px solid #000;padding:8px 14px;font:500 11px "IBM Plex Mono",Menlo,monospace;text-transform:uppercase;letter-spacing:.06em;text-decoration:none;cursor:pointer}
form{border:1px solid #000;padding:20px;display:grid;gap:14px;max-width:420px}label{display:grid;gap:4px;font:500 10px "IBM Plex Mono",Menlo,monospace;text-transform:uppercase;letter-spacing:.08em}
input{border:1px solid #000;padding:9px 10px;font:14px "IBM Plex Mono",Menlo,monospace}.row{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}
.tot{display:flex;justify-content:space-between;border-top:1px solid #000;padding-top:12px;font-weight:600}.ok{color:#0a7d32}.no{color:#c8102e}
.box{border:1px solid #000;padding:20px;max-width:520px}.box h2{margin:0 0 10px;font-size:18px}</style>"""


def page(body: str, title: str = MERCHANT) -> str:
    return (f"<!doctype html><html><head><meta charset=utf-8><title>{html.escape(title)}</title>{CSS}</head><body>"
            f"<header><h1>{MERCHANT}</h1><span class=m>Test merchant · Airwallex sandbox</span></header><main>{body}</main></body></html>")


def store() -> str:
    rows = "".join(f"<tr><td>{html.escape(n)}</td><td class=n>MCC {m}</td><td class=n>${p}</td>"
                   f"<td><a class=b href='/checkout/{k}'>Buy</a></td></tr>" for k, (n, p, m) in CATALOG.items())
    orders = "".join(f"<tr><td class=n>{time.strftime('%H:%M:%S', time.localtime(o['at']))}</td><td>{html.escape(o['item'])}</td>"
                     f"<td class=n>${o['amount']}</td><td class=n>•••• {o['last4']}</td>"
                     f"<td class='n {'ok' if o['status'] == 'approved' else 'no'}'>{o['status'].upper()} {html.escape(o.get('failure_reason') or '')}</td></tr>"
                     for o in reversed(ORDERS[-20:]))
    return page("<table><tr><th>Item</th><th>Category</th><th>Price</th><th></th></tr>" + rows + "</table>"
                "<h3 class=m style='margin-top:32px'>Orders</h3><table><tr><th>Time</th><th>Item</th><th>Amount</th><th>Card</th><th>Result</th></tr>"
                + (orders or "<tr><td colspan=5 class=m>No orders yet</td></tr>") + "</table>")


def checkout(sku: str) -> str:
    name, price, mcc = CATALOG[sku]
    return page(f"""<form method=post action="/pay/{sku}" id=checkout>
<div><b>{html.escape(name)}</b><div class=m>MCC {mcc}</div></div>
<label>Card number<input id=cardnumber name=card_number autocomplete=cc-number inputmode=numeric required></label>
<div class=row><label>MM<input id=expmonth name=exp_month autocomplete=cc-exp-month required></label>
<label>YYYY<input id=expyear name=exp_year autocomplete=cc-exp-year required></label>
<label>CVC<input id=cardcvc name=cvc autocomplete=cc-csc required></label></div>
<div class=tot><span>Total</span><span id=total>${price}</span></div>
<button id=pay type=submit>Pay ${price}</button></form>""", f"Checkout · {name}")


async def charge(sku: str, form: dict) -> dict:
    name, price, mcc = CATALOG[sku]
    number = re.sub(r"\D", "", form.get("card_number", ""))
    order = {"order_id": "ord_" + uuid.uuid4().hex[:12], "merchant": MERCHANT, "item": name, "amount": str(price),
             "currency": "USD", "mcc": mcc, "last4": number[-4:] if len(number) >= 4 else "????", "at": time.time()}
    if not 12 <= len(number) <= 19:
        order.update(status="declined", failure_reason="CARD_INVALID")
    else:
        tx = await Issuing(AirwallexClient()).authorize_card_number(
            card_number=number, exp_month=form.get("exp_month", ""), exp_year=form.get("exp_year", ""), cvc=form.get("cvc", ""),
            amount=price, currency="USD", merchant_category_code=mcc, merchant_name=MERCHANT)
        approved = tx.get("process_result") == "APPROVED"
        order.update(status="approved" if approved else "declined", failure_reason=tx.get("failure_reason"),
                     card_transaction_id=tx.get("card_transaction_id"))
    number = ""
    ORDERS.append(order)
    print(f"[merchant] {order['order_id']} {name} ${price} card ••••{order['last4']} → {order['status']} {order.get('failure_reason') or ''}", flush=True)
    return order


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: str, ctype: str = "text/html; charset=utf-8") -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/":
            return self._send(200, store())
        if path.startswith("/checkout/") and path[10:] in CATALOG:
            return self._send(200, checkout(path[10:]))
        if path == "/orders":
            return self._send(200, json.dumps(ORDERS), "application/json")
        self._send(404, page("<p>Not found</p>"))

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        sku = path[5:] if path.startswith("/pay/") else ""
        if sku not in CATALOG:
            return self._send(404, json.dumps({"error": "unknown item"}), "application/json")
        raw = self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 8192)).decode()
        form = {k: v[0] for k, v in parse_qs(raw).items()}
        try:
            order = asyncio.run_coroutine_threadsafe(charge(sku, form), LOOP).result(timeout=60)
        except Exception as exc:  # no card data in errors
            return self._send(502, json.dumps({"error": type(exc).__name__}), "application/json")
        finally:
            form.clear()
        if "application/json" in (self.headers.get("Accept") or ""):
            return self._send(200, json.dumps(order), "application/json")
        ok = order["status"] == "approved"
        self._send(200, page(f"<div class=box><h2 class={'ok' if ok else 'no'}>{'Payment approved' if ok else 'Payment declined'}</h2>"
                             f"<p class=n>{html.escape(order['item'])} · ${order['amount']} · card •••• {order['last4']}</p>"
                             f"<p class=n>{html.escape(order.get('failure_reason') or order['order_id'])}</p>"
                             f"<a class=b href='/'>Back to store</a></div>"))

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    import threading

    threading.Thread(target=LOOP.run_forever, daemon=True).start()
    port = int(os.getenv("TEST_MERCHANT_PORT", "8800"))
    print(f"{MERCHANT} on http://127.0.0.1:{port}  (Airwallex sandbox)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
