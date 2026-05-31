"""Hermes Agent handlers that forward to the existing wallet CLI."""

from __future__ import annotations

import json
import os
import base64
import hashlib
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SECRET_CONFIG_KEYS = {"privateKey", "masterKey", "approvalSecret"}
BACKENDS = ("solana_local", "wdk_btc_local", "wdk_evm_local")
PREVIEW_BOUND_SWAP_TOOLS = {"swap_solana_tokens"}


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True)


def _canonical_json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _preview_digest(preview: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_text(preview).encode("utf-8")).hexdigest()


def _hermes_home() -> Path:
    return Path(os.getenv("HERMES_HOME", "~/.hermes")).expanduser()


def _preview_cache_path() -> Path:
    return _hermes_home() / "agent_wallet_preview_cache.json"


def _read_preview_cache() -> dict[str, Any]:
    path = _preview_cache_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"previews": {}}
    if not isinstance(payload, dict):
        return {"previews": {}}
    previews = payload.get("previews")
    if not isinstance(previews, dict):
        payload["previews"] = {}
    return payload


def _write_preview_cache(cache: dict[str, Any]) -> None:
    path = _preview_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, sort_keys=True), encoding="utf-8")
        path.chmod(0o600)
    except OSError:
        pass


def _prune_preview_cache(cache: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    previews = cache.get("previews")
    if not isinstance(previews, dict):
        previews = {}
    cache["previews"] = {
        key: value
        for key, value in previews.items()
        if isinstance(value, dict) and float(value.get("expires_at") or 0) > now
    }
    return cache


def _cache_swap_preview(tool_name: str, result: dict[str, Any], ttl_seconds: int = 900) -> None:
    if tool_name not in PREVIEW_BOUND_SWAP_TOOLS or result.get("ok") is not True:
        return
    preview = result.get("data")
    if not isinstance(preview, dict):
        return
    if preview.get("mode") != "preview" or preview.get("asset_type") not in {"swap", "solana-private-swap"}:
        return
    summary = preview.get("confirmation_summary")
    if not isinstance(summary, dict):
        return
    digest = _preview_digest(preview)
    cache = _prune_preview_cache(_read_preview_cache())
    cache["previews"][digest] = {
        "expires_at": time.time() + ttl_seconds,
        "preview": preview,
        "confirmation_summary": summary,
    }
    _write_preview_cache(cache)


def _lookup_preview_for_summary(summary: dict[str, Any]) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    cache = _prune_preview_cache(_read_preview_cache())
    for digest, entry in cache.get("previews", {}).items():
        if not isinstance(entry, dict):
            continue
        if entry.get("confirmation_summary") == summary and isinstance(entry.get("preview"), dict):
            _write_preview_cache(cache)
            return str(digest), entry["preview"]
    _write_preview_cache(cache)
    return None, None


def _approval_token_preview_digest(token: str) -> str:
    if not isinstance(token, str) or "." not in token:
        return ""
    encoded_payload = token.split(".", 1)[0]
    try:
        padding = "=" * (-len(encoded_payload) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded_payload + padding).decode("utf-8"))
    except Exception:
        return ""
    summary = payload.get("binding", {}).get("summary") if isinstance(payload, dict) else None
    if not isinstance(summary, dict):
        return ""
    digest = summary.get("_preview_digest")
    return str(digest).strip() if isinstance(digest, str) else ""


def _lookup_preview_for_token(token: str) -> dict[str, Any] | None:
    digest = _approval_token_preview_digest(token)
    if not digest:
        return None
    cache = _prune_preview_cache(_read_preview_cache())
    entry = cache.get("previews", {}).get(digest)
    _write_preview_cache(cache)
    if isinstance(entry, dict) and isinstance(entry.get("preview"), dict):
        return entry["preview"]
    return None


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


def _script_path(package_root: Path, name: str) -> Path:
    script = package_root / "scripts" / name
    if not script.exists():
        raise RuntimeError(f"Required host script is missing: {script}")
    return script


def _user_id(args: dict[str, Any]) -> str:
    value = (
        args.get("user_id")
        or os.getenv("AGENT_WALLET_USER_ID")
        or os.getenv("OPENCLAW_AGENT_WALLET_USER_ID")
        or os.getenv("USER")
        or "hermes-local-user"
    )
    return str(value).strip() or "hermes-local-user"


def _normalize_backend(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "sol": "solana_local",
        "solana": "solana_local",
        "solana_local": "solana_local",
        "solana-local": "solana_local",
        "evm": "wdk_evm_local",
        "ethereum": "wdk_evm_local",
        "eth": "wdk_evm_local",
        "base": "wdk_evm_local",
        "wdk_evm_local": "wdk_evm_local",
        "wdk-evm-local": "wdk_evm_local",
        "btc": "wdk_btc_local",
        "bitcoin": "wdk_btc_local",
        "wdk_btc_local": "wdk_btc_local",
        "wdk-btc-local": "wdk_btc_local",
    }
    backend = aliases.get(normalized, normalized)
    if backend not in BACKENDS:
        raise RuntimeError(
            "Wallet backend must be one of solana_local, wdk_btc_local, or wdk_evm_local."
        )
    return backend


