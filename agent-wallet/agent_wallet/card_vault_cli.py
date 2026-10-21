"""Human CLI for card retrieval. Secrets are never accepted as command arguments."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path

from agent_wallet.card_vault import CardVault, VERSION
from agent_wallet.card_catalog import CardCatalog
from agent_wallet.config import resolve_card_vault_user_id
from agent_wallet.laso_card_vault import card_object, refresh_record, summary
from agent_wallet.wallet_layer.base import WalletBackendError


def require_terminal() -> None:
    # Terminal checks prevent accidental logging; macOS authenticates the owner.
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise WalletBackendError("Run this command in your own interactive terminal; redirected secret output is disabled.")


def owner_summary(record: dict, reference: str) -> dict:
    result = summary(record, reference)
    card = card_object(record.get("latest") or record.get("order") or {})
    result.update({
        "card_id": card.get("card_id"),
        "card_type": record.get("card_type"),
        "created_at": record.get("created_at"),
        "receipt_state": record.get("state"),
        "http_status": record.get("http_status"),
    })
    payment = record.get("payment_result")
    if isinstance(payment, dict):
        result["payment"] = payment
    return result


def import_owner_record(vault: CardVault, reference: str, record: dict) -> None:
    """An authenticated owner can populate metadata/jobs for older vault records."""
    from agent_wallet.card_runtime_secrets import CardRuntimeSecrets

    catalog = CardCatalog(vault)
    try:
        CardRuntimeSecrets(vault).capture(reference, record)
    except WalletBackendError:
        pass
    path = catalog._path(reference)
    try:
        if path.exists() or path.is_symlink():
            catalog.load(reference)
            return
    except WalletBackendError:
        pass
    try:
        catalog.track(reference, record)
    except WalletBackendError:
        # An unavailable runtime master must not prevent owner-only reveal.
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wallet vault")
    parser.add_argument("command", choices=["kernel-connect", "kernel-status", "kernel-disconnect", "provision", "init", "migrate", "status", "list", "show", "reveal", "refresh", "remove", "change-password"])
    parser.add_argument("reference", nargs="?")
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--output", type=Path, help="Explicitly export card details to a NEW private JSON file (reveal only).")
    args = parser.parse_args(argv)
    try:
        if args.command.startswith("kernel-"):
            if args.reference or args.output or args.user_id:
                raise WalletBackendError("Kernel connection is shared by the local runtime and accepts no card arguments.")
            from agent_wallet.kernel_cli import run
            return run(args.command)
        vault = CardVault(args.user_id or resolve_card_vault_user_id())
        if args.output and args.command != "reveal":
            raise WalletBackendError("--output is only valid with reveal.")
        if args.command in {"show", "reveal", "refresh", "remove"} and not args.reference:
            raise WalletBackendError("A vault reference is required.")
        if args.command == "status":
            config = vault._config() if vault.config_path.exists() else {}
            print(json.dumps({"initialized": bool(config), "protection": config.get("protection", "legacy-password" if config else None), "scope": vault.scope, "path": str(vault.root)}))
            return 0
        if args.command in {"provision", "init"}:
            result = vault.ensure_system()
            print(json.dumps({"ok": True, **result}))
            return 0
        if args.command == "change-password":
            raise WalletBackendError("The card vault uses your macOS login Keychain password. Manage it in system Keychain settings.")
        require_terminal()
        vault.ensure_system()
        if vault._config()["version"] == VERSION:
            password = getpass.getpass("Previous vault password (one-time migration): ")
            private_key = vault.migrate_to_system(password)
            del password
        else:
            private_key = vault.unlock()
        if args.command == "migrate":
            print("Card vault uses macOS login Keychain authentication.")
            return 0
        with vault.owner_lock():
            if args.command == "list":
                cards = []
                for ref in vault.references():
                    with vault.record_lock(ref):
                        record = vault.read(ref, private_key)
                        import_owner_record(vault, ref, record)
                        cards.append(owner_summary(record, ref))
                print(json.dumps(cards, indent=2))
                return 0
            record = vault.read(args.reference, private_key)
            if args.command == "refresh":
                with vault.record_lock(args.reference):
                    record = vault.read(args.reference, private_key)
                    record = asyncio.run(refresh_record(vault, args.reference, record))
            if args.command == "remove":
                if input(f"Type {args.reference} to remove the local encrypted record: ") != args.reference:
                    raise WalletBackendError("Removal cancelled.")
                with vault.record_lock(args.reference):
                    vault.remove_record(args.reference)
                print("Local record removed. The Laso card has not been cancelled.")
                return 0
            if args.command != "refresh":
                with vault.record_lock(args.reference):
                    record = vault.read(args.reference, private_key)
                    import_owner_record(vault, args.reference, record)
            result = owner_summary(record, args.reference)
            if args.command == "reveal":
                card = card_object(record.get("latest") or record.get("order") or {})
                details = card.get("card_details")
                if not isinstance(details, dict) or not details.get("card_number"):
                    raise WalletBackendError("Card details are not ready. Use wallet vault refresh <reference>.")
                # Never reveal provider tokens, unexpected response fields, or payment credentials.
                result = {"vault_reference": args.reference, "card_details": {k: details[k] for k in ("card_number", "exp_month", "exp_year", "cvv", "available_balance", "billing_address") if k in details}}
                if args.output:
                    requested = args.output.expanduser().absolute()
                    destination = requested.parent.resolve() / requested.name
                    if destination.is_relative_to(vault.root.resolve()):
                        raise WalletBackendError("Export outside the encrypted vault directory.")
                    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        json.dump(result, handle, indent=2)
                        handle.flush()
                        os.fsync(handle.fileno())
                    print("Card exported to a private plaintext JSON file. Remove it after use.")
                    return 0
            print(json.dumps(result, indent=2))
        return 0
    except WalletBackendError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError):
        # No traceback, provider body, password or token can enter shell logs.
        print("Vault command failed. Check user ID, system Keychain access, record reference and file permissions. For pending cards, retry refresh later.", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("Vault command cancelled.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
