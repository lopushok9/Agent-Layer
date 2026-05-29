"""Smoke test for deployment-owned Solana RPC configuration."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.config import (  # noqa: E402
    DEFAULT_PROVIDER_GATEWAY_URL,
    resolve_runtime_solana_rpc_config,
    resolve_runtime_solana_rpc_urls,
    resolve_runtime_solana_swap_config,
)
from agent_wallet.openclaw_cli import _apply_config_overrides  # noqa: E402
from agent_wallet.wallet_layer.base import WalletBackendError  # noqa: E402


def _assert_sol_network_rejected(network: str) -> None:
    try:
        resolve_runtime_solana_rpc_urls(
            network,
            "https://plugin-primary.example",
            "https://plugin-secondary.example",
        )
    except WalletBackendError as exc:
        assert "no longer supported" in str(exc)
    else:
        raise AssertionError(f"Expected Solana network {network} to be rejected.")


def main() -> None:
    original_env = {
        "SOLANA_RPC_URL": os.environ.get("SOLANA_RPC_URL"),
        "SOLANA_RPC_URLS": os.environ.get("SOLANA_RPC_URLS"),
        "ALCHEMY_API_KEY": os.environ.get("ALCHEMY_API_KEY"),
        "HELIUS_API_KEY": os.environ.get("HELIUS_API_KEY"),
        "SOLANA_RPC_PROVIDER_MODE": os.environ.get("SOLANA_RPC_PROVIDER_MODE"),
        "PROVIDER_GATEWAY_URL": os.environ.get("PROVIDER_GATEWAY_URL"),
        "PROVIDER_GATEWAY_RPC_PROVIDER": os.environ.get("PROVIDER_GATEWAY_RPC_PROVIDER"),
        "SOLANA_SWAP_PROVIDER": os.environ.get("SOLANA_SWAP_PROVIDER"),
    }
    try:
        os.environ["SOLANA_RPC_URLS"] = "https://alchemy.example,https://helius.example"
        os.environ.pop("SOLANA_RPC_URL", None)
        os.environ.pop("HELIUS_API_KEY", None)
        os.environ.pop("ALCHEMY_API_KEY", None)
        os.environ.pop("SOLANA_RPC_PROVIDER_MODE", None)
        os.environ.pop("PROVIDER_GATEWAY_URL", None)
        os.environ.pop("PROVIDER_GATEWAY_RPC_PROVIDER", None)
        os.environ.pop("SOLANA_SWAP_PROVIDER", None)

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
            "mainnet",
            "https://plugin-primary.example",
            "https://plugin-secondary.example",
        )
        assert resolved_single == [
            "https://single-env.example",
            "https://api.mainnet-beta.solana.com",
        ]

        os.environ.pop("SOLANA_RPC_URL", None)
        os.environ["PROVIDER_GATEWAY_URL"] = ""
        fallback = resolve_runtime_solana_rpc_urls(
            "mainnet",
            "https://plugin-primary.example",
            "https://plugin-secondary.example,https://plugin-tertiary.example",
        )
        assert fallback == [
            "https://plugin-primary.example",
            "https://plugin-secondary.example",
            "https://plugin-tertiary.example",
            "https://api.mainnet-beta.solana.com",
        ]
        os.environ.pop("PROVIDER_GATEWAY_URL", None)
        assert resolve_runtime_solana_swap_config("mainnet") == {
            "provider": "jupiter",
            "transport": "direct",
        }
        default_shared = resolve_runtime_solana_rpc_config(
            "mainnet",
            "",
            "",
        )
        assert default_shared == {
            "mode": "shared_proxy",
            "provider": "auto",
            "transport": "proxy",
            "rpc_urls": [f"gateway::auto::mainnet::{DEFAULT_PROVIDER_GATEWAY_URL}/v1/rpc"],
        }

        os.environ.pop("SOLANA_RPC_URL", None)
        os.environ.pop("SOLANA_RPC_URLS", None)
        _apply_config_overrides(
            {
                "rpcProviderMode": "shared_proxy",
                "providerGatewayUrl": "https://providers.from-plugin.example",
                "providerGatewayRpcProvider": "shared",
                "heliusApiKey": "plugin-helius-key",
            }
        )
        assert os.environ["SOLANA_RPC_PROVIDER_MODE"] == "shared_proxy"
        assert os.environ["PROVIDER_GATEWAY_URL"] == "https://providers.from-plugin.example"
        assert os.environ["PROVIDER_GATEWAY_RPC_PROVIDER"] == "shared"
        assert os.environ["HELIUS_API_KEY"] == "plugin-helius-key"

        os.environ.pop("HELIUS_API_KEY", None)
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

        _assert_sol_network_rejected("devnet")

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

        _assert_sol_network_rejected("testnet")

        os.environ.pop("HELIUS_API_KEY", None)
        os.environ["SOLANA_RPC_PROVIDER_MODE"] = "shared_proxy"
        os.environ["PROVIDER_GATEWAY_URL"] = "https://providers.example"
        os.environ["PROVIDER_GATEWAY_RPC_PROVIDER"] = "helius"
        proxy_config = resolve_runtime_solana_rpc_config(
            "mainnet",
            "https://plugin-primary.example",
            "https://plugin-secondary.example",
        )
        assert proxy_config == {
            "mode": "shared_proxy",
            "provider": "helius",
            "transport": "proxy",
            "rpc_urls": ["gateway::helius::mainnet::https://providers.example/v1/rpc"],
        }

        proxy_urls = resolve_runtime_solana_rpc_urls(
            "mainnet",
            "https://plugin-primary.example",
            "https://plugin-secondary.example",
        )
        assert proxy_urls == ["gateway::helius::mainnet::https://providers.example/v1/rpc"]
        assert resolve_runtime_solana_swap_config("mainnet") == {
            "provider": "jupiter",
            "transport": "direct",
        }

        os.environ["HELIUS_API_KEY"] = "user-owned-helius"
        direct_wins = resolve_runtime_solana_rpc_config(
            "mainnet",
            "https://plugin-primary.example",
            "https://plugin-secondary.example",
        )
        assert direct_wins == {
            "mode": "user_direct",
            "provider": "helius",
            "transport": "direct",
            "rpc_urls": [
                "https://mainnet.helius-rpc.com/?api-key=user-owned-helius",
                "https://api.mainnet-beta.solana.com",
            ],
        }
        assert resolve_runtime_solana_swap_config("mainnet") == {
            "provider": "jupiter",
            "transport": "direct",
        }

        os.environ["SOLANA_SWAP_PROVIDER"] = "bags"
        assert resolve_runtime_solana_swap_config("mainnet") == {
            "provider": "jupiter",
            "transport": "direct",
        }
    finally:
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    print("smoke_runtime_rpc_config: ok")


if __name__ == "__main__":
    main()
