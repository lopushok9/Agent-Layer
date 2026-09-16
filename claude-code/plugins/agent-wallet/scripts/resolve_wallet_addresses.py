#!/usr/bin/env python3
"""One-time wallet address resolver for the statusline feature.

Launches this plugin's own MCP server (run_mcp.sh) over stdio using the
real MCP protocol — the same interface Claude Code itself talks to — asks
it for the configured Base and Solana addresses, and caches them to disk.

The wallet backend's cold start (unsealing local secret material) can take
several seconds, so this is meant to run once via /wallet-statusline, not
on every statusline tick. wallet_statusline.py only ever reads the cache
this script writes; it never imports the wallet backend itself.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

STATE_DIR = Path(os.path.expanduser("~/.openclaw/wallet-statusline"))
ADDRESS_FILE = STATE_DIR / "addresses.json"


def _tool_json(result):
    return json.loads(result.content[0].text)


async def resolve(run_mcp_path: str) -> dict:
    params = StdioServerParameters(command="sh", args=[run_mcp_path])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            base = _tool_json(await session.call_tool("get_wallet_address", {}))
            sol = _tool_json(await session.call_tool("get_wallet_overview", {"backend": "solana"}))
    return {
        "base_address": base.get("address"),
        "sol_address": sol.get("address"),
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: resolve_wallet_addresses.py <path-to-run_mcp.sh>", file=sys.stderr)
        return 2

    try:
        addresses = asyncio.run(resolve(sys.argv[1]))
    except Exception as exc:
        print(f"Failed to resolve wallet addresses: {exc}", file=sys.stderr)
        return 1

    if not addresses.get("base_address") or not addresses.get("sol_address"):
        print(f"Wallet backend returned incomplete data: {addresses}", file=sys.stderr)
        return 1

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ADDRESS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(addresses))
    tmp.replace(ADDRESS_FILE)

    print(f"Base:   {addresses['base_address']}")
    print(f"Solana: {addresses['sol_address']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
