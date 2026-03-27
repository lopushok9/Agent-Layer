#!/usr/bin/env python3
"""One-command host bootstrap for the local OpenClaw BTC wallet flow."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen
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


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


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
    parser.add_argument("--wdk-wallet-root", default=str(_repo_root() / "wdk-btc-wallet"))
    parser.add_argument("--label", default="Agent BTC Wallet")
    parser.add_argument("--account-index", type=int, default=0)
    parser.add_argument("--python-bin", default=_default_python_bin())
    parser.add_argument("--package-root", default=str(_package_root()))
    parser.add_argument("--password-stdin", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--reveal-seed", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--sign-only", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--auto-start-service", action=argparse.BooleanOptionalAction, default=True)
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


def _health_url(service_url: str) -> str:
    return f"{service_url.rstrip('/')}/health"


def _service_is_healthy(service_url: str) -> bool:
    try:
        with urlopen(_health_url(service_url), timeout=1.5) as response:
            return int(getattr(response, "status", 0) or 0) == 200
    except (URLError, TimeoutError, OSError):
        return False


def _is_local_service_url(service_url: str) -> bool:
    parsed = urlparse(service_url)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def _require_local_service_url(service_url: str) -> None:
    if not _is_local_service_url(service_url):
        raise SystemExit(
            f"BTC bootstrap only supports a localhost service URL. Refusing non-local endpoint: {service_url}"
        )


def _service_log_dir(config_path: Path) -> Path:
    return config_path.expanduser().parent / "logs"


def _service_log_path(config_path: Path) -> Path:
    return _service_log_dir(config_path) / "wdk-btc-wallet.log"


def _auto_start_local_service(
    *,
    service_url: str,
    network: str,
    wdk_wallet_root: Path,
    config_path: Path,
) -> dict[str, object]:
    if _service_is_healthy(service_url):
        return {"started": False, "already_healthy": True}

    if not _is_local_service_url(service_url):
        raise SystemExit(
            f"BTC service at {service_url} is unreachable and auto-start is only supported for localhost URLs."
        )

    run_local = wdk_wallet_root / "run-local.sh"
    if not run_local.exists():
        raise SystemExit(f"Could not find wdk-btc-wallet launcher: {run_local}")

    parsed = urlparse(service_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8080
    log_dir = _service_log_dir(config_path)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = _service_log_path(config_path)

    env = os.environ.copy()
    env["HOST"] = host
    env["PORT"] = str(port)
    env["WDK_BTC_NETWORK"] = network

    with log_path.open("a", encoding="utf-8") as log_file:
        process = subprocess.Popen(  # noqa: S603
            ["sh", str(run_local)],
            cwd=str(wdk_wallet_root),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )

    deadline = time.time() + 30.0
    while time.time() < deadline:
        if _service_is_healthy(service_url):
            return {
                "started": True,
                "already_healthy": False,
                "pid": process.pid,
                "log_path": str(log_path),
            }
        if process.poll() is not None:
            raise SystemExit(
                f"wdk-btc-wallet exited before becoming healthy. Check log: {log_path}"
            )
        time.sleep(0.5)

    raise SystemExit(
        f"Timed out waiting for wdk-btc-wallet health at {_health_url(service_url)}. Check log: {log_path}"
    )


def main() -> int:
    args = build_parser().parse_args()
    effective_network = _normalize_network(args.network)
    _require_local_service_url(args.service_url)
    config_path = Path(args.config_path).expanduser()
    config_created = _ensure_openclaw_config(config_path)
    service_bootstrap: dict[str, object] | None = None
    if args.auto_start_service:
        service_bootstrap = _auto_start_local_service(
            service_url=args.service_url,
            network=effective_network,
            wdk_wallet_root=Path(args.wdk_wallet_root).expanduser(),
            config_path=config_path,
        )
    elif not _service_is_healthy(args.service_url):
        raise SystemExit(
            f"BTC service is not healthy at {_health_url(args.service_url)} and --no-auto-start-service was set."
        )

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
        "service_bootstrap": service_bootstrap,
        "btc_setup": setup_payload,
        "openclaw_config": install_payload,
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
