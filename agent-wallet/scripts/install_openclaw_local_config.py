"""Patch an OpenClaw config file for the AgentLayer OpenClaw plugins."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.file_ops import atomic_write_text, chmod_if_exists
from agent_wallet.sealed_keys import resolve_sealed_keys_path, seal_keys, unseal_keys
from security_utils import write_redacted_backup

OPTIONAL_TOOLS = [
    "get_wallet_capabilities",
    "get_wallet_address",
    "get_wallet_balance",
    "get_active_wallet_backend",
    "set_wallet_backend",
    "get_wallet_portfolio",
    "get_solana_token_prices",
    "swap_solana_privately",
    "continue_solana_private_swap",
    "list_pending_solana_private_swaps",
    "get_solana_private_swap_status",
    "get_kamino_lend_markets",
    "get_kamino_lend_market_reserves",
    "get_kamino_lend_user_obligations",
    "get_kamino_lend_user_rewards",
    "kamino_lend_deposit",
    "kamino_lend_withdraw",
    "kamino_lend_borrow",
    "kamino_lend_repay",
    "sign_wallet_message",
    "transfer_sol",
    "transfer_btc",
    "transfer_spl_token",
    "swap_solana_tokens",
    "close_empty_token_accounts",
    "request_devnet_airdrop",
]

PAY_BRIDGE_PLUGIN_ID = "pay-bridge"
PAY_BRIDGE_TOOLS = [
    "pay_status",
    "pay_wallet_info",
    "pay_search_services",
    "pay_get_service_endpoints",
    "pay_api_request",
]


def _default_config_path() -> Path:
    return Path(os.path.expanduser("~/.openclaw/openclaw.json"))


def _resolve_openclaw_home() -> Path:
    return Path(os.path.expanduser(os.getenv("OPENCLAW_HOME", "~/.openclaw")))


def _default_runtime_root() -> Path:
    explicit_target = os.getenv("OPENCLAW_INSTALL_TARGET", "").strip()
    if explicit_target:
        return Path(explicit_target).expanduser()
    explicit_root = os.getenv("OPENCLAW_INSTALL_ROOT", "").strip()
    if explicit_root:
        return Path(explicit_root).expanduser() / "current"
    return _resolve_openclaw_home() / "agent-wallet-runtime" / "current"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _trusted_runtime_root() -> Path | None:
    runtime_root = _default_runtime_root().resolve()
    plugin_manifest = runtime_root / ".openclaw" / "extensions" / "agent-wallet" / "openclaw.plugin.json"
    package_root = runtime_root / "agent-wallet"
    if plugin_manifest.exists() and package_root.exists():
        return runtime_root
    return None


def _default_extension_path() -> Path:
    runtime_root = _trusted_runtime_root()
    if runtime_root is not None:
        return runtime_root / ".openclaw" / "extensions" / "agent-wallet"
    return _repo_root() / ".openclaw" / "extensions" / "agent-wallet"


def _default_pay_bridge_extension_path() -> Path:
    runtime_root = _trusted_runtime_root()
    if runtime_root is not None:
        return runtime_root / ".openclaw" / "extensions" / PAY_BRIDGE_PLUGIN_ID
    return _repo_root() / ".openclaw" / "extensions" / PAY_BRIDGE_PLUGIN_ID


def _default_package_root() -> Path:
    runtime_root = _trusted_runtime_root()
    if runtime_root is not None:
        return runtime_root / "agent-wallet"
    return Path(__file__).resolve().parents[1]


def _default_python_bin() -> str:
    explicit = os.getenv("OPENCLAW_AGENT_WALLET_PYTHON", "").strip()
    if explicit:
        return explicit
    runtime_root = _trusted_runtime_root()
    if runtime_root is not None:
        wrapper = runtime_root / "agent-wallet" / ".runtime-venv" / "bin" / "openclaw-agent-wallet-python"
        if wrapper.exists():
            return str(wrapper)
        runtime_python = runtime_root / "agent-wallet" / ".runtime-venv" / "bin" / "python"
        if runtime_python.exists():
            return str(runtime_python)
    return sys.executable


def _default_pay_binary() -> str:
    explicit = os.getenv("OPENCLAW_PAY_BINARY", "").strip()
    if explicit:
        return explicit
    resolved = shutil.which("pay")
    return resolved or "pay"


def _default_user_id() -> str:
    return f"{os.getenv('USER', 'openclaw-user')}-local"


def _normalize_network(backend: str, network: str) -> str:
    backend_name = backend.strip().lower()
    normalized = network.strip().lower()
    if backend_name in {"wdk_btc_local", "wdk-btc-local", "btc_local", "btc-local"}:
        if normalized == "mainnet":
            return "bitcoin"
        return normalized or "bitcoin"
    return normalized or "devnet"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-path", default=str(_default_config_path()))
    parser.add_argument("--plugin-id", default="agent-wallet")
    parser.add_argument("--user-id", default="")
    parser.add_argument("--backend", default="solana_local")
    parser.add_argument("--network", default="devnet")
    parser.add_argument("--rpc-url", default="")
    parser.add_argument("--rpc-urls", default="")
    parser.add_argument("--wdk-btc-service-url", default="")
    parser.add_argument("--wdk-btc-wallet-id", default="")
    parser.add_argument("--wdk-btc-account-index", type=int, default=0)
    parser.add_argument("--wdk-evm-service-url", default="")
    parser.add_argument("--wdk-evm-wallet-id", default="")
    parser.add_argument("--wdk-evm-account-index", type=int, default=0)
    parser.add_argument("--sign-only", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--encrypt-user-wallets", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--migrate-plaintext-user-wallets",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--extension-path", default=str(_default_extension_path()))
    parser.add_argument("--pay-bridge-extension-path", default=str(_default_pay_bridge_extension_path()))
    parser.add_argument("--package-root", default=str(_default_package_root()))
    parser.add_argument("--python-bin", default=_default_python_bin())
    parser.add_argument("--pay-binary", default=_default_pay_binary())
    parser.add_argument("--write-master-key", action=argparse.BooleanOptionalAction, default=False)
    return parser


def _collect_sealed_secret_updates() -> dict[str, str]:
    updates: dict[str, str] = {}
    master_key = os.getenv("AGENT_WALLET_MASTER_KEY", "").strip()
    approval_secret = os.getenv("AGENT_WALLET_APPROVAL_SECRET", "").strip()
    private_key = os.getenv("SOLANA_AGENT_PRIVATE_KEY", "").strip()
    if master_key:
        updates["master_key"] = master_key
    if approval_secret:
        updates["approval_secret"] = approval_secret
    if private_key:
        updates["private_key"] = private_key
    return updates


def _maybe_install_sealed_keys() -> str | None:
    boot_key = os.getenv("AGENT_WALLET_BOOT_KEY", "").strip()
    if not boot_key:
        return None
    updates = _collect_sealed_secret_updates()
    if not updates:
        return None
    sealed_path = resolve_sealed_keys_path()
    existing = unseal_keys(boot_key) if sealed_path.exists() else {}
    return str(seal_keys(boot_key, {**existing, **updates}))


def _require_hardened_runtime_secrets(backend: str) -> str | None:
    if backend.strip().lower() in {"", "none"}:
        return None

    boot_key = os.getenv("AGENT_WALLET_BOOT_KEY", "").strip()
    if not boot_key:
        raise SystemExit(
            "AGENT_WALLET_BOOT_KEY is required. Runtime secrets must be loaded from sealed_keys.json."
        )

    sealed_path = resolve_sealed_keys_path()
    if not sealed_path.exists():
        raise SystemExit(
            "sealed_keys.json was not created. Provide AGENT_WALLET_MASTER_KEY and "
            "AGENT_WALLET_APPROVAL_SECRET during install so the installer can seal them."
        )

    secrets = unseal_keys(boot_key)
    missing = [name for name in ("master_key", "approval_secret") if not str(secrets.get(name) or "").strip()]
    if missing:
        raise SystemExit(
            "sealed_keys.json is missing required runtime secrets: "
            + ", ".join(missing)
            + "."
        )
    return str(sealed_path)


def main() -> None:
    args = build_parser().parse_args()
    config_path = Path(args.config_path).expanduser()
    data = json.loads(config_path.read_text(encoding="utf-8"))

    backup_path = config_path.with_name(
        f"{config_path.name}.bak.agent-wallet.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    write_redacted_backup(backup_path, data)

    plugins = data.setdefault("plugins", {})
    plugins["enabled"] = True
    allow = plugins.setdefault("allow", [])
    if args.plugin_id not in allow:
        allow.append(args.plugin_id)
    if PAY_BRIDGE_PLUGIN_ID not in allow:
        allow.append(PAY_BRIDGE_PLUGIN_ID)

    load = plugins.setdefault("load", {})
    paths = load.setdefault("paths", [])
    extension_path_text = str(Path(args.extension_path).expanduser().resolve())
    if extension_path_text not in paths:
        paths.append(extension_path_text)
    pay_bridge_extension_path_text = str(Path(args.pay_bridge_extension_path).expanduser().resolve())
    if pay_bridge_extension_path_text not in paths:
        paths.append(pay_bridge_extension_path_text)

    entries = plugins.setdefault("entries", {})
    effective_network = _normalize_network(args.backend, args.network)
    existing_entry = entries.get(args.plugin_id) if isinstance(entries.get(args.plugin_id), dict) else {}
    existing_config = (
        dict(existing_entry.get("config"))
        if isinstance(existing_entry.get("config"), dict)
        else {}
    )
    resolved_user_id = (
        args.user_id.strip()
        or str(existing_config.get("userId") or "").strip()
        or _default_user_id()
    )
    plugin_config = {
        **existing_config,
        "userId": resolved_user_id,
        "backend": args.backend,
        "network": effective_network,
        "signOnly": args.sign_only,
        "encryptUserWallets": args.encrypt_user_wallets,
        "migratePlaintextUserWallets": args.migrate_plaintext_user_wallets,
        "packageRoot": str(Path(args.package_root).expanduser().resolve()),
        "pythonBin": args.python_bin,
    }
    if args.rpc_url.strip():
        plugin_config["rpcUrl"] = args.rpc_url.strip()
    if args.rpc_urls.strip():
        plugin_config["rpcUrls"] = [
            item.strip() for item in args.rpc_urls.split(",") if item.strip()
        ]
    if args.wdk_btc_service_url.strip():
        plugin_config["wdkBtcServiceUrl"] = args.wdk_btc_service_url.strip()
    if args.wdk_btc_wallet_id.strip():
        plugin_config["wdkBtcWalletId"] = args.wdk_btc_wallet_id.strip()
    if args.wdk_btc_account_index is not None:
        plugin_config["wdkBtcAccountIndex"] = int(args.wdk_btc_account_index)
    if args.wdk_evm_service_url.strip():
        plugin_config["wdkEvmServiceUrl"] = args.wdk_evm_service_url.strip()
    if args.wdk_evm_wallet_id.strip():
        plugin_config["wdkEvmWalletId"] = args.wdk_evm_wallet_id.strip()
    if args.wdk_evm_account_index is not None:
        plugin_config["wdkEvmAccountIndex"] = int(args.wdk_evm_account_index)
    if args.write_master_key:
        raise SystemExit(
            "Refusing to write masterKey into config. Runtime secrets must live in sealed_keys.json."
        )

    entries[args.plugin_id] = {
        "enabled": True,
        "config": plugin_config,
    }
    existing_pay_entry = entries.get(PAY_BRIDGE_PLUGIN_ID) if isinstance(entries.get(PAY_BRIDGE_PLUGIN_ID), dict) else {}
    existing_pay_config = (
        dict(existing_pay_entry.get("config"))
        if isinstance(existing_pay_entry.get("config"), dict)
        else {}
    )
    pay_bridge_config = {
        **existing_pay_config,
        "payBinary": args.pay_binary.strip() or _default_pay_binary(),
        "requireHttps": bool(existing_pay_config.get("requireHttps", True)),
    }
    entries[PAY_BRIDGE_PLUGIN_ID] = {
        "enabled": True,
        "config": pay_bridge_config,
    }

    tools = data.setdefault("tools", {})
    also_allow = tools.setdefault("alsoAllow", [])
    for tool_name in OPTIONAL_TOOLS + PAY_BRIDGE_TOOLS:
        if tool_name not in also_allow:
            also_allow.append(tool_name)

    atomic_write_text(config_path, json.dumps(data, indent=2) + "\n", mode=0o600)
    chmod_if_exists(config_path, 0o600)
    _maybe_install_sealed_keys()
    sealed_keys_path = _require_hardened_runtime_secrets(args.backend)

    print(
        json.dumps(
            {
                "ok": True,
                "config_path": str(config_path),
                "backup_path": str(backup_path),
                "extension_path": extension_path_text,
                "pay_bridge_extension_path": pay_bridge_extension_path_text,
                "python_bin": args.python_bin,
                "package_root": plugin_config["packageRoot"],
                "plugin_id": args.plugin_id,
                "user_id": resolved_user_id,
                "sealed_keys_path": sealed_keys_path,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
