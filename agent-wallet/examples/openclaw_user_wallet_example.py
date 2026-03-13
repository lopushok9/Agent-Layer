"""Example: user-scoped wallet integration for an OpenClaw runtime."""

from __future__ import annotations

import asyncio
import json

from agent_wallet.openclaw_adapter import OpenClawWalletAdapter
from agent_wallet.user_wallets import create_wallet_backend_for_user


async def main() -> None:
    user_id = "demo-user-123"
    # Set AGENT_WALLET_MASTER_KEY in the environment before first run so
    # the per-user wallet is encrypted at rest.
    backend = create_wallet_backend_for_user(
        user_id,
        sign_only=False,
        network="devnet",
    )
    adapter = OpenClawWalletAdapter(backend)

    print(f"Loaded backend for user_id={user_id}")
    print(json.dumps([tool.model_dump() for tool in adapter.list_tools()], indent=2))

    address = await adapter.invoke("get_wallet_address")
    print(address.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
