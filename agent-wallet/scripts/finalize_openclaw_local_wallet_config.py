"""Finalize an OpenClaw agent-wallet config with a persistent master key."""

from __future__ import annotations

import argparse
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from agent_wallet.file_ops import atomic_write_text, chmod_if_exists
from agent_wallet.user_wallets import resolve_user_wallet_path, rotate_user_wallet_encryption
from security_utils import write_redacted_backup


def _default_config_path() -> Path:
    return Path(os.path.expanduser("~/.openclaw/openclaw.json"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-path", default=str(_default_config_path()))
    parser.add_argument("--plugin-id", default="agent-wallet")
    parser.add_argument("--user-id")
    parser.add_argument("--network")
    parser.add_argument(
        "--current-master-key",
        default="",
        help="Deprecated insecure path. Use AGENT_WALLET_CURRENT_MASTER_KEY env instead.",
    )
    parser.add_argument(
        "--new-master-key",
        default="",
        help="Deprecated insecure path. Use AGENT_WALLET_NEW_MASTER_KEY env instead.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config_path = Path(args.config_path).expanduser()
    data = json.loads(config_path.read_text(encoding="utf-8"))
    plugin_config = data["plugins"]["entries"][args.plugin_id]["config"]

    backup_path = config_path.with_name(
        f"{config_path.name}.bak.agent-wallet-finalize.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    write_redacted_backup(backup_path, data)

    existing_master_key = str(plugin_config.get("masterKey") or "").strip()
    if existing_master_key:
        raise SystemExit(
            "masterKey stored in config is no longer supported. Remove it and supply AGENT_WALLET_MASTER_KEY via protected environment injection."
        )

    current_master_key = args.current_master_key.strip() or os.getenv("AGENT_WALLET_CURRENT_MASTER_KEY", "").strip()
    new_master_key_arg = args.new_master_key.strip() or os.getenv("AGENT_WALLET_NEW_MASTER_KEY", "").strip()
    if args.current_master_key.strip() or args.new_master_key.strip():
        raise SystemExit(
            "Passing master keys via command-line arguments is insecure. Use AGENT_WALLET_CURRENT_MASTER_KEY / AGENT_WALLET_NEW_MASTER_KEY environment variables instead."
        )

    user_id = args.user_id or str(plugin_config.get("userId") or "").strip()
    if not user_id:
        raise SystemExit("user_id is required either as an argument or in plugin config.")

    network = args.network or str(plugin_config.get("network") or "mainnet").strip() or "mainnet"
    wallet_path = resolve_user_wallet_path(user_id, network=network)
    new_master_key = new_master_key_arg or secrets.token_hex(32)

    rotated_wallet = False
    if wallet_path.exists():
        if not current_master_key:
            raise SystemExit(
                "AGENT_WALLET_CURRENT_MASTER_KEY is required to rotate an existing encrypted user wallet."
            )
        rotate_user_wallet_encryption(
            user_id,
            network=network,
            current_master_key=current_master_key,
            new_master_key=new_master_key,
        )
        rotated_wallet = True

    plugin_config.pop("masterKey", None)
    atomic_write_text(config_path, json.dumps(data, indent=2) + "\n", mode=0o600)
    chmod_if_exists(config_path, 0o600)

    print(
        json.dumps(
            {
                "ok": True,
                "config_path": str(config_path),
                "backup_path": str(backup_path),
                "master_key_present": True,
                "rotated_wallet": rotated_wallet,
                "user_id": user_id,
                "network": network,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
