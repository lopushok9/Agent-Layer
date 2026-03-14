"""Patch an OpenClaw config file for the agent-wallet plugin."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from agent_wallet.file_ops import atomic_write_text, chmod_if_exists
from security_utils import write_redacted_backup

OPTIONAL_TOOLS = [
    "sign_wallet_message",
    "transfer_sol",
    "transfer_spl_token",
    "swap_solana_tokens",
    "close_empty_token_accounts",
    "request_devnet_airdrop",
]


def _default_config_path() -> Path:
    return Path(os.path.expanduser("~/.openclaw/openclaw.json"))


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_extension_path() -> Path:
    return _repo_root() / ".openclaw" / "extensions" / "agent-wallet"


def _default_package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_python_bin() -> str:
    return os.getenv("OPENCLAW_AGENT_WALLET_PYTHON", sys.executable)


def _default_user_id() -> str:
    return f"{os.getenv('USER', 'openclaw-user')}-local"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-path", default=str(_default_config_path()))
    parser.add_argument("--plugin-id", default="agent-wallet")
    parser.add_argument("--user-id", default=_default_user_id())
    parser.add_argument("--backend", default="solana_local")
    parser.add_argument("--network", default="devnet")
    parser.add_argument("--rpc-url", default="")
    parser.add_argument("--rpc-urls", default="")
    parser.add_argument("--sign-only", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--encrypt-user-wallets", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--migrate-plaintext-user-wallets",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--extension-path", default=str(_default_extension_path()))
    parser.add_argument("--package-root", default=str(_default_package_root()))
    parser.add_argument("--python-bin", default=_default_python_bin())
    parser.add_argument("--write-master-key", action=argparse.BooleanOptionalAction, default=False)
    return parser


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

    load = plugins.setdefault("load", {})
    paths = load.setdefault("paths", [])
    extension_path_text = str(Path(args.extension_path).expanduser().resolve())
    if extension_path_text not in paths:
        paths.append(extension_path_text)

    entries = plugins.setdefault("entries", {})
    plugin_config = {
        "userId": args.user_id,
        "backend": args.backend,
        "network": args.network,
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
    if args.write_master_key:
        raise SystemExit(
            "Refusing to write masterKey into config. Provide AGENT_WALLET_MASTER_KEY via protected environment injection instead."
        )

    entries[args.plugin_id] = {
        "enabled": True,
        "config": plugin_config,
    }

    tools = data.setdefault("tools", {})
    also_allow = tools.setdefault("alsoAllow", [])
    for tool_name in OPTIONAL_TOOLS:
        if tool_name not in also_allow:
            also_allow.append(tool_name)

    atomic_write_text(config_path, json.dumps(data, indent=2) + "\n", mode=0o600)
    chmod_if_exists(config_path, 0o600)

    print(
        json.dumps(
            {
                "ok": True,
                "config_path": str(config_path),
                "backup_path": str(backup_path),
                "extension_path": extension_path_text,
                "python_bin": args.python_bin,
                "package_root": plugin_config["packageRoot"],
                "plugin_id": args.plugin_id,
                "user_id": args.user_id,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
