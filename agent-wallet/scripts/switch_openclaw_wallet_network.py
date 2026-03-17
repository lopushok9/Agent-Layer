"""Switch the configured OpenClaw agent-wallet network safely."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from agent_wallet.file_ops import atomic_write_text, chmod_if_exists
from security_utils import write_redacted_backup


def _default_config_path() -> Path:
    return Path(os.path.expanduser("~/.openclaw/openclaw.json"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-path", default=str(_default_config_path()))
    parser.add_argument("--plugin-id", default="agent-wallet")
    parser.add_argument("--network", required=True, choices=["mainnet", "devnet", "testnet"])
    parser.add_argument("--rpc-url", default="")
    parser.add_argument("--rpc-urls", default="")
    parser.add_argument("--sign-only", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--show-only", action=argparse.BooleanOptionalAction, default=False)
    return parser


def _normalize_user_id(user_id: str) -> str:
    import hashlib
    import re

    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", user_id.strip())
    cleaned = cleaned.strip("-._")
    if not cleaned:
        cleaned = "user"
    digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12]
    return f"{cleaned[:48]}-{digest}"


def _resolve_wallet_path(openclaw_home: Path, user_id: str, network: str) -> Path:
    return openclaw_home / "users" / _normalize_user_id(user_id) / "wallets" / f"solana-{network}-agent.json"


def main() -> None:
    args = build_parser().parse_args()
    config_path = Path(args.config_path).expanduser()
    data = json.loads(config_path.read_text(encoding="utf-8"))

    plugin_entry = data["plugins"]["entries"][args.plugin_id]
    plugin_config = plugin_entry.setdefault("config", {})
    user_id = str(plugin_config.get("userId") or os.getenv("USER") or "openclaw-main").strip()
    openclaw_home = Path(
        str(plugin_config.get("openclawHome") or os.getenv("OPENCLAW_HOME") or "~/.openclaw")
    ).expanduser()

    wallet_path = _resolve_wallet_path(openclaw_home, user_id, args.network)
    pin_path = wallet_path.with_suffix(f"{wallet_path.suffix}.pin.json")

    result = {
        "ok": True,
        "config_path": str(config_path),
        "plugin_id": args.plugin_id,
        "user_id": user_id,
        "selected_network": args.network,
        "wallet_path": str(wallet_path),
        "wallet_exists": wallet_path.exists(),
        "wallet_pin_exists": pin_path.exists(),
        "rpc_url": args.rpc_url.strip() or str(plugin_config.get("rpcUrl") or ""),
        "rpc_urls": plugin_config.get("rpcUrls") or [],
        "sign_only": plugin_config.get("signOnly"),
        "show_only": args.show_only,
    }

    if args.show_only:
        print(json.dumps(result, indent=2))
        return

    backup_path = config_path.with_name(
        f"{config_path.name}.bak.agent-wallet-switch.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    write_redacted_backup(backup_path, data)

    plugin_config["network"] = args.network
    if args.rpc_url.strip():
        plugin_config["rpcUrl"] = args.rpc_url.strip()
    else:
        plugin_config.pop("rpcUrl", None)
    if args.rpc_urls.strip():
        plugin_config["rpcUrls"] = [item.strip() for item in args.rpc_urls.split(",") if item.strip()]
    if args.sign_only is not None:
        plugin_config["signOnly"] = args.sign_only

    atomic_write_text(config_path, json.dumps(data, indent=2) + "\n", mode=0o600)
    chmod_if_exists(config_path, 0o600)

    result["backup_path"] = str(backup_path)
    result["sign_only"] = plugin_config.get("signOnly")
    result["rpc_urls"] = plugin_config.get("rpcUrls") or []
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
