"""CLI bridge for the official OpenClaw TypeScript plugin."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any


def _parse_bool(value: Any) -> str:
    return "true" if value is True else "false"


def _apply_config_overrides(config: dict[str, Any]) -> None:
    env_map: dict[str, tuple[str, Any]] = {
        "backend": ("AGENT_WALLET_BACKEND", config.get("backend")),
        "signOnly": ("AGENT_WALLET_SIGN_ONLY", _parse_bool(config.get("signOnly"))),
        "network": ("SOLANA_NETWORK", config.get("network")),
        "rpcUrl": ("SOLANA_RPC_URL", config.get("rpcUrl")),
        "publicKey": ("SOLANA_AGENT_PUBLIC_KEY", config.get("publicKey")),
        "privateKey": ("SOLANA_AGENT_PRIVATE_KEY", config.get("privateKey")),
        "keypairPath": ("SOLANA_AGENT_KEYPAIR_PATH", config.get("keypairPath")),
        "autoCreateWallet": ("SOLANA_AUTO_CREATE_WALLET", _parse_bool(config.get("autoCreateWallet"))),
        "masterKey": ("AGENT_WALLET_MASTER_KEY", config.get("masterKey")),
        "encryptUserWallets": (
            "AGENT_WALLET_ENCRYPT_USER_WALLETS",
            _parse_bool(config.get("encryptUserWallets")),
        ),
        "migratePlaintextUserWallets": (
            "AGENT_WALLET_MIGRATE_PLAINTEXT_USER_WALLETS",
            _parse_bool(config.get("migratePlaintextUserWallets")),
        ),
        "openclawHome": ("OPENCLAW_HOME", config.get("openclawHome")),
        "jupiterBaseUrl": ("JUPITER_API_BASE_URL", config.get("jupiterBaseUrl")),
        "jupiterUltraBaseUrl": ("JUPITER_ULTRA_API_BASE_URL", config.get("jupiterUltraBaseUrl")),
        "jupiterPriceBaseUrl": ("JUPITER_PRICE_API_BASE_URL", config.get("jupiterPriceBaseUrl")),
        "jupiterPortfolioBaseUrl": (
            "JUPITER_PORTFOLIO_API_BASE_URL",
            config.get("jupiterPortfolioBaseUrl"),
        ),
        "jupiterLendBaseUrl": ("JUPITER_LEND_API_BASE_URL", config.get("jupiterLendBaseUrl")),
        "jupiterApiKey": ("JUPITER_API_KEY", config.get("jupiterApiKey")),
    }
    for _, (env_name, value) in env_map.items():
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        os.environ[env_name] = text


def _load_json(raw: str | None, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not raw:
        return {} if default is None else dict(default)
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object.")
    return parsed


async def _run_onboard(user_id: str, config: dict[str, Any]) -> dict[str, Any]:
    from agent_wallet.openclaw_runtime import onboard_openclaw_user_wallet

    context = onboard_openclaw_user_wallet(
        user_id,
        sign_only=config.get("signOnly"),
        network=config.get("network"),
        rpc_url=config.get("rpcUrl"),
    )
    return context.serializable_bundle()


async def _run_invoke(
    user_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    from agent_wallet.openclaw_runtime import onboard_openclaw_user_wallet

    context = onboard_openclaw_user_wallet(
        user_id,
        sign_only=config.get("signOnly"),
        network=config.get("network"),
        rpc_url=config.get("rpcUrl"),
    )
    result = await context.adapter.invoke(tool_name, arguments)
    return result.model_dump()


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenClaw wallet bridge CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    onboard_parser = subparsers.add_parser("onboard")
    onboard_parser.add_argument("--user-id", required=True)
    onboard_parser.add_argument("--config-json", default="{}")

    invoke_parser = subparsers.add_parser("invoke")
    invoke_parser.add_argument("--user-id", required=True)
    invoke_parser.add_argument("--tool", required=True)
    invoke_parser.add_argument("--arguments-json", default="{}")
    invoke_parser.add_argument("--config-json", default="{}")

    args = parser.parse_args()

    try:
        config = _load_json(getattr(args, "config_json", "{}"))
        _apply_config_overrides(config)

        if args.command == "onboard":
            payload = asyncio.run(_run_onboard(args.user_id, config))
        else:
            payload = asyncio.run(
                _run_invoke(
                    args.user_id,
                    args.tool,
                    _load_json(args.arguments_json),
                    config,
                )
            )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1

    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
