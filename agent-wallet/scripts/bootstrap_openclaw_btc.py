#!/usr/bin/env python3
"""One-command host bootstrap for the local OpenClaw BTC wallet flow."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.file_ops import atomic_write_text, chmod_if_exists


def _default_config_path() -> Path:
    return Path(os.path.expanduser("~/.openclaw/openclaw.json"))


def _default_user_id() -> str:
    return f"{os.getenv('USER', 'openclaw-user')}-local"


def _default_python_bin() -> str:
    return os.getenv("OPENCLAW_AGENT_WALLET_PYTHON", sys.executable)


def _package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path(name: str) -> Path:
    return _package_root() / "scripts" / name


def _normalize_network(value: str) -> str:
    network = str(value or "").strip().lower()
    if network == "mainnet":
        return "bitcoin"
    return network or "bitcoin"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-path", default=str(_default_config_path()))
    parser.add_argument("--plugin-id", default="agent-wallet")
    parser.add_argument("--user-id", default=_default_user_id())
    parser.add_argument("--network", default="testnet")
    parser.add_argument("--service-url", default="http://127.0.0.1:8080")
    parser.add_argument("--label", default="Agent BTC Wallet")
    parser.add_argument("--account-index", type=int, default=0)
    parser.add_argument("--python-bin", default=_default_python_bin())
    parser.add_argument("--package-root", default=str(_package_root()))
    parser.add_argument("--password-stdin", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--reveal-seed", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--sign-only", action=argparse.BooleanOptionalAction, default=False)
    return parser


def _ensure_openclaw_config(config_path: Path) -> bool:
    if config_path.exists():
        return False
    config_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        config_path,
        json.dumps({"plugins": {"entries": {}}, "tools": {"alsoAllow": []}}, indent=2) + "\n",
        mode=0o600,
    )
    chmod_if_exists(config_path, 0o600)
    return True


def _run_script(
    python_bin: str,
    script_name: str,
    args: list[str],
    *,
    stdin_text: str | None = None,
) -> dict:
    completed = subprocess.run(
        [python_bin, str(_script_path(script_name)), *args],
        check=True,
        capture_output=True,
        text=True,
        input=stdin_text,
        env=os.environ.copy(),
    )
    return json.loads(completed.stdout)


def main() -> int:
    args = build_parser().parse_args()
    effective_network = _normalize_network(args.network)
    config_path = Path(args.config_path).expanduser()
    config_created = _ensure_openclaw_config(config_path)

    stdin_text = sys.stdin.read() if args.password_stdin else None
    setup_payload = _run_script(
        args.python_bin,
        "manage_openclaw_btc_wallet.py",
        [
            "setup",
            "--user-id",
            args.user_id,
            "--network",
            effective_network,
            "--service-url",
            args.service_url,
            "--label",
            args.label,
            "--account-index",
            str(args.account_index),
            *([] if not args.password_stdin else ["--password-stdin"]),
            *(["--reveal-seed"] if args.reveal_seed else []),
        ],
        stdin_text=stdin_text,
    )

    install_args = [
        "--config-path",
        str(config_path),
        "--plugin-id",
        args.plugin_id,
        "--user-id",
        args.user_id,
        "--backend",
        "wdk_btc_local",
        "--network",
        effective_network,
        "--wdk-btc-service-url",
        args.service_url,
        "--wdk-btc-account-index",
        str(args.account_index),
        "--package-root",
        args.package_root,
        "--python-bin",
        args.python_bin,
        "--sign-only" if args.sign_only else "--no-sign-only",
    ]
    install_payload = _run_script(
        args.python_bin,
        "install_openclaw_local_config.py",
        install_args,
    )

    output = {
        "ok": True,
        "config_created": config_created,
        "config_path": str(config_path),
        "btc_setup": setup_payload,
        "openclaw_config": install_payload,
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
