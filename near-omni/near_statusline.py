#!/usr/bin/env python3
"""Claude Code statusLine: live NEAR balance of a NEAR Omni account.

Usage (in ~/.claude/settings.json):
  "statusLine": {"type": "command",
                 "command": "python3 /path/to/near_statusline.py <your-near-account-id>",
                 "refreshInterval": 30}

Read-only: it only calls the public NEAR RPC view_account method. No keys,
no MCP calls. The account ID comes from omni_balances / near_account_status.
A short on-disk cache keeps rapid statusLine refreshes off the RPC.
"""
import json
import os
import sys
import time
import urllib.request

RPCS = ["https://free.rpc.fastnear.com", "https://rpc.mainnet.near.org"]
CACHE = os.path.expanduser("~/.cache/near-omni-statusline.json")
TTL_SECONDS = 30
TIMEOUT = 2.5

RESET, BOLD, DIM = "\x1b[0m", "\x1b[1m", "\x1b[2m"
BLUE = "\x1b[38;2;37;99;235m"


def view_account(account_id):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "query",
                       "params": {"request_type": "view_account", "finality": "final", "account_id": account_id}}).encode()
    last = None
    for url in RPCS:
        try:
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "near-omni-statusline"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                result = json.loads(resp.read())
            # An implicit account that has never been funded does not exist yet: 0 NEAR.
            return 0.0 if "error" in result else int(result["result"]["amount"]) / 1e24
        except Exception as e:  # try the next RPC
            last = e
    raise last


def read_cache(account_id):
    try:
        with open(CACHE) as f:
            data = json.load(f)
        return data if data.get("account") == account_id else None
    except (OSError, ValueError):
        return None


def write_cache(data):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    tmp = CACHE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, CACHE)


def line(near, stale=False):
    return f"{DIM + '~ ' + RESET if stale else ''}{BOLD}{BLUE}Ⓝ {near:.4f} NEAR{RESET}"


def main():
    account_id = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("NEAR_OMNI_ACCOUNT", "")).strip()
    if not account_id:
        print(f"{DIM}near: pass your NEAR account ID{RESET}")
        return
    cache = read_cache(account_id)
    if cache and time.time() - cache["fetched_at"] < TTL_SECONDS:
        print(line(cache["near"]))
        return
    try:
        near = view_account(account_id)
        write_cache({"account": account_id, "near": near, "fetched_at": time.time()})
        print(line(near))
    except Exception:
        print(line(cache["near"], stale=True) if cache else f"{DIM}near: unavailable{RESET}")


if __name__ == "__main__":
    main()
