"""Smoke test for deployment-owned Solana RPC configuration."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.config import resolve_runtime_solana_rpc_urls  # noqa: E402
from agent_wallet.openclaw_cli import _apply_config_overrides  # noqa: E402


def main() -> None:
    original_env = {
        "SOLANA_RPC_URL": os.environ.get("SOLANA_RPC_URL"),
        "SOLANA_RPC_URLS": os.environ.get("SOLANA_RPC_URLS"),
        "ALCHEMY_API_KEY": os.environ.get("ALCHEMY_API_KEY"),
        "HELIUS_API_KEY": os.environ.get("HELIUS_API_KEY"),
    }
    try:
        os.environ["SOLANA_RPC_URLS"] = "https://alchemy.example,https://helius.example"
        os.environ.pop("SOLANA_RPC_URL", None)

        _apply_config_overrides(
            {
                "rpcUrl": "https://plugin-primary.example",
                "rpcUrls": [
                    "https://plugin-secondary.example",
                    "https://plugin-tertiary.example",
                ],
            }
        )

        assert os.environ["SOLANA_RPC_URLS"] == "https://alchemy.example,https://helius.example"
        resolved = resolve_runtime_solana_rpc_urls(
            "mainnet",
            "https://plugin-primary.example",
            "https://plugin-secondary.example,https://plugin-tertiary.example",
        )
        assert resolved == [
            "https://alchemy.example",
            "https://helius.example",
            "https://api.mainnet-beta.solana.com",
        ]

        os.environ.pop("SOLANA_RPC_URLS", None)
        os.environ["SOLANA_RPC_URL"] = "https://single-env.example"
        resolved_single = resolve_runtime_solana_rpc_urls(
            "devnet",
            "https://plugin-primary.example",
            "https://plugin-secondary.example",
        )
        assert resolved_single == [
            "https://single-env.example",
            "https://api.devnet.solana.com",
        ]

        os.environ.pop("SOLANA_RPC_URL", None)
        fallback = resolve_runtime_solana_rpc_urls(
            "devnet",
            "https://plugin-primary.example",
            "https://plugin-secondary.example,https://plugin-tertiary.example",
        )
        assert fallback == [
            "https://plugin-primary.example",
            "https://plugin-secondary.example",
            "https://plugin-tertiary.example",
            "https://api.devnet.solana.com",
        ]

        os.environ["ALCHEMY_API_KEY"] = "test-alchemy-key"
        alchemy_mainnet = resolve_runtime_solana_rpc_urls(
            "mainnet",
            "https://plugin-primary.example",
            "https://plugin-secondary.example",
        )
        assert alchemy_mainnet == [
            "https://solana-mainnet.g.alchemy.com/v2/test-alchemy-key",
            "https://api.mainnet-beta.solana.com",
        ]

        alchemy_devnet = resolve_runtime_solana_rpc_urls(
            "devnet",
            "https://plugin-primary.example",
            "https://plugin-secondary.example",
        )
        assert alchemy_devnet == [
            "https://solana-devnet.g.alchemy.com/v2/test-alchemy-key",
            "https://api.devnet.solana.com",
        ]

        os.environ.pop("ALCHEMY_API_KEY", None)
        os.environ["HELIUS_API_KEY"] = "test-helius-key"
        helius_mainnet = resolve_runtime_solana_rpc_urls(
            "mainnet",
            "https://plugin-primary.example",
            "https://plugin-secondary.example",
        )
        assert helius_mainnet == [
            "https://mainnet.helius-rpc.com/?api-key=test-helius-key",
            "https://api.mainnet-beta.solana.com",
        ]

        helius_devnet = resolve_runtime_solana_rpc_urls(
            "devnet",
            "https://plugin-primary.example",
            "https://plugin-secondary.example",
        )
        assert helius_devnet == [
            "https://devnet.helius-rpc.com/?api-key=test-helius-key",
            "https://api.devnet.solana.com",
        ]
    finally:
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    print("smoke_runtime_rpc_config: ok")


if __name__ == "__main__":
    main()
