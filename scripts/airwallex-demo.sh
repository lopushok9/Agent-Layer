#!/usr/bin/env bash
# End-to-end demo against the Airwallex sandbox. Safe to re-run: it uses a fresh
# treasury state file and only sandbox credentials. No real money moves.
#
#   AIRWALLEX_CLIENT_ID=... AIRWALLEX_API_KEY=... ./scripts/airwallex-demo.sh
#   (or put clientid_aw / airwallex in the repo .env)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
T="$ROOT/agent-wallet/scripts/treasury"
if [[ -z "${AIRWALLEX_CLIENT_ID:-}" && -r "$ROOT/.env" ]]; then set -a; source "$ROOT/.env"; set +a; fi
export AGENTLAYER_TREASURY_STATE="${AGENTLAYER_TREASURY_STATE:-$HOME/.openclaw/agent-treasury/demo-$(date +%Y%m%d-%H%M%S).json}"
step() { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; sleep "${DEMO_PAUSE:-1}"; }
pid_of_last() { "$T" payments --limit 1 | tail -1 | awk '{print $2}'; }
PY="${AGENT_WALLET_PYTHON:-}"; [[ -z "$PY" && -x "$ROOT/agent-wallet/.runtime-venv/bin/python" ]] && PY="$ROOT/agent-wallet/.runtime-venv/bin/python"
[[ -z "$PY" ]] && PY="$HOME/.openclaw/agent-wallet-runtime/current/agent-wallet/.runtime-venv/bin/python"
SHOP=http://127.0.0.1:8800
PYTHONPATH="$ROOT/agent-wallet" "$PY" "$ROOT/agent-wallet/examples/test_merchant.py" >/dev/null 2>&1 & SHOP_PID=$!
python3 "$ROOT/agent-wallet/examples/demo_merchants.py" >/dev/null 2>&1 & MERCHANTS=$!
trap 'kill $MERCHANTS $SHOP_PID 2>/dev/null || true' EXIT

sleep 2
step "Operator connects the shared Airwallex account"
"$T" connect
"$T" balances | head -8

step "Operator sets budgets and policy per agent (all limits live in code)"
"$T" account --reserve-floor 1000 --card-ttl 60 --name "Acme agent account" >/dev/null
"$T" agent research-bot --name "Research agent" --budget 200 --per-tx 50 --auto 25 --mcc 5734 5817 7372
"$T" agent ops-bot --name "Ops agent" --budget 500 --per-tx 300 --auto 100
"$T" status

step "research-bot buys a dataset at Northwind Data Store ($SHOP, cards only) → single-use Airwallex card"
"$T" request research-bot --merchant "Northwind Data Store" --amount 19.99 --purpose "Monthly dataset subscription" --mcc 5734 \
  | python3 -c 'import json,sys;d=json.load(sys.stdin);print("rail:",d["routing"]["rail"],"|",d["routing"]["reason"]);print("decision:",d["decision"]);print("card:",{k:d["card"][k] for k in ("last4","limit","single_use","allowed_mcc","details_stored_in_vault")})'
P1=$(pid_of_last)

echo "The treasury submits the shop's checkout form from the vault. The agent never sees the card number."
step "Checkout of the \$24 PRO upsell instead of the approved \$19.99 → Airwallex declines on the rail"
"$T" checkout "$P1" --url "$SHOP/pay/dataset-pro"
step "Checkout of casino credits (MCC 7995) with the same card → declined by merchant category"
"$T" checkout "$P1" --url "$SHOP/pay/casino"
step "Checkout of the approved item → approved and cleared by Airwallex, payment settles"
"$T" checkout "$P1" --url "$SHOP/pay/dataset"
step "Card is single-use: the shop tries to charge it again → Airwallex refuses"
"$T" checkout "$P1" --url "$SHOP/pay/seat" || true

step "ops-bot buys market data: the merchant answers HTTP 402 → x402 rail (USDC), budget reserved"
"$T" request ops-bot --merchant "Market data API" --amount 0.05 --purpose "BTC order book snapshot" \
  --url http://127.0.0.1:8799/x402/market-data \
  | python3 -c 'import json,sys;d=json.load(sys.stdin);print("rail:",d["routing"]["rail"],"|",d["routing"]["reason"]);print(d["status"],"→",d["next_step"])'
"$T" cancel "$(pid_of_last)" >/dev/null && echo "(demo merchant is local: reservation released instead of paying)"
step "Same agent, card-only checkout page → falls back to an Airwallex card"
"$T" request ops-bot --merchant "SaaS vendor (cards only)" --amount 12 --purpose "Seat license" --mcc 5734 \
  --url http://127.0.0.1:8799/checkout/saas \
  | python3 -c 'import json,sys;d=json.load(sys.stdin);print("rail:",d["routing"]["rail"],"|",d["routing"]["reason"]);print("card ••••",d["card"]["last4"],"limit",d["card"]["limit"])'
"$T" checkout "$(pid_of_last)" --url "$SHOP/pay/seat"

step "research-bot asks for \$45 of GPU compute → above its auto-approve limit, waits for the operator"
"$T" request research-bot --merchant "GPU Cloud" --amount 45 --purpose "Burst compute for eval run" --mcc 7372 \
  | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["status"],d["decision"]["reasons"])'
"$T" approvals
P2=$(pid_of_last)
step "Operator approves → a \$45 card is issued, the agent completes checkout"
"$T" approve "$P2" --note "ok for eval" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["status"],"card ••••",d["card"]["last4"],"limit",d["card"]["limit"])'
"$T" checkout "$P2" --url "$SHOP/pay/gpu"

step "research-bot tries to spend \$500 → over budget and per-tx limit, operator denies"
"$T" request research-bot --merchant "Unknown vendor" --amount 500 --purpose "Bulk data" --mcc 5734 \
  | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["status"],d["decision"]["reasons"])'
"$T" deny "$(pid_of_last)" --note "not in plan" >/dev/null && echo denied

step "Operator pauses ops-bot after an incident → its live cards are frozen at Airwallex"
"$T" request ops-bot --merchant "SaaS vendor" --amount 30 --purpose "Seat license" >/dev/null
"$T" pause ops-bot
"$T" request ops-bot --merchant "SaaS vendor" --amount 5 --purpose "Another seat" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["status"],d["decision"]["reasons"])'
"$T" resume ops-bot

step "Spend across agents, reconciliation and idle cash for the yield vault"
"$T" sync >/dev/null
"$T" status
"$T" payments
"$T" idle
echo
echo "State: $AGENTLAYER_TREASURY_STATE"
echo "Shop orders: $SHOP (stops with this script; restart: PYTHONPATH=agent-wallet python agent-wallet/examples/test_merchant.py)"
echo "Dashboard: AGENTLAYER_TREASURY_STATE=$AGENTLAYER_TREASURY_STATE $T dashboard"
