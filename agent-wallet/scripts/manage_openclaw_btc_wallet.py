#!/usr/bin/env python3
"""Host-side helper for managing a local OpenClaw BTC wallet binding."""

from __future__ import annotations

import argparse
import json
import sys
from getpass import getpass
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from agent_wallet.btc_user_wallets import (  # noqa: E402
    create_user_btc_wallet,
    get_user_btc_wallet_binding,
    import_user_btc_wallet,
    lock_user_btc_wallet,
    unlock_user_btc_wallet,
)


def _read_secret(
    *,
    prompt: str,
    confirm_prompt: str | None = None,
    stdin_mode: bool = False,
) -> str:
    if stdin_mode:
        value = sys.stdin.read().strip()
        if not value:
            raise SystemExit(f"{prompt.rstrip(':')} is required on stdin.")
        return value
    value = getpass(prompt)
    if confirm_prompt is not None:
        confirmed = getpass(confirm_prompt)
        if value != confirmed:
            raise SystemExit("Secrets did not match.")
    if not value.strip():
        raise SystemExit(f"{prompt.rstrip(':')} is required.")
    return value.strip()


def _read_password_and_seed_from_stdin() -> tuple[str, str]:
    raw = sys.stdin.read().strip()
    if not raw:
        raise SystemExit("Password and seed phrase payload is required on stdin.")
    lines = raw.splitlines()
    if len(lines) < 2:
        raise SystemExit(
            "For import via stdin, provide password on the first line and the seed phrase on the remaining lines."
        )
    password = lines[0].strip()
    seed_phrase = " ".join(line.strip() for line in lines[1:] if line.strip())
    if not password or not seed_phrase:
        raise SystemExit("Both password and seed phrase are required.")
    return password, seed_phrase


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage a local OpenClaw BTC wallet binding")
    subparsers = parser.add_subparsers(dest="command", required=True)

    common_parent = argparse.ArgumentParser(add_help=False)
    common_parent.add_argument("--user-id", required=True)
    common_parent.add_argument("--network", default="bitcoin")
    common_parent.add_argument("--service-url")

    get_parser = subparsers.add_parser("get", parents=[common_parent])

    create_parser = subparsers.add_parser("create", parents=[common_parent])
    create_parser.add_argument("--label")
    create_parser.add_argument("--account-index", type=int)
    create_parser.add_argument("--reveal-seed", action="store_true")
    create_parser.add_argument("--password-stdin", action="store_true")

    import_parser = subparsers.add_parser("import", parents=[common_parent])
    import_parser.add_argument("--label")
    import_parser.add_argument("--account-index", type=int)
    import_parser.add_argument("--password-stdin", action="store_true")
    import_parser.add_argument("--seed-stdin", action="store_true")

    unlock_parser = subparsers.add_parser("unlock", parents=[common_parent])
    unlock_parser.add_argument("--password-stdin", action="store_true")

    lock_parser = subparsers.add_parser("lock", parents=[common_parent])

    args = parser.parse_args()

    if args.command == "get":
        payload = {"ok": True, "wallet": get_user_btc_wallet_binding(args.user_id, network=args.network)}
    elif args.command == "create":
        payload = {
            "ok": True,
            "wallet": create_user_btc_wallet(
                args.user_id,
                password=_read_secret(
                    prompt="BTC wallet password: ",
                    confirm_prompt="Confirm BTC wallet password: ",
                    stdin_mode=bool(args.password_stdin),
                ),
                label=args.label,
                network=args.network,
                service_url=args.service_url,
                reveal_seed_phrase=bool(args.reveal_seed),
                account_index=args.account_index,
            ),
        }
    elif args.command == "import":
        if args.password_stdin and args.seed_stdin:
            password, seed_phrase = _read_password_and_seed_from_stdin()
        else:
            password = _read_secret(
                prompt="BTC wallet password: ",
                confirm_prompt="Confirm BTC wallet password: ",
                stdin_mode=bool(args.password_stdin),
            )
            seed_phrase = _read_secret(
                prompt="BTC seed phrase: ",
                stdin_mode=bool(args.seed_stdin),
            )
        payload = {
            "ok": True,
            "wallet": import_user_btc_wallet(
                args.user_id,
                password=password,
                seed_phrase=seed_phrase,
                label=args.label,
                network=args.network,
                service_url=args.service_url,
                account_index=args.account_index,
            ),
        }
    elif args.command == "unlock":
        payload = {
            "ok": True,
            "wallet": unlock_user_btc_wallet(
                args.user_id,
                password=_read_secret(
                    prompt="BTC wallet password: ",
                    stdin_mode=bool(args.password_stdin),
                ),
                network=args.network,
                service_url=args.service_url,
            ),
        }
    else:
        payload = {
            "ok": True,
            "wallet": lock_user_btc_wallet(
                args.user_id,
                network=args.network,
                service_url=args.service_url,
            ),
        }

    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
