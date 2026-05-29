#!/usr/bin/env python3
"""Host-side helper for managing a local OpenClaw EVM wallet binding."""

from __future__ import annotations

import argparse
import json
import sys
from getpass import getpass
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from agent_wallet.config import normalize_evm_network, settings  # noqa: E402
from agent_wallet.evm_user_wallets import (  # noqa: E402
    bind_user_evm_wallet,
    create_user_evm_wallet,
    get_user_evm_wallet_binding,
    import_user_evm_wallet,
    list_user_evm_wallet_bindings,
    lock_user_evm_wallet,
    unlock_user_evm_wallet,
)
from agent_wallet.providers.wdk_evm_local import WdkEvmLocalClient  # noqa: E402


def _normalize_network(value: str) -> str:
    return normalize_evm_network(value)


def _paired_network(network: str) -> str | None:
    mapping = {
        "ethereum": "base",
        "base": "ethereum",
    }
    return mapping.get(_normalize_network(network))


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


def _service_health(service_url: str | None) -> dict[str, object]:
    target = str(service_url or "").strip()
    if not target:
        return {"service_url": None, "healthy": False, "error": "service_url is not configured"}
    health_url = f"{target.rstrip('/')}/health"
    try:
        with urlopen(health_url, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return {
                "service_url": target,
                "healthy": int(getattr(response, "status", 0) or 0) == 200,
                "health": payload,
            }
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        return {"service_url": target, "healthy": False, "error": str(exc)}


def _status_payload(user_id: str | None, network: str | None, service_url: str | None) -> dict[str, object]:
    target_service_url = str(service_url or settings.wdk_evm_service_url).strip() or None
    payload: dict[str, object] = {
        "ok": True,
        "network": _normalize_network(network or "ethereum"),
        "service": _service_health(target_service_url),
    }
    target_network = _normalize_network(network or "ethereum")
    if target_service_url:
        try:
            payload["network_info"] = WdkEvmLocalClient(target_service_url).get_sync("/v1/evm/network")
        except Exception as exc:  # pragma: no cover - defensive
            payload["network_info_error"] = str(exc)
    if user_id:
        payload["bindings"] = list_user_evm_wallet_bindings(user_id)
        try:
            payload["binding"] = get_user_evm_wallet_binding(user_id, network=target_network)
        except Exception as exc:
            payload["binding_error"] = str(exc)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage a local OpenClaw EVM wallet binding")
    subparsers = parser.add_subparsers(dest="command", required=True)

    common_parent = argparse.ArgumentParser(add_help=False)
    common_parent.add_argument("--network", default="ethereum")
    common_parent.add_argument("--service-url")

    get_parser = subparsers.add_parser("get", parents=[common_parent])
    get_parser.add_argument("--user-id", required=True)

    list_parser = subparsers.add_parser("list", parents=[common_parent])
    list_parser.add_argument("--user-id", required=True)

    status_parser = subparsers.add_parser("status", parents=[common_parent])
    status_parser.add_argument("--user-id", default="")

    setup_parser = subparsers.add_parser("setup", parents=[common_parent])
    setup_parser.add_argument("--user-id", required=True)
    setup_parser.add_argument("--label")
    setup_parser.add_argument("--account-index", type=int)
    setup_parser.add_argument("--password-stdin", action="store_true")
    setup_parser.add_argument("--bind-network-pair", action=argparse.BooleanOptionalAction, default=True)

    create_parser = subparsers.add_parser("create", parents=[common_parent])
    create_parser.add_argument("--user-id", required=True)
    create_parser.add_argument("--label")
    create_parser.add_argument("--account-index", type=int)
    create_parser.add_argument("--reveal-seed", action="store_true")
    create_parser.add_argument("--password-stdin", action="store_true")
    create_parser.add_argument("--bind-network-pair", action=argparse.BooleanOptionalAction, default=True)

    import_parser = subparsers.add_parser("import", parents=[common_parent])
    import_parser.add_argument("--user-id", required=True)
    import_parser.add_argument("--label")
    import_parser.add_argument("--account-index", type=int)
    import_parser.add_argument("--password-stdin", action="store_true")
    import_parser.add_argument("--seed-stdin", action="store_true")
    import_parser.add_argument("--bind-network-pair", action=argparse.BooleanOptionalAction, default=True)

    unlock_parser = subparsers.add_parser("unlock", parents=[common_parent])
    unlock_parser.add_argument("--user-id", required=True)
    unlock_parser.add_argument("--password-stdin", action="store_true")
    unlock_parser.add_argument("--wallet-id", default="")
    unlock_parser.add_argument("--account-index", type=int)
    unlock_parser.add_argument("--bind-network-pair", action=argparse.BooleanOptionalAction, default=True)

    lock_parser = subparsers.add_parser("lock", parents=[common_parent])
    lock_parser.add_argument("--user-id", required=True)
    lock_parser.add_argument("--wallet-id", default="")
    lock_parser.add_argument("--account-index", type=int)

    args = parser.parse_args()
    effective_network = _normalize_network(args.network)

    def _config_hint(wallet: dict[str, object]) -> dict[str, object]:
        return {
            "backend": "wdk_evm_local",
            "network": effective_network,
            "wdkEvmServiceUrl": args.service_url,
            "wdkEvmWalletId": wallet.get("wallet_id"),
            "wdkEvmAccountIndex": wallet.get("account_index"),
        }

    def _bind_pair(wallet: dict[str, object]) -> dict[str, object] | None:
        if not getattr(args, "bind_network_pair", False):
            return None
        paired = _paired_network(effective_network)
        if not paired:
            return None
        return bind_user_evm_wallet(
            args.user_id,
            wallet_id=str(wallet.get("wallet_id") or ""),
            network=paired,
            service_url=args.service_url,
            account_index=wallet.get("account_index"),
            tolerate_locked=True,
            fallback_address=str(wallet.get("address") or "").strip() or None,
        )

    if args.command == "status":
        payload = _status_payload(args.user_id or None, effective_network, args.service_url)
    elif args.command == "list":
        payload = {"ok": True, "wallets": list_user_evm_wallet_bindings(args.user_id)}
    elif args.command == "get":
        wallet = get_user_evm_wallet_binding(args.user_id, network=effective_network)
        payload = {"ok": True, "wallet": wallet, "openclaw_config_hint": _config_hint(wallet)}
    elif args.command == "setup":
        password = _read_secret(
            prompt="EVM wallet password: ",
            confirm_prompt=None,
            stdin_mode=bool(args.password_stdin),
        )
        try:
            existing = get_user_evm_wallet_binding(args.user_id, network=effective_network)
        except Exception:
            existing = None

        if existing is None:
            wallet = create_user_evm_wallet(
                args.user_id,
                password=password,
                label=args.label,
                network=effective_network,
                service_url=args.service_url,
                account_index=args.account_index,
            )
            paired_binding = _bind_pair(wallet)
            payload = {
                "ok": True,
                "action": "created",
                "wallet": wallet,
                "paired_binding": paired_binding,
                "openclaw_config_hint": _config_hint(wallet),
            }
        else:
            wallet = unlock_user_evm_wallet(
                args.user_id,
                password=password,
                network=effective_network,
                service_url=args.service_url,
                account_index=args.account_index,
            )
            paired_binding = _bind_pair(wallet)
            payload = {
                "ok": True,
                "action": "unlocked",
                "wallet": wallet,
                "paired_binding": paired_binding,
                "openclaw_config_hint": _config_hint(wallet),
            }
    elif args.command == "create":
        wallet = create_user_evm_wallet(
            args.user_id,
            password=_read_secret(
                prompt="EVM wallet password: ",
                confirm_prompt="Confirm EVM wallet password: ",
                stdin_mode=bool(args.password_stdin),
            ),
            label=args.label,
            network=effective_network,
            service_url=args.service_url,
            reveal_seed_phrase=bool(args.reveal_seed),
            account_index=args.account_index,
        )
        payload = {
            "ok": True,
            "wallet": wallet,
            "paired_binding": _bind_pair(wallet),
        }
    elif args.command == "import":
        if args.password_stdin and args.seed_stdin:
            password, seed_phrase = _read_password_and_seed_from_stdin()
        else:
            password = _read_secret(
                prompt="EVM wallet password: ",
                confirm_prompt="Confirm EVM wallet password: ",
                stdin_mode=bool(args.password_stdin),
            )
            seed_phrase = _read_secret(
                prompt="EVM seed phrase: ",
                stdin_mode=bool(args.seed_stdin),
            )
        wallet = import_user_evm_wallet(
            args.user_id,
            password=password,
            seed_phrase=seed_phrase,
            label=args.label,
            network=effective_network,
            service_url=args.service_url,
            account_index=args.account_index,
        )
        payload = {
            "ok": True,
            "wallet": wallet,
            "paired_binding": _bind_pair(wallet),
        }
    elif args.command == "unlock":
        wallet = unlock_user_evm_wallet(
            args.user_id,
            password=_read_secret(
                prompt="EVM wallet password: ",
                stdin_mode=bool(args.password_stdin),
            ),
            network=effective_network,
            service_url=args.service_url,
            wallet_id=args.wallet_id or None,
            account_index=args.account_index,
        )
        payload = {
            "ok": True,
            "wallet": wallet,
            "paired_binding": _bind_pair(wallet),
        }
    else:
        payload = {
            "ok": True,
            "wallet": lock_user_evm_wallet(
                args.user_id,
                network=effective_network,
                service_url=args.service_url,
                wallet_id=args.wallet_id or None,
                account_index=args.account_index,
            ),
        }

    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
