"""Regression smoke test for missing rpcUrls in OpenClaw CLI config."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.openclaw_cli import _apply_config_overrides


def main() -> None:
    os.environ.pop("SOLANA_RPC_URL", None)
    os.environ.pop("SOLANA_RPC_URLS", None)

    _apply_config_overrides(
        {
            "backend": "solana_local",
            "network": "devnet",
            "signOnly": False,
            # rpcUrls intentionally omitted
        }
    )

    assert os.environ.get("SOLANA_NETWORK") == "devnet"
    assert os.environ.get("SOLANA_RPC_URLS", "") != "None"
    assert os.environ.get("SOLANA_RPC_URLS", "") == ""
    print("smoke_rpc_none_config: ok")


if __name__ == "__main__":
    main()