def _infer_backend_for_tool(tool_name: str) -> str | None:
    if (
        tool_name.startswith("get_evm_")
        or tool_name.startswith("manage_evm_")
        or tool_name.startswith("swap_evm_")
        or tool_name.startswith("transfer_evm_")
        or tool_name == "agent_wallet_evm_status"
        or tool_name == "agent_wallet_evm_setup"
    ):
        return "wdk_evm_local"
    if tool_name.startswith("get_btc_") or tool_name == "transfer_btc":
        return "wdk_btc_local"
    if (
        "solana" in tool_name
        or "jupiter" in tool_name
        or "kamino" in tool_name
        or "bags" in tool_name
        or tool_name
        in {
            "transfer_sol",
            "transfer_spl_token",
            "sign_wallet_message",
            "close_empty_token_accounts",
            "get_wallet_portfolio",
            "get_solana_token_prices",
        }
    ):
        return "solana_local"
    return None


def _normalize_network_for_backend(backend: str, raw_network: Any) -> str:
    network = str(raw_network or "").strip().lower()
    if backend == "wdk_evm_local":
        aliases = {
            "mainnet": "ethereum",
            "eth": "ethereum",
            "eth-mainnet": "ethereum",
            "base-mainnet": "base",
        }
        normalized = aliases.get(network, network)
        if normalized in {"sepolia", "base-sepolia", "base_sepolia"}:
            raise RuntimeError("EVM testnets are no longer supported. Use ethereum or base.")
        return normalized if normalized in {"ethereum", "base"} else "ethereum"
    if backend == "wdk_btc_local":
        aliases = {
            "btc": "bitcoin",
            "bitcoin_mainnet": "bitcoin",
            "bitcoin-mainnet": "bitcoin",
            "mainnet": "bitcoin",
        }
        normalized = aliases.get(network, network)
        if normalized in {"testnet", "regtest"}:
            raise RuntimeError("Bitcoin testnet/regtest are no longer supported. Use bitcoin.")
        return normalized if normalized == "bitcoin" else "bitcoin"
    aliases = {
        "solana": "mainnet",
        "solana-mainnet": "mainnet",
        "mainnet_beta": "mainnet",
        "mainnet-beta": "mainnet",
    }
    normalized = aliases.get(network, network)
    if normalized in {"devnet", "testnet"}:
        raise RuntimeError("Solana devnet/testnet are no longer supported. Use mainnet.")
    return normalized if normalized == "mainnet" else "mainnet"


def _reject_secret_config(config: dict[str, Any]) -> None:
    present = sorted(key for key in SECRET_CONFIG_KEYS if str(config.get(key) or "").strip())
    if present:
        raise RuntimeError(
            "Sensitive keys are not allowed in Hermes wallet bridge config: "
            + ", ".join(present)
            + ". Use sealed_keys.json and protected environment injection."
        )


def _base_config(args: dict[str, Any], *, tool_name: str | None = None) -> dict[str, Any]:
    raw = args.get("config") or {}
    if not isinstance(raw, dict):
        raise RuntimeError("config must be a JSON object when provided.")
    config = dict(raw)
    backend = args.get("backend") or os.getenv("AGENT_WALLET_BACKEND")
    if not backend and tool_name:
        backend = _infer_backend_for_tool(tool_name)
    if backend:
        config["backend"] = _normalize_backend(backend)
    network = args.get("network") or os.getenv("AGENT_WALLET_NETWORK") or config.get("network")
    if backend:
        config["network"] = _normalize_network_for_backend(config["backend"], network)
    elif network:
        config["network"] = str(network).strip()
    _reject_secret_config(config)
    return config


def _cli_env(package_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    prior = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(package_root) if not prior else f"{package_root}{os.pathsep}{prior}"
    if not env.get("AGENT_WALLET_BOOT_KEY"):
        key_file = env.get("AGENT_WALLET_BOOT_KEY_FILE", "").strip()
        if key_file:
            try:
                boot_key = Path(key_file).expanduser().read_text(encoding="utf-8").strip()
            except OSError:
                boot_key = ""
            if boot_key:
                env["AGENT_WALLET_BOOT_KEY"] = boot_key
    return env


def _call_wallet_cli(args: dict[str, Any]) -> dict[str, Any]:
    package_root = _resolve_package_root()
    tool_name = str(args.get("tool_name") or "").strip()
    if not tool_name:
        raise RuntimeError("tool_name is required.")
    config = _base_config(args, tool_name=tool_name)

    tool_args = args.get("arguments") or {}
    if not isinstance(tool_args, dict):
        raise RuntimeError("arguments must be a JSON object when provided.")
    if tool_name in PREVIEW_BOUND_SWAP_TOOLS and str(tool_args.get("mode") or "") == "execute":
        approval_token = str(tool_args.get("approval_token") or "").strip()
        cached_preview = _lookup_preview_for_token(approval_token)
        if cached_preview is not None and "_approved_preview" not in tool_args:
            tool_args = dict(tool_args)
            tool_args["_approved_preview"] = cached_preview

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
        result = json.loads(completed.stdout.strip() or "{}")
        _cache_swap_preview(tool_name, result)
        return result
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"wallet CLI returned invalid JSON: {exc}"}


