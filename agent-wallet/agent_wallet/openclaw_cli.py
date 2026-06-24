"""CLI bridge for the official OpenClaw TypeScript plugin."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from agent_wallet.wallet_layer.base import WalletBackendError

try:  # telemetry is optional and must never break the CLI
    from agent_wallet.telemetry import record as _telemetry_record
except Exception:  # pragma: no cover - defensive
    def _telemetry_record(*_args: Any, **_kwargs: Any) -> None:
        return None


def _parse_bool(value: Any) -> str:
    if value is None:
        return ""
    return "true" if value is True else "false"


def _parse_csv(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


SECRET_CONFIG_KEYS = {"privateKey", "masterKey", "approvalSecret"}


def _reject_secret_config_json(config: dict[str, Any]) -> None:
    present = sorted(key for key in SECRET_CONFIG_KEYS if str(config.get(key) or "").strip())
    if present:
        joined = ", ".join(present)
        raise WalletBackendError(
            f"Sensitive keys are not allowed in --config-json: {joined}. "
            "Pass secrets via protected environment injection instead."
        )


def _apply_config_overrides(config: dict[str, Any]) -> None:
    _reject_secret_config_json(config)
    rpc_env_locked = bool(os.getenv("SOLANA_RPC_URL", "").strip() or os.getenv("SOLANA_RPC_URLS", "").strip())
    env_map: dict[str, tuple[str, Any, bool]] = {
        "backend": ("AGENT_WALLET_BACKEND", config.get("backend"), True),
        "signOnly": ("AGENT_WALLET_SIGN_ONLY", _parse_bool(config.get("signOnly")), True),
        "network": ("SOLANA_NETWORK", config.get("network"), True),
        # Deployment-owned RPC env must win over plugin config.
        "rpcUrl": ("SOLANA_RPC_URL", config.get("rpcUrl"), False),
        "rpcUrls": ("SOLANA_RPC_URLS", _parse_csv(config.get("rpcUrls")), False),
        "rpcProviderMode": ("SOLANA_RPC_PROVIDER_MODE", config.get("rpcProviderMode"), True),
        "providerGatewayUrl": ("PROVIDER_GATEWAY_URL", config.get("providerGatewayUrl"), True),
        "providerGatewayRpcProvider": (
            "PROVIDER_GATEWAY_RPC_PROVIDER",
            config.get("providerGatewayRpcProvider"),
            True,
        ),
        "wdkBtcServiceUrl": ("WDK_BTC_SERVICE_URL", config.get("wdkBtcServiceUrl"), True),
        "wdkBtcWalletId": ("WDK_BTC_WALLET_ID", config.get("wdkBtcWalletId"), True),
        "wdkBtcAccountIndex": (
            "WDK_BTC_ACCOUNT_INDEX",
            config.get("wdkBtcAccountIndex"),
            True,
        ),
        "wdkEvmServiceUrl": ("WDK_EVM_SERVICE_URL", config.get("wdkEvmServiceUrl"), True),
        "wdkEvmWalletId": ("WDK_EVM_WALLET_ID", config.get("wdkEvmWalletId"), True),
        "wdkEvmAccountIndex": (
            "WDK_EVM_ACCOUNT_INDEX",
            config.get("wdkEvmAccountIndex"),
            True,
        ),
        "swapProvider": ("SOLANA_SWAP_PROVIDER", config.get("swapProvider"), True),
        "heliusApiKey": ("HELIUS_API_KEY", config.get("heliusApiKey"), True),
        "alchemyApiKey": ("ALCHEMY_API_KEY", config.get("alchemyApiKey"), True),
        "publicKey": ("SOLANA_AGENT_PUBLIC_KEY", config.get("publicKey"), True),
        "keypairPath": ("SOLANA_AGENT_KEYPAIR_PATH", config.get("keypairPath"), True),
        "autoCreateWallet": ("SOLANA_AUTO_CREATE_WALLET", _parse_bool(config.get("autoCreateWallet")), True),
        "encryptUserWallets": (
            "AGENT_WALLET_ENCRYPT_USER_WALLETS",
            _parse_bool(config.get("encryptUserWallets")),
            True,
        ),
        "migratePlaintextUserWallets": (
            "AGENT_WALLET_MIGRATE_PLAINTEXT_USER_WALLETS",
            _parse_bool(config.get("migratePlaintextUserWallets")),
            True,
        ),
        "refuseMainnetWalletRecreation": (
            "AGENT_WALLET_REFUSE_MAINNET_WALLET_RECREATION",
            _parse_bool(config.get("refuseMainnetWalletRecreation")),
            True,
        ),
        "openclawHome": ("OPENCLAW_HOME", config.get("openclawHome"), True),
        "jupiterBaseUrl": ("JUPITER_API_BASE_URL", config.get("jupiterBaseUrl"), True),
        "jupiterSwapV2BaseUrl": ("JUPITER_SWAP_V2_API_BASE_URL", config.get("jupiterSwapV2BaseUrl"), True),
        "jupiterUltraBaseUrl": ("JUPITER_ULTRA_API_BASE_URL", config.get("jupiterUltraBaseUrl"), True),
        "jupiterPriceBaseUrl": ("JUPITER_PRICE_API_BASE_URL", config.get("jupiterPriceBaseUrl"), True),
        "jupiterApiKey": ("JUPITER_API_KEY", config.get("jupiterApiKey"), True),
        "kaminoBaseUrl": ("KAMINO_API_BASE_URL", config.get("kaminoBaseUrl"), True),
        "kaminoProgramId": ("KAMINO_PROGRAM_ID", config.get("kaminoProgramId"), True),
    }
    for _, (env_name, value, allow_override) in env_map.items():
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        if env_name in {"SOLANA_RPC_URL", "SOLANA_RPC_URLS"} and rpc_env_locked:
            continue
        if not allow_override and os.getenv(env_name, "").strip():
            continue
        os.environ[env_name] = text


def _load_json(raw: str | None, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not raw:
        return {} if default is None else dict(default)
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object.")
    return parsed


def _read_stdin_secret(field_name: str) -> str:
    value = sys.stdin.read().strip()
    if not value:
        raise WalletBackendError(f"{field_name} is required on stdin.")
    return value


async def _run_onboard(user_id: str, config: dict[str, Any]) -> dict[str, Any]:
    from agent_wallet.openclaw_runtime import onboard_openclaw_user_wallet

    context = onboard_openclaw_user_wallet(
        user_id,
        backend=config.get("backend"),
        sign_only=config.get("signOnly"),
        network=config.get("network"),
        rpc_url=config.get("rpcUrl"),
        wdk_btc_service_url=config.get("wdkBtcServiceUrl"),
        wdk_btc_wallet_id=config.get("wdkBtcWalletId"),
        wdk_btc_account_index=config.get("wdkBtcAccountIndex"),
        wdk_evm_service_url=config.get("wdkEvmServiceUrl"),
        wdk_evm_wallet_id=config.get("wdkEvmWalletId"),
        wdk_evm_account_index=config.get("wdkEvmAccountIndex"),
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
        backend=config.get("backend"),
        sign_only=config.get("signOnly"),
        network=config.get("network"),
        rpc_url=config.get("rpcUrl"),
        wdk_btc_service_url=config.get("wdkBtcServiceUrl"),
        wdk_btc_wallet_id=config.get("wdkBtcWalletId"),
        wdk_btc_account_index=config.get("wdkBtcAccountIndex"),
        wdk_evm_service_url=config.get("wdkEvmServiceUrl"),
        wdk_evm_wallet_id=config.get("wdkEvmWalletId"),
        wdk_evm_account_index=config.get("wdkEvmAccountIndex"),
    )
    result = await context.adapter.invoke(tool_name, arguments)
    return result.model_dump()


async def _run_issue_approval(
    user_id: str,
    tool_name: str,
    summary: dict[str, Any],
    config: dict[str, Any],
    *,
    mainnet_confirmed: bool = False,
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    from agent_wallet.openclaw_runtime import onboard_openclaw_user_wallet

    context = onboard_openclaw_user_wallet(
        user_id,
        backend=config.get("backend"),
        sign_only=config.get("signOnly"),
        network=config.get("network"),
        rpc_url=config.get("rpcUrl"),
        wdk_btc_service_url=config.get("wdkBtcServiceUrl"),
        wdk_btc_wallet_id=config.get("wdkBtcWalletId"),
        wdk_btc_account_index=config.get("wdkBtcAccountIndex"),
        wdk_evm_service_url=config.get("wdkEvmServiceUrl"),
        wdk_evm_wallet_id=config.get("wdkEvmWalletId"),
        wdk_evm_account_index=config.get("wdkEvmAccountIndex"),
    )
    token = context.issue_execute_approval(
        tool_name=tool_name,
        confirmation_summary=summary,
        mainnet_confirmed=mainnet_confirmed,
        ttl_seconds=ttl_seconds,
    )
    return {
        "ok": True,
        "tool": tool_name,
        "network": str(getattr(context.backend, "network", "unknown")),
        "approval_token": token,
        "confirmation_summary": summary,
        "mainnet_confirmed": bool(mainnet_confirmed),
        "ttl_seconds": ttl_seconds,
    }


def _run_autonomous_permission(action: str, scope: str) -> dict[str, Any]:
    from agent_wallet import autonomous_permissions

    normalized_scope = str(scope or "").strip()
    if normalized_scope != autonomous_permissions.BASE_SWAP_SCOPE:
        raise WalletBackendError("Only scope=base_swaps is currently supported.")

    normalized_action = str(action or "").strip().lower()
    if normalized_action == "approve":
        return {
            "ok": True,
            "action": normalized_action,
            "data": autonomous_permissions.approve_base_swaps(approved_by="openclaw_cli"),
        }
    if normalized_action == "revoke":
        return {
            "ok": True,
            "action": normalized_action,
            "data": autonomous_permissions.revoke_base_swaps(),
        }
    if normalized_action == "status":
        return {
            "ok": True,
            "action": normalized_action,
            "data": autonomous_permissions.status(),
        }
    raise WalletBackendError("action must be approve, revoke, or status.")


async def _run_btc_wallet_get(user_id: str, config: dict[str, Any]) -> dict[str, Any]:
    from agent_wallet.btc_user_wallets import get_user_btc_wallet_binding

    return {
        "ok": True,
        "wallet": get_user_btc_wallet_binding(
            user_id,
            network=config.get("network"),
        ),
    }


async def _run_btc_wallet_create(
    user_id: str,
    config: dict[str, Any],
    *,
    label: str | None,
    reveal_seed: bool,
    password: str,
) -> dict[str, Any]:
    from agent_wallet.btc_user_wallets import create_user_btc_wallet

    return {
        "ok": True,
        "wallet": create_user_btc_wallet(
            user_id,
            password=password,
            label=label,
            network=config.get("network"),
            service_url=config.get("wdkBtcServiceUrl"),
            reveal_seed_phrase=reveal_seed,
            account_index=config.get("wdkBtcAccountIndex"),
        ),
    }


async def _run_btc_wallet_import(
    user_id: str,
    config: dict[str, Any],
    *,
    label: str | None,
    password: str,
    seed_phrase: str,
) -> dict[str, Any]:
    from agent_wallet.btc_user_wallets import import_user_btc_wallet

    return {
        "ok": True,
        "wallet": import_user_btc_wallet(
            user_id,
            password=password,
            seed_phrase=seed_phrase,
            label=label,
            network=config.get("network"),
            service_url=config.get("wdkBtcServiceUrl"),
            account_index=config.get("wdkBtcAccountIndex"),
        ),
    }


async def _run_btc_wallet_unlock(
    user_id: str,
    config: dict[str, Any],
    *,
    password: str,
) -> dict[str, Any]:
    from agent_wallet.btc_user_wallets import unlock_user_btc_wallet

    return {
        "ok": True,
        "wallet": unlock_user_btc_wallet(
            user_id,
            password=password,
            network=config.get("network"),
            service_url=config.get("wdkBtcServiceUrl"),
        ),
    }


async def _run_btc_wallet_lock(user_id: str, config: dict[str, Any]) -> dict[str, Any]:
    from agent_wallet.btc_user_wallets import lock_user_btc_wallet

    return {
        "ok": True,
        "wallet": lock_user_btc_wallet(
            user_id,
            network=config.get("network"),
            service_url=config.get("wdkBtcServiceUrl"),
        ),
    }


async def _run_evm_wallet_get(user_id: str, config: dict[str, Any]) -> dict[str, Any]:
    from agent_wallet.evm_user_wallets import resolve_user_evm_wallet_binding

    return {
        "ok": True,
        "wallet": resolve_user_evm_wallet_binding(
            user_id,
            network=config.get("network"),
            service_url=config.get("wdkEvmServiceUrl"),
            wallet_id=config.get("wdkEvmWalletId"),
            account_index=config.get("wdkEvmAccountIndex"),
        ),
    }


async def _run_evm_wallet_create(
    user_id: str,
    config: dict[str, Any],
    *,
    label: str | None,
    reveal_seed: bool,
    password: str,
) -> dict[str, Any]:
    from agent_wallet.evm_user_wallets import create_user_evm_wallet

    return {
        "ok": True,
        "wallet": create_user_evm_wallet(
            user_id,
            password=password,
            label=label,
            network=config.get("network"),
            service_url=config.get("wdkEvmServiceUrl"),
            reveal_seed_phrase=reveal_seed,
            account_index=config.get("wdkEvmAccountIndex"),
        ),
    }


async def _run_evm_wallet_import(
    user_id: str,
    config: dict[str, Any],
    *,
    label: str | None,
    password: str,
    seed_phrase: str,
) -> dict[str, Any]:
    from agent_wallet.evm_user_wallets import import_user_evm_wallet

    return {
        "ok": True,
        "wallet": import_user_evm_wallet(
            user_id,
            password=password,
            seed_phrase=seed_phrase,
            label=label,
            network=config.get("network"),
            service_url=config.get("wdkEvmServiceUrl"),
            account_index=config.get("wdkEvmAccountIndex"),
        ),
    }


async def _run_evm_wallet_unlock(
    user_id: str,
    config: dict[str, Any],
    *,
    password: str,
) -> dict[str, Any]:
    from agent_wallet.evm_user_wallets import unlock_user_evm_wallet

    return {
        "ok": True,
        "wallet": unlock_user_evm_wallet(
            user_id,
            password=password,
            network=config.get("network"),
            service_url=config.get("wdkEvmServiceUrl"),
            wallet_id=config.get("wdkEvmWalletId"),
            account_index=config.get("wdkEvmAccountIndex"),
        ),
    }


async def _run_evm_wallet_lock(user_id: str, config: dict[str, Any]) -> dict[str, Any]:
    from agent_wallet.evm_user_wallets import lock_user_evm_wallet

    return {
        "ok": True,
        "wallet": lock_user_evm_wallet(
            user_id,
            network=config.get("network"),
            service_url=config.get("wdkEvmServiceUrl"),
            wallet_id=config.get("wdkEvmWalletId"),
            account_index=config.get("wdkEvmAccountIndex"),
        ),
    }


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

    approval_parser = subparsers.add_parser("issue-approval")
    approval_parser.add_argument("--user-id", required=True)
    approval_parser.add_argument("--tool", required=True)
    approval_parser.add_argument("--summary-json", required=True)
    approval_parser.add_argument("--mainnet-confirmed", action="store_true")
    approval_parser.add_argument("--ttl-seconds", type=int)
    approval_parser.add_argument("--config-json", default="{}")

    autonomous_permission_parser = subparsers.add_parser("autonomous-permission")
    autonomous_permission_parser.add_argument("--action", choices=["approve", "revoke", "status"], required=True)
    autonomous_permission_parser.add_argument("--scope", choices=["base_swaps"], required=True)
    autonomous_permission_parser.add_argument("--config-json", default="{}")

    btc_get_parser = subparsers.add_parser("btc-wallet-get")
    btc_get_parser.add_argument("--user-id", required=True)
    btc_get_parser.add_argument("--config-json", default="{}")

    btc_create_parser = subparsers.add_parser("btc-wallet-create")
    btc_create_parser.add_argument("--user-id", required=True)
    btc_create_parser.add_argument("--label")
    btc_create_parser.add_argument("--reveal-seed", action="store_true")
    btc_create_parser.add_argument("--password-stdin", action="store_true")
    btc_create_parser.add_argument("--config-json", default="{}")

    btc_import_parser = subparsers.add_parser("btc-wallet-import")
    btc_import_parser.add_argument("--user-id", required=True)
    btc_import_parser.add_argument("--label")
    btc_import_parser.add_argument("--password-stdin", action="store_true")
    btc_import_parser.add_argument("--seed-stdin", action="store_true")
    btc_import_parser.add_argument("--config-json", default="{}")

    btc_unlock_parser = subparsers.add_parser("btc-wallet-unlock")
    btc_unlock_parser.add_argument("--user-id", required=True)
    btc_unlock_parser.add_argument("--password-stdin", action="store_true")
    btc_unlock_parser.add_argument("--config-json", default="{}")

    btc_lock_parser = subparsers.add_parser("btc-wallet-lock")
    btc_lock_parser.add_argument("--user-id", required=True)
    btc_lock_parser.add_argument("--config-json", default="{}")

    evm_get_parser = subparsers.add_parser("evm-wallet-get")
    evm_get_parser.add_argument("--user-id", required=True)
    evm_get_parser.add_argument("--config-json", default="{}")

    evm_create_parser = subparsers.add_parser("evm-wallet-create")
    evm_create_parser.add_argument("--user-id", required=True)
    evm_create_parser.add_argument("--label")
    evm_create_parser.add_argument("--reveal-seed", action="store_true")
    evm_create_parser.add_argument("--password-stdin", action="store_true")
    evm_create_parser.add_argument("--config-json", default="{}")

    evm_import_parser = subparsers.add_parser("evm-wallet-import")
    evm_import_parser.add_argument("--user-id", required=True)
    evm_import_parser.add_argument("--label")
    evm_import_parser.add_argument("--password-stdin", action="store_true")
    evm_import_parser.add_argument("--seed-stdin", action="store_true")
    evm_import_parser.add_argument("--config-json", default="{}")

    evm_unlock_parser = subparsers.add_parser("evm-wallet-unlock")
    evm_unlock_parser.add_argument("--user-id", required=True)
    evm_unlock_parser.add_argument("--password-stdin", action="store_true")
    evm_unlock_parser.add_argument("--config-json", default="{}")

    evm_lock_parser = subparsers.add_parser("evm-wallet-lock")
    evm_lock_parser.add_argument("--user-id", required=True)
    evm_lock_parser.add_argument("--config-json", default="{}")

    args = parser.parse_args()

    try:
        config = _load_json(getattr(args, "config_json", "{}"))
        _apply_config_overrides(config)

        if args.command == "onboard":
            payload = asyncio.run(_run_onboard(args.user_id, config))
        elif args.command == "issue-approval":
            payload = asyncio.run(
                _run_issue_approval(
                    args.user_id,
                    args.tool,
                    _load_json(args.summary_json),
                    config,
                    mainnet_confirmed=bool(args.mainnet_confirmed),
                    ttl_seconds=args.ttl_seconds,
                )
            )
        elif args.command == "autonomous-permission":
            payload = _run_autonomous_permission(args.action, args.scope)
        elif args.command == "btc-wallet-get":
            payload = asyncio.run(_run_btc_wallet_get(args.user_id, config))
        elif args.command == "btc-wallet-create":
            if not args.password_stdin:
                raise WalletBackendError("btc-wallet-create requires --password-stdin.")
            payload = asyncio.run(
                _run_btc_wallet_create(
                    args.user_id,
                    config,
                    label=args.label,
                    reveal_seed=bool(args.reveal_seed),
                    password=_read_stdin_secret("password"),
                )
            )
        elif args.command == "btc-wallet-import":
            if not args.password_stdin:
                raise WalletBackendError("btc-wallet-import requires --password-stdin.")
            if not args.seed_stdin:
                raise WalletBackendError("btc-wallet-import requires --seed-stdin.")
            raw = _read_stdin_secret("password and seed phrase payload")
            lines = raw.splitlines()
            if len(lines) < 2:
                raise WalletBackendError(
                    "btc-wallet-import stdin must contain password on the first line and seed phrase on the remaining lines."
                )
            password = lines[0].strip()
            seed_phrase = " ".join(line.strip() for line in lines[1:] if line.strip())
            if not password or not seed_phrase:
                raise WalletBackendError("btc-wallet-import requires both password and seed phrase on stdin.")
            payload = asyncio.run(
                _run_btc_wallet_import(
                    args.user_id,
                    config,
                    label=args.label,
                    password=password,
                    seed_phrase=seed_phrase,
                )
            )
        elif args.command == "btc-wallet-unlock":
            if not args.password_stdin:
                raise WalletBackendError("btc-wallet-unlock requires --password-stdin.")
            payload = asyncio.run(
                _run_btc_wallet_unlock(
                    args.user_id,
                    config,
                    password=_read_stdin_secret("password"),
                )
            )
        elif args.command == "btc-wallet-lock":
            payload = asyncio.run(_run_btc_wallet_lock(args.user_id, config))
        elif args.command == "evm-wallet-get":
            payload = asyncio.run(_run_evm_wallet_get(args.user_id, config))
        elif args.command == "evm-wallet-create":
            if not args.password_stdin:
                raise WalletBackendError("evm-wallet-create requires --password-stdin.")
            payload = asyncio.run(
                _run_evm_wallet_create(
                    args.user_id,
                    config,
                    label=args.label,
                    reveal_seed=bool(args.reveal_seed),
                    password=_read_stdin_secret("password"),
                )
            )
        elif args.command == "evm-wallet-import":
            if not args.password_stdin:
                raise WalletBackendError("evm-wallet-import requires --password-stdin.")
            if not args.seed_stdin:
                raise WalletBackendError("evm-wallet-import requires --seed-stdin.")
            raw = _read_stdin_secret("password and seed phrase payload")
            lines = raw.splitlines()
            if len(lines) < 2:
                raise WalletBackendError(
                    "evm-wallet-import stdin must contain password on the first line and seed phrase on the remaining lines."
                )
            password = lines[0].strip()
            seed_phrase = " ".join(line.strip() for line in lines[1:] if line.strip())
            if not password or not seed_phrase:
                raise WalletBackendError("evm-wallet-import requires both password and seed phrase on stdin.")
            payload = asyncio.run(
                _run_evm_wallet_import(
                    args.user_id,
                    config,
                    label=args.label,
                    password=password,
                    seed_phrase=seed_phrase,
                )
            )
        elif args.command == "evm-wallet-unlock":
            if not args.password_stdin:
                raise WalletBackendError("evm-wallet-unlock requires --password-stdin.")
            payload = asyncio.run(
                _run_evm_wallet_unlock(
                    args.user_id,
                    config,
                    password=_read_stdin_secret("password"),
                )
            )
        elif args.command == "evm-wallet-lock":
            payload = asyncio.run(_run_evm_wallet_lock(args.user_id, config))
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
        # Anonymous adoption telemetry for tool invocations only (never for
        # onboard/wallet-create/unlock/import — those touch secrets). Records
        # just the tool name + backend family + failure flag; never raises.
        if getattr(args, "command", "") == "invoke":
            _telemetry_record(
                getattr(args, "tool", ""),
                backend=str(locals().get("config", {}).get("backend", "") or ""),
                ok=False,
            )
        error_payload: dict[str, Any] = {"ok": False, "error": str(exc)}
        if isinstance(exc, WalletBackendError):
            if exc.code:
                error_payload["code"] = exc.code
            if exc.details is not None:
                error_payload["details"] = exc.details
        print(json.dumps(error_payload), file=sys.stderr)
        return 1

    if getattr(args, "command", "") == "invoke":
        _telemetry_record(
            getattr(args, "tool", ""),
            backend=str(config.get("backend", "") or ""),
            ok=True,
        )

    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
