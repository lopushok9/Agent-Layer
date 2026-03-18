"""One-command installer for the local OpenClaw agent-wallet setup."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.file_ops import atomic_write_text, chmod_if_exists
from agent_wallet.sealed_keys import resolve_sealed_keys_path, unseal_keys


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _extension_path() -> Path:
    return _repo_root() / ".openclaw" / "extensions" / "agent-wallet"


def _default_env_path() -> Path:
    return _package_root() / ".env"


def _default_env_example_path() -> Path:
    return _package_root() / ".env.example"


def _default_config_path() -> Path:
    return Path(os.path.expanduser("~/.openclaw/openclaw.json"))


def _default_venv_path() -> Path:
    return _package_root() / ".venv"


def _default_user_id() -> str:
    return f"{os.getenv('USER', 'openclaw-user')}-local"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-path", default=str(_default_config_path()))
    parser.add_argument("--env-path", default=str(_default_env_path()))
    parser.add_argument("--env-example-path", default=str(_default_env_example_path()))
    parser.add_argument("--venv-path", default=str(_default_venv_path()))
    parser.add_argument("--plugin-id", default="agent-wallet")
    parser.add_argument("--user-id", default=_default_user_id())
    parser.add_argument("--backend", default="solana_local")
    parser.add_argument("--network", default="devnet")
    parser.add_argument("--rpc-url", default="")
    parser.add_argument("--rpc-urls", default="")
    parser.add_argument("--sign-only", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--skip-python-setup", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=False)
    return parser


def _ensure_env_file(env_path: Path, env_example_path: Path) -> bool:
    if env_path.exists():
        return False
    env_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(env_example_path, env_path)
    chmod_if_exists(env_path, 0o600)
    return True


def _ensure_openclaw_config(config_path: Path) -> bool:
    if config_path.exists():
        return False
    config_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        config_path,
        json.dumps({"plugins": {"entries": {}}, "tools": {"alsoAllow": []}}, indent=2) + "\n",
        mode=0o600,
    )
    return True


def _venv_python(venv_path: Path) -> Path:
    if os.name == "nt":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def _ensure_python_runtime(venv_path: Path, package_root: Path) -> tuple[Path, bool]:
    created = False
    python_bin = _venv_python(venv_path)
    if not python_bin.exists():
        venv.EnvBuilder(with_pip=True).create(venv_path)
        created = True

    subprocess.run(
        [str(python_bin), "-m", "pip", "install", "-e", str(package_root)],
        check=True,
    )
    return python_bin, created


def _pending_env_names() -> list[str]:
    pending: list[str] = []
    boot_key = os.getenv("AGENT_WALLET_BOOT_KEY", "").strip()
    sealed_path = resolve_sealed_keys_path()
    if not boot_key:
        pending.append("AGENT_WALLET_BOOT_KEY")
        if not sealed_path.exists():
            pending.extend(["AGENT_WALLET_MASTER_KEY", "AGENT_WALLET_APPROVAL_SECRET"])

    if "AGENT_WALLET_BOOT_KEY" not in pending:
        secrets: dict[str, str] = {}
        if sealed_path.exists():
            try:
                secrets = unseal_keys(boot_key)
            except Exception:
                secrets = {}
        master_key = str(secrets.get("master_key") or "").strip() or os.getenv(
            "AGENT_WALLET_MASTER_KEY", ""
        ).strip()
        approval_secret = str(secrets.get("approval_secret") or "").strip() or os.getenv(
            "AGENT_WALLET_APPROVAL_SECRET", ""
        ).strip()
        if not master_key:
            pending.append("AGENT_WALLET_MASTER_KEY")
        if not approval_secret:
            pending.append("AGENT_WALLET_APPROVAL_SECRET")
    return pending


def _build_next_steps(
    python_bin: Path,
    script_path: Path,
    args: argparse.Namespace,
) -> list[str]:
    command = [
        str(python_bin),
        str(script_path),
        "--config-path",
        str(Path(args.config_path).expanduser()),
        "--plugin-id",
        args.plugin_id,
        "--user-id",
        args.user_id,
        "--backend",
        args.backend,
        "--network",
        args.network,
    ]
    if args.rpc_url.strip():
        command.extend(["--rpc-url", args.rpc_url.strip()])
    if args.rpc_urls.strip():
        command.extend(["--rpc-urls", args.rpc_urls.strip()])
    command.append("--sign-only" if args.sign_only else "--no-sign-only")
    return command


def main() -> None:
    args = build_parser().parse_args()
    package_root = _package_root()
    extension_path = _extension_path()
    config_path = Path(args.config_path).expanduser()
    env_path = Path(args.env_path).expanduser()
    env_example_path = Path(args.env_example_path).expanduser()
    venv_path = Path(args.venv_path).expanduser()
    install_config_script = package_root / "scripts" / "install_openclaw_local_config.py"

    env_created = _ensure_env_file(env_path, env_example_path)
    config_created = _ensure_openclaw_config(config_path)

    python_bin = Path(sys.executable)
    venv_created = False
    if not args.skip_python_setup:
        if not args.dry_run:
            python_bin, venv_created = _ensure_python_runtime(venv_path, package_root)
        else:
            python_bin = _venv_python(venv_path)

    pending_env = _pending_env_names() if args.backend.strip().lower() not in {"", "none"} else []
    configured = False
    configure_stdout = ""
    if not pending_env and not args.dry_run:
        result = subprocess.run(
            _build_next_steps(python_bin, install_config_script, args),
            capture_output=True,
            text=True,
            check=True,
        )
        configured = True
        configure_stdout = result.stdout

    print(
        json.dumps(
            {
                "ok": True,
                "env_path": str(env_path),
                "env_created": env_created,
                "config_path": str(config_path),
                "config_created": config_created,
                "package_root": str(package_root),
                "extension_path": str(extension_path),
                "python_bin": str(python_bin),
                "venv_created": venv_created,
                "configured": configured,
                "pending_env": pending_env,
                "next_configure_command": _build_next_steps(python_bin, install_config_script, args),
                "configure_result": json.loads(configure_stdout) if configure_stdout else None,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
