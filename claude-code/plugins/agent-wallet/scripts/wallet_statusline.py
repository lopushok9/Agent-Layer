#!/usr/bin/env python3
"""Fast, read-only statusLine renderer: SOL + Base USDC balances.

Reads the cached wallet addresses written by wallet_statusline_setup.sh /
resolve_wallet_addresses.py (never touches the wallet backend or any secret
material itself) and polls public RPCs directly, with its own short TTL
cache so a rapid string of statusLine invocations doesn't hammer the RPCs
or add latency to the UI.
"""
import json
import os
import time
import urllib.request

STATE_DIR = os.path.expanduser("~/.openclaw/wallet-statusline")
ADDRESS_FILE = os.path.join(STATE_DIR, "addresses.json")
BALANCE_CACHE_FILE = os.path.join(STATE_DIR, "balance_cache.json")

SOL_USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
BASE_USDC_CONTRACT = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"

SOL_RPC = "https://api.mainnet-beta.solana.com"
BASE_RPC = "https://base-rpc.publicnode.com"

TTL_SECONDS = 30
TIMEOUT = 2.5

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
LABEL_COLOR = "\x1b[38;2;56;189;248m"
GRAY = "\x1b[38;2;156;163;175m"
DIM = "\x1b[2m"


def rpc_call(url, method, params):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (wallet-statusline)"}
    req = urllib.request.Request(url, data=payload, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read())


def load_addresses():
    try:
        with open(ADDRESS_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def fetch_sol_usdc(sol_address):
    result = rpc_call(
        SOL_RPC,
        "getTokenAccountsByOwner",
        [sol_address, {"mint": SOL_USDC_MINT}, {"encoding": "jsonParsed"}],
    )["result"]["value"]
    if not result:
        return 0.0
    return result[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"]


def fetch_base_usdc(base_address):
    selector = "70a08231"
    padded_address = base_address[2:].rjust(64, "0")
    data = f"0x{selector}{padded_address}"
    raw = rpc_call(BASE_RPC, "eth_call", [{"to": BASE_USDC_CONTRACT, "data": data}, "latest"])["result"]
    return int(raw, 16) / 1_000_000


def fetch_balances(addresses):
    return {
        "sol": fetch_sol_usdc(addresses["sol_address"]),
        "base": fetch_base_usdc(addresses["base_address"]),
        "fetched_at": time.time(),
    }


def load_cache():
    try:
        with open(BALANCE_CACHE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_cache(data):
    os.makedirs(os.path.dirname(BALANCE_CACHE_FILE), exist_ok=True)
    tmp = BALANCE_CACHE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, BALANCE_CACHE_FILE)


def format_line(data, stale):
    marker = f"{DIM}~ {RESET}" if stale else ""
    total = data["sol"] + data["base"]
    label = f"{BOLD}{LABEL_COLOR}AGENTLAYER{RESET}"
    total_str = f"{BOLD}{LABEL_COLOR}${total:.2f}{RESET}"
    base = f"{GRAY}base ${data['base']:.2f}{RESET}"
    sol = f"{GRAY}sol ${data['sol']:.2f}{RESET}"
    breakdown = f"{DIM}({RESET}{base}{DIM} · {RESET}{sol}{DIM}){RESET}"
    return f"{marker}{label} {total_str} {breakdown}"


def main():
    addresses = load_addresses()
    if not addresses:
        print(f"{DIM}wallet: run /wallet-statusline to enable{RESET}")
        return

    cache = load_cache()
    now = time.time()

    if cache and now - cache["fetched_at"] < TTL_SECONDS:
        print(format_line(cache, stale=False))
        return

    try:
        fresh = fetch_balances(addresses)
        save_cache(fresh)
        print(format_line(fresh, stale=False))
    except Exception:
        if cache:
            print(format_line(cache, stale=True))
        else:
            print(f"{DIM}wallet: unavailable{RESET}")


if __name__ == "__main__":
    main()
