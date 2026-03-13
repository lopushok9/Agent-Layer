"""Example: exposing agent-wallet tools to an OpenClaw-style runtime."""

from __future__ import annotations

import asyncio
import json

from agent_wallet.openclaw_adapter import OpenClawWalletAdapter
from agent_wallet.wallet_layer.factory import create_wallet_backend


async def main() -> None:
    backend = create_wallet_backend()
    if backend is None:
        raise RuntimeError("No wallet backend configured. Set AGENT_WALLET_BACKEND first.")

    adapter = OpenClawWalletAdapter(backend)

    print("Runtime instructions:")
    print(adapter.get_runtime_instructions())
    print()

    print("Registered tools:")
    print(json.dumps([tool.model_dump() for tool in adapter.list_tools()], indent=2))
    print()

    result = await adapter.invoke("get_wallet_capabilities")
    print("Capabilities:")
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
