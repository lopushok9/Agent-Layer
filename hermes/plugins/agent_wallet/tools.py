"""Hermes Agent handlers that forward to the existing wallet CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


SECRET_CONFIG_KEYS = {"privateKey", "masterKey", "approvalSecret"}
BACKENDS = ("solana_local", "wdk_btc_local", "wdk_evm_local")


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True)


def _repo_relative_package_root() -> Path:
    return Path(__file__).resolve().parents[3] / "agent-wallet"


def _resolve_package_root() -> Path:
    candidates = [
        os.getenv("AGENT_WALLET_PACKAGE_ROOT"),
        os.getenv("OPENCLAW_AGENT_WALLET_PACKAGE_ROOT"),
        str(_repo_relative_package_root()),
        str(Path.cwd() / "agent-wallet"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        root = Path(candidate).expanduser().resolve()
        if (root / "agent_wallet" / "__init__.py").exists():
            return root
    raise RuntimeError(
        "Could not resolve agent-wallet package root. Set AGENT_WALLET_PACKAGE_ROOT."
    )


def _python_bin(package_root: Path) -> str:
    for candidate in (
        os.getenv("AGENT_WALLET_PYTHON"),
        os.getenv("OPENCLAW_AGENT_WALLET_PYTHON"),
        str(package_root / ".venv" / "bin" / "python"),
        str(package_root / ".runtime-venv" / "bin" / "python"),
        "python3",
    ):
        if not candidate:
            continue
        resolved = Path(candidate).expanduser()
        if resolved.is_absolute() and not resolved.exists():
            continue
        return str(resolved)
    return "python3"


def _user_id(args: dict[str, Any]) -> str:
    value = (
        args.get("user_id")
        or os.getenv("AGENT_WALLET_USER_ID")
        or os.getenv("OPENCLAW_AGENT_WALLET_USER_ID")
        or os.getenv("USER")
        or "hermes-local-user"
    )
    return str(value).strip() or "hermes-local-user"


def _reject_secret_config(config: dict[str, Any]) -> None:
    present = sorted(key for key in SECRET_CONFIG_KEYS if str(config.get(key) or "").strip())
    if present:
        raise RuntimeError(
            "Sensitive keys are not allowed in Hermes wallet bridge config: "
            + ", ".join(present)
            + ". Use sealed_keys.json and protected environment injection."
        )


def _base_config(args: dict[str, Any]) -> dict[str, Any]:
    raw = args.get("config") or {}
    if not isinstance(raw, dict):
        raise RuntimeError("config must be a JSON object when provided.")
    config = dict(raw)
    backend = args.get("backend") or os.getenv("AGENT_WALLET_BACKEND")
    network = args.get("network") or os.getenv("AGENT_WALLET_NETWORK")
    if backend:
        config["backend"] = str(backend).strip()
    if network:
        config["network"] = str(network).strip()
    _reject_secret_config(config)
    return config


def _cli_env(package_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    prior = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(package_root) if not prior else f"{package_root}{os.pathsep}{prior}"
    return env


def _call_wallet_cli(args: dict[str, Any]) -> dict[str, Any]:
    package_root = _resolve_package_root()
    config = _base_config(args)
    tool_name = str(args.get("tool_name") or "").strip()
    if not tool_name:
        raise RuntimeError("tool_name is required.")

    tool_args = args.get("arguments") or {}
    if not isinstance(tool_args, dict):
        raise RuntimeError("arguments must be a JSON object when provided.")

    command = [
        _python_bin(package_root),
        "-m",
        "agent_wallet.openclaw_cli",
        "invoke",
        "--user-id",
        _user_id(args),
        "--tool",
        tool_name,
        "--arguments-json",
        json.dumps(tool_args),
        "--config-json",
        json.dumps(config),
    ]
    completed = subprocess.run(
        command,
        cwd=str(package_root),
        env=_cli_env(package_root),
        text=True,
        capture_output=True,
        timeout=float(os.getenv("AGENT_WALLET_HERMES_TIMEOUT", "120")),
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        return {"ok": False, "error": detail or f"wallet CLI exited {completed.returncode}"}
    try:
        return json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"wallet CLI returned invalid JSON: {exc}"}


class _SchemaOnlyBackend:
    def __init__(self, *, name: str, chain: str, network: str):
        self.name = name
        self.chain = chain
        self.network = network
        self.sign_only = True

    def get_capabilities(self):
        from agent_wallet.wallet_layer.base import WalletCapabilities

        return WalletCapabilities(
            backend=self.name,
            chain=self.chain,
            custody_model="local",
            sign_only=True,
            has_signer=False,
            can_get_address=True,
            can_get_balance=True,
            external_dependencies=[],
        )

    async def get_address(self):
        return None

    async def get_balance(self, address=None):
        return {}


def _schema_backend(name: str) -> _SchemaOnlyBackend:
    if name == "wdk_btc_local":
        return _SchemaOnlyBackend(name=name, chain="bitcoin", network="bitcoin")
    if name == "wdk_evm_local":
        return _SchemaOnlyBackend(name=name, chain="evm", network="ethereum")
    return _SchemaOnlyBackend(name="solana_local", chain="solana", network="mainnet")


def _tool_specs(backend_name: str) -> list[dict[str, Any]]:
    package_root = _resolve_package_root()
    package_root_text = str(package_root)
    inserted = package_root_text not in sys.path
    if inserted:
        sys.path.insert(0, package_root_text)
    try:
        from agent_wallet.openclaw_adapter import OpenClawWalletAdapter

        adapter = OpenClawWalletAdapter(_schema_backend(backend_name))
        return [tool.model_dump() for tool in adapter.list_tools()]
    finally:
        if inserted:
            try:
                sys.path.remove(package_root_text)
            except ValueError:
                pass


def agent_wallet_tools(args: dict, **kwargs) -> str:
    try:
        requested = str((args or {}).get("backend") or "all").strip() or "all"
        backend_names = BACKENDS if requested == "all" else (requested,)
        invalid = [name for name in backend_names if name not in BACKENDS]
        if invalid:
            return _json({"ok": False, "error": f"Unknown backend: {', '.join(invalid)}"})
        tools = {
            backend_name: _tool_specs(backend_name)
            for backend_name in backend_names
        }
        return _json(
            {
                "ok": True,
                "bridge": "hermes-agent-wallet",
                "backends": list(backend_names),
                "tools": tools,
                "usage": (
                    "Call agent_wallet_invoke with one of these tool names and JSON arguments. "
                    "Use preview before execute. Execute requires a host-issued approval_token."
                ),
            }
        )
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


def agent_wallet_invoke(args: dict, **kwargs) -> str:
    try:
        return _json(_call_wallet_cli(args or {}))
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})
