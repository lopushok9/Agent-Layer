"""Local operator dashboard: budgets, live payments, approvals (127.0.0.1 only).

    agent-wallet/scripts/treasury dashboard [--port 8787]

Write actions (approve/deny/pause/limits) require the per-process token embedded
in the page, so other local pages cannot trigger them cross-origin.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from agent_wallet.airwallex.service import TreasuryService
from agent_wallet.wallet_layer.base import WalletBackendError

PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AgentLayer Treasury</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#fff;--text:#000;--dim:#6b6b6b;--line:#000;--hair:#d9d9d9;--green:#0a7d32;--red:#c8102e;--amber:#9a6200;--blue:#000;--violet:#000}
*{box-sizing:border-box;border-radius:0!important}
body{margin:0;background:var(--bg);color:var(--text);font:13px/1.5 "IBM Plex Sans","Helvetica Neue",Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased}
header{display:flex;align-items:baseline;justify-content:space-between;padding:20px 32px;border-bottom:2px solid var(--line)}
h1{font-size:15px;margin:0;font-weight:600;letter-spacing:.06em;text-transform:uppercase}h1 span{color:var(--dim);font-weight:400;text-transform:none;letter-spacing:0}
.pill{font:11px "IBM Plex Mono",ui-monospace,Menlo,monospace;text-transform:uppercase;letter-spacing:.06em;color:var(--dim);margin-left:18px}
#env{color:var(--text);border:1px solid var(--line);padding:3px 8px}
main{padding:28px 32px 48px;display:grid;gap:28px;max-width:1320px;margin:0 auto}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);border:1px solid var(--line)}
.kpi{padding:16px 18px;border-right:1px solid var(--line)}.kpi:last-child{border-right:0}
.kpi small{font:11px "IBM Plex Mono",ui-monospace,Menlo,monospace;text-transform:uppercase;letter-spacing:.06em;color:var(--dim)}
.kpi b{display:block;font:500 26px/1.2 "IBM Plex Mono",ui-monospace,Menlo,monospace;margin-top:10px;font-variant-numeric:tabular-nums}
section{border:1px solid var(--line);padding:0}
h2{font:600 11px "IBM Plex Mono",ui-monospace,Menlo,monospace;text-transform:uppercase;letter-spacing:.1em;margin:0;padding:10px 16px;border-bottom:1px solid var(--line);background:#000;color:#fff}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th{text-align:left;font:500 10px "IBM Plex Mono",ui-monospace,Menlo,monospace;text-transform:uppercase;letter-spacing:.08em;color:var(--dim);padding:9px 12px;border-bottom:1px solid var(--line)}
td{padding:10px 12px;border-bottom:1px solid var(--hair);vertical-align:middle}tr:last-child td{border-bottom:0}
.bar{height:8px;border:1px solid var(--line);background:#fff;overflow:hidden;min-width:120px}.bar i{display:block;height:100%;float:left}
.s{font:500 10px "IBM Plex Mono",ui-monospace,Menlo,monospace;text-transform:uppercase;letter-spacing:.06em;white-space:nowrap;padding:2px 6px;border:1px solid currentColor}
.settled{color:var(--green)}.card_issued,.x402_ready,.approved{color:var(--text)}.pending_approval{color:var(--amber)}.denied,.declined{color:var(--red)}.expired,.cancelled{color:var(--dim)}
.rail{font:500 10px "IBM Plex Mono",ui-monospace,Menlo,monospace;text-transform:uppercase;letter-spacing:.06em;padding:2px 6px;border:1px solid var(--line)}.rail.x402{background:#000;color:#fff}
button{background:#fff;color:#000;border:1px solid #000;padding:6px 12px;cursor:pointer;font:500 11px "IBM Plex Mono",ui-monospace,Menlo,monospace;text-transform:uppercase;letter-spacing:.06em}
button:hover{background:#000;color:#fff}button.ok{background:#000;color:#fff}button.ok:hover{background:#fff;color:#000}button.no:hover{background:var(--red);border-color:var(--red);color:#fff}
.appr{display:grid}.ap{display:flex;justify-content:space-between;gap:16px;align-items:center;padding:14px 16px;border-bottom:1px solid var(--hair);border-left:4px solid var(--amber)}.ap:last-child{border-bottom:0}
.ap .why{color:var(--amber);font:11px "IBM Plex Mono",ui-monospace,Menlo,monospace;margin-top:4px}.muted{color:var(--dim)}.mono{font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace;font-size:11px}
.grid2{display:grid;grid-template-columns:2fr 1fr;gap:28px;align-items:start}td.mono,#pays td:nth-child(-n+2){white-space:nowrap}#events{padding:4px 16px}.ev{font:11px/1.5 "IBM Plex Mono",ui-monospace,Menlo,monospace;border-bottom:1px solid var(--hair);padding:7px 0}.ev:last-child{border:0}
.empty{color:var(--dim);padding:14px 16px}td.empty{padding:14px 12px}
@media(max-width:900px){.kpis{grid-template-columns:repeat(2,1fr)}.kpi{border-bottom:1px solid var(--line)}.grid2{grid-template-columns:1fr}main,header{padding-left:16px;padding-right:16px}section{overflow-x:auto}}
</style></head><body>
<header><h1>AgentLayer Treasury <span id="acct"></span></h1><div><span class="pill" id="env">Airwallex sandbox</span> <span class="pill" id="upd"></span></div></header>
<main>
<div class="kpis" id="kpis"></div>
<section><h2>Waiting for you</h2><div class="appr" id="appr"></div></section>
<section><h2>Agents</h2><table><thead><tr><th>Agent</th><th>Status</th><th>Budget use</th><th>Spent</th><th>Reserved</th><th>Available</th><th>Per-tx</th><th>Auto ≤</th><th>Rails</th><th>MCC</th><th></th></tr></thead><tbody id="agents"></tbody></table></section>
<div class="grid2">
<section><h2>Payments</h2><table><thead><tr><th>Time</th><th>Agent</th><th>Merchant</th><th>Amount</th><th>Rail</th><th>Status</th><th>Card</th><th>Decision</th></tr></thead><tbody id="pays"></tbody></table></section>
<section><h2>Audit log</h2><div id="events"></div></section>
</div>
<section><h2>Airwallex Issuing · live card transactions</h2><table><thead><tr><th>Time</th><th>Card</th><th>Merchant</th><th>MCC</th><th>Amount</th><th>Type</th><th>Result</th></tr></thead><tbody id="aw"></tbody></table></section>
</main>
<script>
const TOKEN="__TOKEN__";
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const t=ts=>new Date(ts*1000).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit",second:"2-digit"});
async function act(path,body){const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json","X-Treasury-Token":TOKEN},body:JSON.stringify(body||{})});
 const j=await r.json(); if(!r.ok) alert(j.error||"failed"); load();}
async function load(){
 const d=await (await fetch("/api/state")).json();
 $("acct").textContent="· "+d.account.name; $("upd").textContent="updated "+new Date().toLocaleTimeString();
 const T=d.totals, k=[["Agent budgets",T.budget],["Spent",T.spent],["Reserved on cards / x402",T.reserved],["Available to agents",T.available],["Waiting approvals",d.pending_approvals.length]];
 $("kpis").innerHTML=k.map(([l,v],i)=>`<div class="kpi"><small>${l}</small><b>${i<4?"$":""}${esc(v)}</b></div>`).join("");
 $("appr").innerHTML=d.pending_approvals.length?d.pending_approvals.map(p=>`<div class="ap"><div><b>${esc(p.agent_id)}</b> wants <b>$${esc(p.amount)}</b> at ${esc(p.merchant)} <span class="rail ${esc(p.rail)}">${esc(p.rail)}</span><div class="muted">${esc(p.purpose)}</div><div class="why">${esc(p.decision.reasons.join(", "))}</div></div><div><button class="ok" onclick="act('/api/approve',{payment_id:'${p.payment_id}'})">Approve &amp; issue</button> <button class="no" onclick="act('/api/deny',{payment_id:'${p.payment_id}'})">Deny</button></div></div>`).join(""):'<div class="empty">Nothing needs your attention.</div>';
 $("agents").innerHTML=d.agents.map(a=>{const b=+a.budget||1,sp=+a.spent/b*100,rs=+a.reserved/b*100;return `<tr><td><b>${esc(a.name)}</b><div class="muted mono">${esc(a.agent_id)}</div></td><td><span class="s ${a.status=="active"?"settled":"denied"}">${esc(a.status)}</span></td><td><div class="bar"><i style="width:${sp}%;background:#000"></i><i style="width:${rs}%;background:repeating-linear-gradient(45deg,#000 0 2px,#fff 2px 5px)"></i></div></td><td>$${esc(a.spent)}</td><td>$${esc(a.reserved)}</td><td><b>$${esc(a.available)}</b> <span class="muted">/ ${esc(a.budget)}</span></td><td>$${esc(a.per_tx_limit)}</td><td>$${esc(a.auto_approve_limit)}</td><td>${a.rails.map(r=>`<span class="rail ${r}">${r}</span>`).join(" ")}</td><td class="mono">${esc(a.allowed_mcc.join(", ")||"any")}</td><td><button onclick="act('/api/${a.status=="active"?"pause":"resume"}',{agent_id:'${a.agent_id}'})">${a.status=="active"?"Pause + freeze":"Resume"}</button> <button onclick="limits('${a.agent_id}','${a.budget}','${a.per_tx_limit}','${a.auto_approve_limit}')">Limits</button></td></tr>`}).join("");
 $("pays").innerHTML=d.payments.length?d.payments.map(p=>`<tr><td class="muted">${t(p.created_at)}</td><td>${esc(p.agent_id)}</td><td>${esc(p.merchant)}</td><td>$${esc(p.settled_amount||p.amount)}</td><td><span class="rail ${esc(p.rail)}">${esc(p.rail)}</span></td><td><span class="s ${esc(p.status)}">${esc(p.status.replace("_"," "))}</span>${p.failure_reason&&p.status!="settled"?`<div class="muted mono">last: ${esc(p.failure_reason)}</div>`:""}</td><td class="mono">${p.card_last4?"•••• "+esc(p.card_last4):""}</td><td class="muted">${esc((p.decision.reasons||[]).join(", "))}</td></tr>`).join(""):'<tr><td colspan="8" class="empty">No payments yet.</td></tr>';
 $("events").innerHTML=d.events.slice().reverse().map(e=>`<div class="ev"><span class="muted">${t(e.at)}</span> <b>${esc(e.actor)}</b> ${esc(e.kind.replace(/_/g," "))} ${e.amount?"$"+esc(e.amount):""} ${e.failure_reason?'<span style="color:var(--red)">'+esc(e.failure_reason)+'</span>':""}</div>`).join("");
}
function limits(id,b,p,a){const nb=prompt("Budget for "+id,b);if(nb===null)return;const np=prompt("Per-transaction limit",p);if(np===null)return;const na=prompt("Auto-approve up to",a);if(na===null)return;act("/api/limits",{agent_id:id,budget:nb,per_tx_limit:np,auto_approve_limit:na});}
async function loadAw(){try{const d=await (await fetch("/api/airwallex")).json();
 $("aw").innerHTML=(d.items||[]).length?d.items.map(e=>`<tr><td class="muted mono">${esc((e.at||"").replace("T"," ").slice(0,19))}</td><td class="mono">•••• ${esc(e.last4)}</td><td>${esc(e.merchant)}</td><td class="mono">${esc(e.mcc)}</td><td class="mono">$${esc(e.amount)}</td><td class="mono">${esc(e.type)}</td><td><span class="s ${e.result=="APPROVED"?"settled":"denied"}">${esc(e.result)}</span> <span class="mono muted">${esc(e.failure_reason||"")}</span></td></tr>`).join(""):`<tr><td colspan="7" class="empty">${esc(d.error||"No card transactions yet.")}</td></tr>`;}catch(_){}}
load();setInterval(load,2000);loadAw();setInterval(loadAw,6000);
</script></body></html>"""


