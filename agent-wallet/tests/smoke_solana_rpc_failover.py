"""Smoke test for Solana RPC failover behavior."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.exceptions import ProviderError  # noqa: E402
from agent_wallet.providers import solana_rpc  # noqa: E402


async def _run() -> None:
    calls: list[str] = []
    original = solana_rpc._do_rpc_call

    async def fake_do_rpc_call(rpc_url: str, method: str, params: list[object]) -> dict[str, object]:
        calls.append(rpc_url)
        if rpc_url == "https://primary.example":
            raise ProviderError("solana-rpc", "Rate limited on https://primary.example")
        return {"result": {"value": 123}}

    solana_rpc._do_rpc_call = fake_do_rpc_call
    try:
        data = await solana_rpc.rpc_call(
            "getBalance",
            ["Fake11111111111111111111111111111111111111111"],
            [None, "None", "", "https://primary.example", "https://secondary.example"],
        )
    finally:
        solana_rpc._do_rpc_call = original

    assert data["result"]["value"] == 123
    assert calls == ["https://primary.example", "https://secondary.example"]


def main() -> None:
    asyncio.run(_run())
    print("smoke_solana_rpc_failover: ok")


if __name__ == "__main__":
    main()
