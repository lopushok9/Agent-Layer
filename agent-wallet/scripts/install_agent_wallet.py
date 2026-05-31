"""One-command installer for the local OpenClaw agent-wallet setup."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
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
    "codex",
    ".openclaw",
    "agent-wallet",
    "agent-a2a-gateway",
    "hermes",
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
    ".env",
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
    return _resolve_openclaw_home() / "openclaw.json"


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


def _runtime_base_for(runtime_root: Path) -> Path:
    resolved = runtime_root.expanduser().resolve()
    if resolved.parent.name == "releases":
        return resolved.parent.parent
    return resolved.parent


def _shared_runtime_root(runtime_root: Path) -> Path:
    return _runtime_base_for(runtime_root) / "shared"


def _shared_dependency_links_supported() -> bool:
    return os.name != "nt"


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


def _sha256_text(parts: list[str]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _file_text_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


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
    parser.add_argument("--wdk-evm-service-url", default=EVM_DEFAULT_SERVICE_URL)
    parser.add_argument("--runtime-root", default=str(_default_runtime_root()))
    parser.add_argument("--npm-bin", default=_default_npm_bin())
    parser.add_argument("--plugin-id", default="agent-wallet")
    parser.add_argument("--user-id", default=_default_user_id())
    parser.add_argument("--backend", default="solana_local")
    parser.add_argument("--network", default="mainnet")
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
    directory = Path(_directory)
    keep_dist = ".openclaw" in directory.parts and "extensions" in directory.parts
    ignored: set[str] = set()
    for name in names:
        if name == "pay-bridge" and directory.parts[-2:] == (".openclaw", "extensions"):
            ignored.add(name)
            continue
        if name == "dist" and keep_dist:
            continue
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
    if not env_example_path.exists():
        source_candidate = _package_root() / ".env.example"
        if source_candidate.exists():
            env_example_path = source_candidate
        else:
            raise SystemExit(
                f"Missing env example template at '{env_example_path}'."
            )
    env_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(env_example_path, env_path)
    _chmod_if_exists(env_path, 0o600)
    return True


def _upsert_env_value(env_path: Path, key: str, value: str) -> bool:
    if not env_path.exists():
        return False
    lines = env_path.read_text(encoding="utf-8").splitlines()
    updated = False
    replaced = False
    prefix = f"{key}="
    new_line = f"{key}={value}"
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            replaced = True
            if line != new_line:
                lines[index] = new_line
                updated = True
            break
    if not replaced:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(new_line)
        updated = True
    if updated:
        _atomic_write_text(env_path, "\n".join(lines) + "\n", mode=0o600)
        _chmod_if_exists(env_path, 0o600)
    return updated


def _ensure_runtime_boot_key_file_env(env_path: Path) -> bool:
    boot_key_file = _resolve_openclaw_home() / "agent-wallet-runtime" / "boot-key"
    if not boot_key_file.exists():
        return False
    return _upsert_env_value(env_path, "AGENT_WALLET_BOOT_KEY_FILE", str(boot_key_file))


def _ensure_flash_bridge_env(env_path: Path, package_root: Path) -> dict[str, bool]:
    bridge_path = package_root / "scripts" / "flash-sdk-bridge" / "bridge.mjs"
    results = {
        "command_updated": False,
        "mode_updated": False,
    }
    if not bridge_path.exists():
        return results
    results["command_updated"] = _upsert_env_value(
        env_path,
        "FLASH_SDK_BRIDGE_COMMAND",
        f"node {bridge_path}",
    )
    results["mode_updated"] = _upsert_env_value(
        env_path,
        "FLASH_SDK_BRIDGE_MODE",
        "real",
    )
    return results


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


def _venv_python_wrapper(venv_path: Path) -> Path:
    if os.name == "nt":
        return _venv_python(venv_path)
    return venv_path / "bin" / "openclaw-agent-wallet-python"


def _ensure_python_wrapper(venv_path: Path) -> Path:
    if os.name == "nt":
        return _venv_python(venv_path)
    wrapper = _venv_python_wrapper(venv_path)
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text('#!/bin/sh\nexec "$(dirname "$0")/python" "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    return wrapper


def _python_runtime_fingerprint(package_root: Path, python_bin: Path) -> str:
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    return _sha256_text(
        [
            f"python-bin:{python_bin}",
            f"python-version:{version}",
            f"platform:{platform.system()}",
            f"machine:{platform.machine()}",
            _file_text_or_empty(package_root / "pyproject.toml"),
        ]
    )[:24]


def _python_runtime_plan(
    venv_path: Path,
    package_root: Path,
    runtime_root: Path,
) -> dict[str, object]:
    if _shared_dependency_links_supported():
        fingerprint = _python_runtime_fingerprint(package_root, Path(sys.executable))
        shared_root = _shared_runtime_root(runtime_root) / "python" / fingerprint
        shared_venv_path = shared_root / "venv"
        shared_wrapper = _venv_python_wrapper(shared_venv_path)
        return {
            "shared": True,
            "fingerprint": fingerprint,
            "shared_root": str(shared_root),
            "venv_path": str(shared_venv_path),
            "release_link_path": str(venv_path),
            "python_bin": str(venv_path / shared_wrapper.relative_to(shared_venv_path)),
            "action": "reuse" if shared_venv_path.exists() else "create",
            "exists": shared_venv_path.exists(),
        }
    return {
        "shared": False,
        "fingerprint": None,
        "shared_root": None,
        "venv_path": str(venv_path),
        "release_link_path": str(venv_path),
        "python_bin": str(_venv_python_wrapper(venv_path)),
        "action": "install",
        "exists": _venv_python(venv_path).exists(),
    }


def _replace_with_directory_symlink(link_path: Path, target_path: Path) -> None:
    target_resolved = target_path.resolve()
    if link_path.is_symlink():
        existing_target = link_path.resolve()
        if existing_target == target_resolved:
            return
        link_path.unlink()
    elif link_path.exists():
        if link_path.is_dir():
            shutil.rmtree(link_path)
        else:
            link_path.unlink()
    link_path.parent.mkdir(parents=True, exist_ok=True)
    link_path.symlink_to(target_resolved, target_is_directory=True)


def _ensure_python_runtime(
    venv_path: Path,
    package_root: Path,
    runtime_root: Path,
) -> tuple[Path, bool, dict[str, object]]:
    created = False
    plan = _python_runtime_plan(venv_path, package_root, runtime_root)
    if bool(plan["shared"]):
        shared_root = Path(str(plan["shared_root"]))
        shared_venv_path = Path(str(plan["venv_path"]))
        python_bin = _venv_python(shared_venv_path)
        if not python_bin.exists():
            venv.EnvBuilder(with_pip=True).create(shared_venv_path)
            created = True
            subprocess.run(
                [str(python_bin), "-m", "pip", "install", "-e", str(package_root)],
                check=True,
            )
        shared_wrapper = _ensure_python_wrapper(shared_venv_path)
        _replace_with_directory_symlink(venv_path, shared_venv_path)
        plan["action"] = "create" if created else "reuse"
        plan["exists"] = True
        return (
            venv_path / shared_wrapper.relative_to(shared_venv_path),
            created,
            plan,
        )

    python_bin = _venv_python(venv_path)
    if not python_bin.exists():
        venv.EnvBuilder(with_pip=True).create(venv_path)
        created = True

    subprocess.run(
        [str(python_bin), "-m", "pip", "install", "-e", str(package_root)],
        check=True,
    )
    return (
        _ensure_python_wrapper(venv_path),
        created,
        plan,
    )


def _node_version() -> str:
    result = subprocess.run(
        ["node", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _node_runtime_fingerprint(project_root: Path) -> str:
    return _sha256_text(
        [
            f"node-version:{_node_version()}",
            f"platform:{platform.system()}",
            f"machine:{platform.machine()}",
            _file_text_or_empty(project_root / "package.json"),
            _file_text_or_empty(project_root / "package-lock.json"),
        ]
    )[:24]


def _node_runtime_plan(project_root: Path, runtime_root: Path) -> dict[str, object]:
    package_json = project_root / "package.json"
    package_lock = project_root / "package-lock.json"
    command = ["npm", "ci"] if package_lock.exists() else ["npm", "install"]
    if _shared_dependency_links_supported():
        fingerprint = _node_runtime_fingerprint(project_root)
        shared_project_root = _shared_runtime_root(runtime_root) / "node" / project_root.name / fingerprint
        shared_node_modules = shared_project_root / "node_modules"
        return {
            "project_root": str(project_root),
            "package_json": str(package_json),
            "package_lock": str(package_lock) if package_lock.exists() else None,
            "command": command,
            "shared": True,
            "fingerprint": fingerprint,
            "shared_root": str(shared_project_root),
            "node_modules_path": str(shared_node_modules),
            "release_link_path": str(project_root / "node_modules"),
            "action": "reuse" if shared_node_modules.exists() else "create",
            "exists": shared_node_modules.exists(),
        }
    return {
        "project_root": str(project_root),
        "package_json": str(package_json),
        "package_lock": str(package_lock) if package_lock.exists() else None,
        "command": command,
        "shared": False,
        "fingerprint": None,
        "shared_root": None,
        "node_modules_path": str(project_root / "node_modules"),
        "release_link_path": str(project_root / "node_modules"),
        "action": "install",
        "exists": (project_root / "node_modules").exists(),
    }


def _copy_if_exists(source: Path, target: Path) -> None:
    if not source.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _ensure_node_runtime(npm_bin: str, project_root: Path, runtime_root: Path) -> dict[str, object]:
    package_json = project_root / "package.json"
    if not package_json.exists():
        raise SystemExit(f"Missing package.json for Node runtime at '{project_root}'.")
    package_lock = project_root / "package-lock.json"
    command = [npm_bin, "ci"] if package_lock.exists() else [npm_bin, "install"]
    env = dict(os.environ)
    cache_dir = (
        env.get("OPENCLAW_AGENT_WALLET_NPM_CACHE")
        or str(_resolve_openclaw_home() / "npm-cache")
    )
    env["NPM_CONFIG_CACHE"] = cache_dir
    env["npm_config_cache"] = cache_dir
    Path(cache_dir).expanduser().mkdir(parents=True, exist_ok=True)
    plan = _node_runtime_plan(project_root, runtime_root)
    if bool(plan["shared"]):
        shared_project_root = Path(str(plan["shared_root"]))
        shared_node_modules = Path(str(plan["node_modules_path"]))
        created = False
        if not shared_node_modules.exists():
            shared_project_root.mkdir(parents=True, exist_ok=True)
            _copy_if_exists(package_json, shared_project_root / "package.json")
            _copy_if_exists(package_lock, shared_project_root / "package-lock.json")
            _copy_if_exists(project_root / ".npmrc", shared_project_root / ".npmrc")
            subprocess.run(command, cwd=shared_project_root, check=True, env=env)
            created = True
        _replace_with_directory_symlink(project_root / "node_modules", shared_node_modules)
        plan["cache_dir"] = cache_dir
        plan["created"] = created
        plan["action"] = "create" if created else "reuse"
        plan["exists"] = True
        return plan

    subprocess.run(command, cwd=project_root, check=True, env=env)
    plan["cache_dir"] = cache_dir
    plan["created"] = True
    plan["exists"] = True
    return plan


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
    *,
    package_root: Path | None = None,
    extension_path: Path | None = None,
) -> list[str]:
    effective_package_root = package_root or Path(args.package_root).expanduser()
    effective_extension_path = extension_path or Path(args.extension_path).expanduser()
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
    command.extend(["--extension-path", str(effective_extension_path)])
    command.extend(["--package-root", str(effective_package_root)])
    command.extend(["--python-bin", str(python_bin)])
    if _is_evm_backend(args.backend):
        service_url = str(getattr(args, "wdk_evm_service_url", "") or EVM_DEFAULT_SERVICE_URL).strip()
        command.extend(["--wdk-evm-service-url", service_url or EVM_DEFAULT_SERVICE_URL])
    return command


def _is_solana_backend(backend: str) -> bool:
    return backend.strip().lower() in {"solana", "solana_local", "solana-local"}


def _is_evm_backend(backend: str) -> bool:
    return backend.strip().lower() in {
        "wdk_evm_local",
        "wdk-evm-local",
        "evm_local",
        "evm-local",
    }


EVM_DEFAULT_SERVICE_URL = "http://127.0.0.1:8081"


def _build_evm_onboard_config(args: argparse.Namespace) -> dict[str, object]:
    # The EVM wallet is provisioned on every install (best-effort). Seed creation
    # with a valid EVM network; ensure_user_evm_wallet_ready binds BOTH base and
    # ethereum (one address), so the active --network only matters when EVM is the
    # active backend.
    network = args.network.strip().lower() if _is_evm_backend(args.backend) else "base"
    if network not in {"base", "ethereum"}:
        network = "base"
    service_url = str(getattr(args, "wdk_evm_service_url", "") or EVM_DEFAULT_SERVICE_URL).strip()
    return {
        "backend": "wdk_evm_local",
        "network": network,
        "signOnly": bool(args.sign_only),
        "wdkEvmServiceUrl": service_url or EVM_DEFAULT_SERVICE_URL,
    }


def _build_solana_onboard_config(args: argparse.Namespace) -> dict[str, object]:
    # Solana is provisioned on every install (both wallets are created), so force
    # the Solana backend/network here -- this must work even when the active
    # backend chosen by the user is EVM or BTC.
    solana_active = _is_solana_backend(args.backend)
    config: dict[str, object] = {
        "backend": "solana_local",
        "network": "mainnet",
        "signOnly": bool(args.sign_only),
        "encryptUserWallets": True,
        "migratePlaintextUserWallets": True,
        "refuseMainnetWalletRecreation": True,
    }
    if solana_active and args.rpc_url.strip():
        config["rpcUrl"] = args.rpc_url.strip()
    if solana_active and args.rpc_urls.strip():
        config["rpcUrls"] = [item.strip() for item in args.rpc_urls.split(",") if item.strip()]
    return config


def _runtime_env_for_onboard(package_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    python_path = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = (
        f"{package_root}{os.pathsep}{python_path}" if python_path else str(package_root)
    )
    for var_name in (
        "AGENT_WALLET_MASTER_KEY",
        "AGENT_WALLET_APPROVAL_SECRET",
        "SOLANA_AGENT_PRIVATE_KEY",
    ):
        env.pop(var_name, None)
    return env


def _bootstrap_solana_wallet(
    python_bin: Path,
    package_root: Path,
    args: argparse.Namespace,
) -> dict[str, object] | None:
    result = subprocess.run(
        [
            str(python_bin),
            "-m",
            "agent_wallet.openclaw_cli",
            "onboard",
            "--user-id",
            args.user_id,
            "--config-json",
            json.dumps(_build_solana_onboard_config(args)),
        ],
        cwd=package_root,
        capture_output=True,
        text=True,
        check=True,
        env=_runtime_env_for_onboard(package_root),
    )
    payload = json.loads(result.stdout)
    session = dict(payload.get("session") or {})
    return {
        "ok": True,
        "user_id": session.get("user_id") or args.user_id,
        "address": session.get("address"),
        "network": session.get("network") or args.network,
        "wallet_path": session.get("wallet_path"),
        "storage_format": session.get("storage_format"),
        "created_now": bool(session.get("created_now")),
        "backend": session.get("backend"),
    }


def _bootstrap_evm_wallet(
    python_bin: Path,
    package_root: Path,
    args: argparse.Namespace,
    wdk_evm_root: Path,
) -> dict[str, object]:
    """Provision the local EVM wallet (best-effort).

    Mirrors _bootstrap_solana_wallet but for wdk_evm_local. Runs the onboard CLI,
    which calls ensure_user_evm_wallet_ready: auto-starts the local Node service,
    creates and seals the wallet password, and binds both base and ethereum.
    Failures here never abort the install -- the lazy runtime path (ensure_ready on
    first EVM use) remains the safety net.
    """
    env = _runtime_env_for_onboard(package_root)
    env["OPENCLAW_EVM_WDK_WALLET_ROOT"] = str(wdk_evm_root)
    try:
        result = subprocess.run(
            [
                str(python_bin),
                "-m",
                "agent_wallet.openclaw_cli",
                "onboard",
                "--user-id",
                args.user_id,
                "--config-json",
                json.dumps(_build_evm_onboard_config(args)),
            ],
            cwd=package_root,
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        return {"ok": False, "error": detail[-2000:]}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": "EVM onboard returned non-JSON output."}
    session = dict(payload.get("session") or {})
    wallet_path = str(session.get("wallet_path") or "")
    wallet_id = wallet_path.split("walletId=", 1)[-1] if "walletId=" in wallet_path else None
    return {
        "ok": True,
        "user_id": session.get("user_id") or args.user_id,
        "address": session.get("address"),
        "wallet_id": wallet_id,
        "networks": ["base", "ethereum"],
        "backend": session.get("backend"),
    }


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
            venv_path = package_root / ".runtime-venv"
        source_env_example_path = source_package_root / ".env.example"
        if env_example_path.resolve() == source_env_example_path.resolve():
            env_example_path = package_root / ".env.example"

    env_created = _ensure_env_file(env_path, env_example_path)
    boot_key_file_env_updated = _ensure_runtime_boot_key_file_env(env_path)
    flash_bridge_env = _ensure_flash_bridge_env(env_path, package_root)
    config_created = _ensure_openclaw_config(config_path)

    python_bin = Path(sys.executable)
    venv_created = False
    existing_wrapper = _venv_python_wrapper(venv_path)
    python_runtime: dict[str, object] = {
        "shared": False,
        "fingerprint": None,
        "shared_root": None,
        "venv_path": str(venv_path),
        "release_link_path": str(venv_path),
        "python_bin": str(_venv_python_wrapper(venv_path)),
        "action": "skipped",
        "exists": existing_wrapper.exists(),
    }
    if args.skip_python_setup and args.install_from_runtime and existing_wrapper.exists():
        python_bin = existing_wrapper
    elif not args.skip_python_setup:
        if not args.dry_run:
            python_bin, venv_created, python_runtime = _ensure_python_runtime(
                venv_path,
                package_root,
                runtime_root,
            )
        else:
            python_runtime = _python_runtime_plan(venv_path, package_root, runtime_root)
            python_bin = Path(str(python_runtime["python_bin"]))

    node_runtime = {
        "skipped": bool(args.skip_node_setup),
        "npm_bin": args.npm_bin,
        "projects": [],
    }
    node_projects = [wdk_btc_root, wdk_evm_root]
    flash_bridge_root = package_root / "scripts" / "flash-sdk-bridge"
    if (flash_bridge_root / "package.json").exists():
        node_projects.append(flash_bridge_root)

    if not args.skip_node_setup:
        if args.dry_run:
            node_runtime["projects"] = [
                {
                    **_node_runtime_plan(project_root, runtime_root),
                    "command": [
                        args.npm_bin,
                        "ci" if (project_root / "package-lock.json").exists() else "install",
                    ],
                    "cache_dir": (
                        os.environ.get("OPENCLAW_AGENT_WALLET_NPM_CACHE")
                        or str(_resolve_openclaw_home() / "npm-cache")
                    ),
                    "created": False,
                }
                for project_root in node_projects
            ]
        else:
            node_runtime["projects"] = [
                _ensure_node_runtime(args.npm_bin, project_root, runtime_root)
                for project_root in node_projects
            ]

    backend_enabled = args.backend.strip().lower() not in {"", "none"}
    pending_env = _pending_env_names() if backend_enabled else []
    configured = False
    configure_stdout = ""
    solana_onboard_result: dict[str, object] | None = None
    evm_onboard_result: dict[str, object] | None = None
    if backend_enabled and not pending_env and not args.dry_run:
        result = subprocess.run(
            _build_next_steps(
                python_bin,
                install_config_script,
                args,
                package_root=package_root,
                extension_path=extension_path,
            ),
            capture_output=True,
            text=True,
            check=True,
        )
        configured = True
        configure_stdout = result.stdout
        solana_onboard_result = _bootstrap_solana_wallet(
            python_bin,
            package_root,
            args,
        )
        # Both wallets are provisioned on every install. EVM provisioning is
        # best-effort: a failure here must not abort the install, since the lazy
        # runtime path will create the wallet on first EVM use.
        evm_onboard_result = _bootstrap_evm_wallet(
            python_bin,
            package_root,
            args,
            wdk_evm_root,
        )
        if isinstance(evm_onboard_result, dict) and not evm_onboard_result.get("ok"):
            print(
                "warning: the EVM wallet was not provisioned during install; it will "
                "be created automatically on first EVM use. Details: "
                + str(evm_onboard_result.get("error") or "unknown"),
                file=sys.stderr,
            )

    print(
        json.dumps(
            {
                "ok": True,
                "env_path": str(env_path),
                "env_created": env_created,
                "boot_key_file_env_updated": boot_key_file_env_updated,
                "flash_bridge_env": flash_bridge_env,
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
                "python_runtime": python_runtime,
                "node_runtime": node_runtime,
                "runtime_sync": runtime_sync,
                "configured": configured,
                "pending_env": pending_env,
                "solana_wallet": solana_onboard_result,
                "evm_wallet": evm_onboard_result,
                "next_configure_command": _build_next_steps(
                    python_bin,
                    install_config_script,
                    args,
                    package_root=package_root,
                    extension_path=extension_path,
                ),
                "configure_result": json.loads(configure_stdout) if configure_stdout else None,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
