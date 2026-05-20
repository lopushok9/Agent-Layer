"""Create or update the encrypted sealed_keys.json secret bundle."""

from __future__ import annotations

import argparse
import json
import os
import secrets as py_secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.sealed_keys import resolve_sealed_keys_path, seal_keys, unseal_keys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--replace",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Replace the sealed bundle instead of merging with existing entries.",
    )
    parser.add_argument(
        "--boot-key",
        default="",
        help="Deprecated insecure path. Use AGENT_WALLET_BOOT_KEY env instead.",
    )
    parser.add_argument(
        "--master-key",
        default="",
        help="Deprecated insecure path. Use AGENT_WALLET_MASTER_KEY env instead.",
    )
    parser.add_argument(
        "--approval-secret",
        default="",
        help="Deprecated insecure path. Use AGENT_WALLET_APPROVAL_SECRET env instead.",
    )
    parser.add_argument(
        "--private-key",
        default="",
        help="Deprecated insecure path. Use SOLANA_AGENT_PRIVATE_KEY env instead.",
    )
    return parser


def _collect_secret_updates() -> dict[str, str]:
    updates: dict[str, str] = {}
    master_key = os.getenv("AGENT_WALLET_MASTER_KEY", "").strip()
    approval_secret = os.getenv("AGENT_WALLET_APPROVAL_SECRET", "").strip()
    private_key = os.getenv("SOLANA_AGENT_PRIVATE_KEY", "").strip()
    evm_wallet_password = os.getenv("WDK_EVM_WALLET_PASSWORD", "").strip()
    if master_key:
        updates["master_key"] = master_key
    if approval_secret:
        updates["approval_secret"] = approval_secret
    if private_key:
        updates["private_key"] = private_key
    if evm_wallet_password:
        updates["wdk_evm_wallet_password"] = evm_wallet_password
    return updates


def main() -> None:
    args = build_parser().parse_args()
    if (
        args.boot_key.strip()
        or args.master_key.strip()
        or args.approval_secret.strip()
        or args.private_key.strip()
    ):
        raise SystemExit(
            "Passing secrets via command-line arguments is insecure. "
            "Use AGENT_WALLET_BOOT_KEY / AGENT_WALLET_MASTER_KEY / "
            "AGENT_WALLET_APPROVAL_SECRET / SOLANA_AGENT_PRIVATE_KEY environment variables instead."
        )

    boot_key = os.getenv("AGENT_WALLET_BOOT_KEY", "").strip()
    if not boot_key:
        raise SystemExit("AGENT_WALLET_BOOT_KEY is required.")

    updates = _collect_secret_updates()
    sealed_path = resolve_sealed_keys_path()
    existing = unseal_keys(boot_key) if sealed_path.exists() and not args.replace else {}
    secrets = {**existing, **updates}
    generated_keys: list[str] = []
    if "wdk_evm_wallet_password" not in secrets:
        secrets["wdk_evm_wallet_password"] = py_secrets.token_urlsafe(24)
        generated_keys.append("wdk_evm_wallet_password")
    if not secrets:
        raise SystemExit(
            "No secrets provided. Set AGENT_WALLET_MASTER_KEY, AGENT_WALLET_APPROVAL_SECRET, "
            "and/or SOLANA_AGENT_PRIVATE_KEY in the environment."
        )

    path = seal_keys(boot_key, secrets)
    print(
        json.dumps(
            {
                "ok": True,
                "path": str(path),
                "stored_keys": sorted(secrets.keys()),
                "updated_keys": sorted(set(updates.keys()) | set(generated_keys)),
                "replaced": bool(args.replace),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
