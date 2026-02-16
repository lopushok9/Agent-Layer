"""OpenClaw Crypto MCP Server — entry point."""

import logging

from fastmcp import FastMCP

from cache import Cache
from config import settings
from tools import prices, sentiment, defi, onchain, gas, search, agents

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)

mcp = FastMCP(
    "OpenClaw Crypto",
    instructions=(
        "Crypto analytics MCP server — prices, DeFi yields/TVL, "
        "on-chain data, token balances, sentiment, gas, crypto news search."
    ),
)

# Shared cache instance
cache = Cache(max_entries=settings.cache_max_entries)

# Register all tool groups
prices.register(mcp, cache)
sentiment.register(mcp, cache)
defi.register(mcp, cache)
onchain.register(mcp, cache)
gas.register(mcp, cache)
search.register(mcp, cache)
agents.register(mcp, cache)

if __name__ == "__main__":
    import sys

    if "--http" in sys.argv:
        port = 8000
        for arg in sys.argv:
            if arg.startswith("--port="):
                port = int(arg.split("=")[1])
        mcp.run(transport="http", host="0.0.0.0", port=port)
    else:
        mcp.run()
