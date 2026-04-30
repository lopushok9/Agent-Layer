"""One-command installer for the local OpenClaw agent-wallet setup."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

INCLUDED_RUNTIME_ROOT_FILES = [
    ".env.example",
    "AGENTS.md",
    "README.md",
    "CHANGELOG.md",
    "RELEASING.md",
    "install-from-github.sh",
    "requirements.txt",
    "setup.sh",
]
INCLUDED_RUNTIME_TOP_LEVEL_DIRS = [
    ".openclaw",
    "agent-wallet",
    "agent-a2a-gateway",
    "wdk-btc-wallet",
    "wdk-evm-wallet",
]
EXCLUDED_RUNTIME_DIR_NAMES = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    ".runtime-venv",
    "__pycache__",
    "dist",
    "extensions-local",
    "graphify-out",
    "node_modules",
}
EXCLUDED_RUNTIME_FILE_NAMES = {
    ".DS_Store",
}
EXCLUDED_RUNTIME_SUFFIXES = {
    ".pyc",
    ".pyo",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _extension_path() -> Path:
    return _repo_root() / ".openclaw" / "extensions" / "agent-wallet"


def _default_wdk_btc_root() -> Path:
    return _repo_root() / "wdk-btc-wallet"


def _default_wdk_evm_root() -> Path:
    return _repo_root() / "wdk-evm-wallet"


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


def _default_npm_bin() -> str:
    return shutil.which("npm") or "npm"


def _resolve_openclaw_home() -> Path:
    return Path(os.path.expanduser(os.getenv("OPENCLAW_HOME", "~/.openclaw")))


def _default_runtime_root() -> Path:
    explicit_target = os.getenv("OPENCLAW_INSTALL_TARGET", "").strip()
    if explicit_target:
        return Path(explicit_target).expanduser()
    explicit_root = os.getenv("OPENCLAW_INSTALL_ROOT", "").strip()
    if explicit_root:
        return Path(explicit_root).expanduser() / "current"
    return _resolve_openclaw_home() / "agent-wallet-runtime" / "current"


def _resolve_sealed_keys_path() -> Path:
    return _resolve_openclaw_home() / "sealed_keys.json"


def _atomic_write_text(path: Path, content: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise


def _chmod_if_exists(path: Path, mode: int = 0o600) -> None:
    try:
        path.chmod(mode)
    except FileNotFoundError:
        return


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-path", default=str(_default_config_path()))
    parser.add_argument("--env-path", default=str(_default_env_path()))
    parser.add_argument("--env-example-path", default=str(_default_env_example_path()))
    parser.add_argument("--venv-path", default=str(_default_venv_path()))
    parser.add_argument("--package-root", default=str(_package_root()))
    parser.add_argument("--extension-path", default=str(_extension_path()))
    parser.add_argument("--wdk-btc-root", default=str(_default_wdk_btc_root()))
    parser.add_argument("--wdk-evm-root", default=str(_default_wdk_evm_root()))
    parser.add_argument("--runtime-root", default=str(_default_runtime_root()))
    parser.add_argument("--npm-bin", default=_default_npm_bin())
    parser.add_argument("--plugin-id", default="agent-wallet")
    parser.add_argument("--user-id", default=_default_user_id())
    parser.add_argument("--backend", default="solana_local")
    parser.add_argument("--network", default="devnet")
    parser.add_argument("--rpc-url", default="")
    parser.add_argument("--rpc-urls", default="")
    parser.add_argument("--sign-only", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--sync-runtime", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--install-from-runtime", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--skip-python-setup", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--skip-node-setup", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=False)
    return parser


def _infer_source_root(
    package_root: Path,
    extension_path: Path,
    wdk_btc_root: Path,
    wdk_evm_root: Path,
) -> Path:
    candidates = [
        package_root.parent,
        Path(os.path.commonpath([package_root, extension_path, wdk_btc_root, wdk_evm_root])),
    ]
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if (
            (resolved / "agent-wallet").resolve() == package_root
            and (resolved / ".openclaw" / "extensions" / "agent-wallet").resolve() == extension_path
            and (resolved / "wdk-btc-wallet").resolve() == wdk_btc_root
            and (resolved / "wdk-evm-wallet").resolve() == wdk_evm_root
            and (resolved / "setup.sh").exists()
        ):
            return resolved
    raise SystemExit(
        "Could not infer the source root for runtime sync. Expected package-root, extension-path, "
        "wdk-btc-root, and wdk-evm-root to belong to the same repo checkout."
    )


def _ignore_runtime_entries(_directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in EXCLUDED_RUNTIME_DIR_NAMES:
            ignored.add(name)
            continue
        if name in EXCLUDED_RUNTIME_FILE_NAMES:
            ignored.add(name)
            continue
        if any(name.endswith(suffix) for suffix in EXCLUDED_RUNTIME_SUFFIXES):
            ignored.add(name)
    return ignored


def _replace_if_type_mismatch(source: Path, target: Path) -> None:
    if not target.exists():
        return
    if source.is_dir() and target.is_file():
        target.unlink()
    elif source.is_file() and target.is_dir():
        shutil.rmtree(target)


def _sync_runtime_tree(source_root: Path, runtime_root: Path) -> dict[str, object]:
    source_root = source_root.resolve()
    runtime_root = runtime_root.resolve()
    if source_root == runtime_root:
        return {
            "enabled": True,
            "skipped": True,
            "reason": "source_root_matches_runtime_root",
            "source_root": str(source_root),
            "runtime_root": str(runtime_root),
            "copied_paths": [],
        }

    runtime_root.mkdir(parents=True, exist_ok=True)
    copied_paths: list[str] = []
    for relative in INCLUDED_RUNTIME_ROOT_FILES + INCLUDED_RUNTIME_TOP_LEVEL_DIRS:
        source = source_root / relative
        if not source.exists():
            continue
        target = runtime_root / relative
        _replace_if_type_mismatch(source, target)
        if source.is_dir():
            shutil.copytree(
                source,
                target,
                dirs_exist_ok=True,
                ignore=_ignore_runtime_entries,
            )
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        copied_paths.append(relative)

    return {
        "enabled": True,
        "skipped": False,
        "reason": None,
        "source_root": str(source_root),
        "runtime_root": str(runtime_root),
        "copied_paths": copied_paths,
    }


def _ensure_env_file(env_path: Path, env_example_path: Path) -> bool:
    if env_path.exists():
        return False
    env_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(env_example_path, env_path)
    _chmod_if_exists(env_path, 0o600)
    return True


def _ensure_openclaw_config(config_path: Path) -> bool:
    if config_path.exists():
        return False
    config_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(
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


def _ensure_node_runtime(npm_bin: str, project_root: Path) -> dict[str, object]:
    package_json = project_root / "package.json"
    if not package_json.exists():
        raise SystemExit(f"Missing package.json for Node runtime at '{project_root}'.")
    package_lock = project_root / "package-lock.json"
    command = [npm_bin, "ci"] if package_lock.exists() else [npm_bin, "install"]
    subprocess.run(command, cwd=project_root, check=True)
    return {
        "project_root": str(project_root),
        "package_json": str(package_json),
        "package_lock": str(package_lock) if package_lock.exists() else None,
        "command": command,
    }


def _pending_env_names() -> list[str]:
    pending: list[str] = []
    boot_key = os.getenv("AGENT_WALLET_BOOT_KEY", "").strip()
    sealed_path = _resolve_sealed_keys_path()
    if not boot_key:
        pending.append("AGENT_WALLET_BOOT_KEY")
        if not sealed_path.exists():
            pending.extend(["AGENT_WALLET_MASTER_KEY", "AGENT_WALLET_APPROVAL_SECRET"])
    elif not sealed_path.exists():
        if not os.getenv("AGENT_WALLET_MASTER_KEY", "").strip():
            pending.append("AGENT_WALLET_MASTER_KEY")
        if not os.getenv("AGENT_WALLET_APPROVAL_SECRET", "").strip():
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
    command.extend(["--extension-path", str(Path(args.extension_path).expanduser())])
    command.extend(["--package-root", str(Path(args.package_root).expanduser())])
    command.extend(["--python-bin", str(python_bin)])
    return command


def main() -> None:
    args = build_parser().parse_args()
    source_package_root = Path(args.package_root).expanduser().resolve()
    source_extension_path = Path(args.extension_path).expanduser().resolve()
    source_wdk_btc_root = Path(args.wdk_btc_root).expanduser().resolve()
    source_wdk_evm_root = Path(args.wdk_evm_root).expanduser().resolve()
    runtime_root = Path(args.runtime_root).expanduser().resolve()
    config_path = Path(args.config_path).expanduser()
    env_path = Path(args.env_path).expanduser()
    env_example_path = Path(args.env_example_path).expanduser()
    venv_path = Path(args.venv_path).expanduser()
    source_root = _infer_source_root(
        source_package_root,
        source_extension_path,
        source_wdk_btc_root,
        source_wdk_evm_root,
    )

    runtime_sync: dict[str, object]
    if not args.sync_runtime:
        runtime_sync = {
            "enabled": False,
            "skipped": True,
            "reason": "sync_runtime_disabled",
            "source_root": str(source_root),
            "runtime_root": str(runtime_root),
            "copied_paths": [],
        }
    elif args.dry_run:
        runtime_sync = {
            "enabled": True,
            "skipped": False,
            "reason": "dry_run",
            "source_root": str(source_root),
            "runtime_root": str(runtime_root),
            "copied_paths": INCLUDED_RUNTIME_ROOT_FILES + INCLUDED_RUNTIME_TOP_LEVEL_DIRS,
        }
    else:
        runtime_sync = _sync_runtime_tree(source_root, runtime_root)

    if args.install_from_runtime:
        package_root = runtime_root / "agent-wallet"
        extension_path = runtime_root / ".openclaw" / "extensions" / "agent-wallet"
        wdk_btc_root = runtime_root / "wdk-btc-wallet"
        wdk_evm_root = runtime_root / "wdk-evm-wallet"
    else:
        package_root = source_package_root
        extension_path = source_extension_path
        wdk_btc_root = source_wdk_btc_root
        wdk_evm_root = source_wdk_evm_root

    install_config_script = package_root / "scripts" / "install_openclaw_local_config.py"
    if args.install_from_runtime:
        default_source_env_path = source_package_root / ".env"
        default_source_venv_path = source_package_root / ".venv"
        if env_path.resolve() == default_source_env_path.resolve():
            env_path = package_root / ".env"
        if venv_path.resolve() == default_source_venv_path.resolve():
            venv_path = package_root / ".venv"
        source_env_example_path = source_package_root / ".env.example"
        if env_example_path.resolve() == source_env_example_path.resolve():
            env_example_path = package_root / ".env.example"

    env_created = _ensure_env_file(env_path, env_example_path)
    config_created = _ensure_openclaw_config(config_path)

    python_bin = Path(sys.executable)
    venv_created = False
    if not args.skip_python_setup:
        if not args.dry_run:
            python_bin, venv_created = _ensure_python_runtime(venv_path, package_root)
        else:
            python_bin = _venv_python(venv_path)

    node_runtime = {
        "skipped": bool(args.skip_node_setup),
        "npm_bin": args.npm_bin,
        "projects": [],
    }
    if not args.skip_node_setup:
        if args.dry_run:
            node_runtime["projects"] = [
                {
                    "project_root": str(wdk_btc_root),
                    "command": [args.npm_bin, "ci" if (wdk_btc_root / "package-lock.json").exists() else "install"],
                },
                {
                    "project_root": str(wdk_evm_root),
                    "command": [args.npm_bin, "ci" if (wdk_evm_root / "package-lock.json").exists() else "install"],
                },
            ]
        else:
            node_runtime["projects"] = [
                _ensure_node_runtime(args.npm_bin, wdk_btc_root),
                _ensure_node_runtime(args.npm_bin, wdk_evm_root),
            ]

    backend_enabled = args.backend.strip().lower() not in {"", "none"}
    pending_env = _pending_env_names() if backend_enabled else []
    configured = False
    configure_stdout = ""
    if backend_enabled and not pending_env and not args.dry_run:
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
                "wdk_btc_root": str(wdk_btc_root),
                "wdk_evm_root": str(wdk_evm_root),
                "runtime_root": str(runtime_root),
                "install_from_runtime": bool(args.install_from_runtime),
                "python_bin": str(python_bin),
                "venv_created": venv_created,
                "node_runtime": node_runtime,
                "runtime_sync": runtime_sync,
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