def serve(port: int = 8787, user_id: str | None = None) -> None:
    service = TreasuryService(user_id)
    token = secrets.token_urlsafe(24)
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()

    def run(coro):
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=120)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: Any, content_type: str = "application/json") -> None:
            data = body.encode() if isinstance(body, str) else json.dumps(body, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if self.path == "/":
                return self._send(200, PAGE.replace("__TOKEN__", token), "text/html; charset=utf-8")
            if self.path == "/api/state":
                dash = service.treasury.dashboard()
                dash["payments"] = service.treasury.list_payments(limit=40)
                dash["events"] = service.treasury.read()["events"][-30:]
                return self._send(200, dash)
            if self.path == "/api/airwallex":
                try:
                    data = run(service.issuing.client.request("GET", "/api/v1/issuing/card_transaction_events",
                                                              params={"page_size": 40}))
                except Exception as exc:  # show the reason, never card data
                    return self._send(200, {"items": [], "error": "Airwallex unavailable: " + type(exc).__name__})
                items = [{"at": e.get("transacted_at"), "last4": str(e.get("masked_card_number") or "")[-4:],
                          "merchant": (e.get("merchant") or {}).get("name"), "mcc": (e.get("merchant") or {}).get("category_code"),
                          "amount": e.get("transaction_amount"), "type": e.get("type"),
                          "result": e.get("process_result"), "failure_reason": e.get("failure_reason")}
                         for e in data.get("items", [])]
                return self._send(200, {"items": items})
            self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            if self.headers.get("X-Treasury-Token") != token:
                return self._send(403, {"error": "missing operator token"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if self.path == "/api/approve":
                    result = run(service.approve(body["payment_id"], note="approved in dashboard"))
                elif self.path == "/api/deny":
                    result = service.deny(body["payment_id"], note="denied in dashboard")
                elif self.path == "/api/pause":
                    result = run(service.freeze_agent(body["agent_id"]))
                elif self.path == "/api/resume":
                    result = service.treasury.upsert_agent(body["agent_id"], status="active")
                elif self.path == "/api/limits":
                    result = service.treasury.upsert_agent(body["agent_id"], budget=body.get("budget"),
                                                           per_tx_limit=body.get("per_tx_limit"),
                                                           auto_approve_limit=body.get("auto_approve_limit"))
                else:
                    return self._send(404, {"error": "not found"})
                self._send(200, result)
            except (WalletBackendError, KeyError, ValueError) as exc:
                self._send(400, {"error": str(exc)})

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Treasury dashboard on http://127.0.0.1:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