def _run_host_script(
    package_root: Path,
    script_name: str,
    script_args: list[str],
    *,
    stdin_text: str | None = None,
) -> dict[str, Any]:
    command = [
        _python_bin(package_root),
        str(_script_path(package_root, script_name)),
        *script_args,
    ]
    completed = subprocess.run(
        command,
        cwd=str(package_root),
        env=_cli_env(package_root),
        text=True,
        input=stdin_text,
        capture_output=True,
        timeout=float(os.getenv("AGENT_WALLET_HERMES_TIMEOUT", "120")),
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        return {"ok": False, "error": detail or f"host script exited {completed.returncode}"}
    try:
        return json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"host script returned invalid JSON: {exc}"}


def _call_issue_approval(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("user_confirmed") is not True:
        raise RuntimeError(
            "user_confirmed=true is required after explicit user approval of the exact confirmation_summary."
        )
    package_root = _resolve_package_root()
    tool_name = str(args.get("tool_name") or "").strip()
    if not tool_name:
        raise RuntimeError("tool_name is required.")
    config = _base_config(args, tool_name=tool_name)

    summary = args.get("confirmation_summary")
    if not isinstance(summary, dict) or not summary:
        raise RuntimeError("confirmation_summary must be the non-empty object returned by preview/prepare.")
    summary_for_token = dict(summary)
    preview_digest, _preview = _lookup_preview_for_summary(summary)
    if preview_digest:
        summary_for_token["_preview_digest"] = preview_digest

    command = [
        _python_bin(package_root),
        "-m",
        "agent_wallet.openclaw_cli",
        "issue-approval",
        "--user-id",
        _user_id(args),
        "--tool",
        tool_name,
        "--summary-json",
        json.dumps(summary_for_token),
        "--config-json",
        json.dumps(config),
    ]
    if args.get("mainnet_confirmed") is True:
        command.append("--mainnet-confirmed")
    ttl_seconds = args.get("ttl_seconds")
    if ttl_seconds is not None:
        ttl = int(ttl_seconds)
        if ttl <= 0 or ttl > 3600:
            raise RuntimeError("ttl_seconds must be between 1 and 3600.")
        command.extend(["--ttl-seconds", str(ttl)])

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


def _call_evm_status(args: dict[str, Any]) -> dict[str, Any]:
    package_root = _resolve_package_root()
    command = ["status"]
    user_id = str(args.get("user_id") or "").strip()
    network = str(args.get("network") or "").strip()
    service_url = str(args.get("service_url") or "").strip()
    if user_id:
        command.extend(["--user-id", user_id])
    if network:
        command.extend(["--network", network])
    if service_url:
        command.extend(["--service-url", service_url])
    return _run_host_script(package_root, "manage_openclaw_evm_wallet.py", command)


def _call_evm_setup(args: dict[str, Any]) -> dict[str, Any]:
    package_root = _resolve_package_root()
    password = str(args.get("password") or "").strip()
    if not password:
        raise RuntimeError("password is required.")
    command = [
        "--user-id",
        _user_id(args),
        "--password-stdin",
    ]
    network = str(args.get("network") or "").strip()
    label = str(args.get("label") or "").strip()
    service_url = str(args.get("service_url") or "").strip()
    auto_start_service = args.get("auto_start_service")
    bind_network_pair = args.get("bind_network_pair")
    if network:
        command.extend(["--network", network])
    if label:
        command.extend(["--label", label])
    if service_url:
        command.extend(["--service-url", service_url])
    if auto_start_service is False:
        command.append("--no-auto-start-service")
    if bind_network_pair is False:
        command.append("--no-bind-network-pair")
    return _run_host_script(
        package_root,
        "bootstrap_openclaw_evm.py",
        command,
        stdin_text=f"{password}\n",
    )


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


def agent_wallet_approve(args: dict, **kwargs) -> str:
    try:
        return _json(_call_issue_approval(args or {}))
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


def agent_wallet_evm_status(args: dict, **kwargs) -> str:
    try:
        return _json(_call_evm_status(args or {}))
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})


def agent_wallet_evm_setup(args: dict, **kwargs) -> str:
    try:
        return _json(_call_evm_setup(args or {}))
    except Exception as exc:
        return _json({"ok": False, "error": str(exc)})
