"""Codex MCP bridge for the existing AgentLayer wallet runtime."""

from __future__ import annotations

import copy
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Any


SECRET_CONFIG_KEYS = {"privateKey", "masterKey", "approvalSecret"}
HOST_DEFAULT_CONFIG_KEYS = {
    "backend",
    "signOnly",
    "network",
    "rpcUrl",
    "rpcUrls",
    "rpcProviderMode",
    "providerGatewayUrl",
    "providerGatewayRpcProvider",
    "wdkBtcServiceUrl",
    "wdkBtcWalletId",
    "wdkBtcAccountIndex",
    "wdkEvmServiceUrl",
    "wdkEvmWalletId",
    "wdkEvmAccountIndex",
    "swapProvider",
    "heliusApiKey",
    "alchemyApiKey",
    "publicKey",
    "keypairPath",
    "autoCreateWallet",
    "encryptUserWallets",
    "migratePlaintextUserWallets",
    "refuseMainnetWalletRecreation",
    "openclawHome",
    "jupiterBaseUrl",
    "jupiterSwapV2BaseUrl",
    "jupiterUltraBaseUrl",
    "jupiterPriceBaseUrl",
    "jupiterPortfolioBaseUrl",
    "jupiterLendBaseUrl",
    "jupiterApiKey",
    "houdiniBaseUrl",
    "houdiniApiKey",
    "houdiniApiSecret",
    "houdiniUserIp",
    "houdiniUserAgent",
    "houdiniUserTimezone",
    "kaminoBaseUrl",
    "kaminoProgramId",
}
BACKENDS = ("solana_local", "wdk_btc_local", "wdk_evm_local")
PREVIEW_CACHE_TTL_SECONDS = 15 * 60
PRIVATE_SWAP_CACHE_TTL_SECONDS = 35 * 60
PREVIEW_BOUND_SWAP_TOOLS = {
    "swap_solana_tokens",
    "swap_solana_privately",
    "flash_trade_open_position",
    "flash_trade_close_position",
}
PRIVATE_SWAP_APPROVAL_TOOL_NAME = "swap_solana_privately"
APPROVAL_PREVIEW_TOOL_ALIASES = {
    "x402_pay_request": "x402_preview_request",
}
APPROVAL_CONTEXT_MISSING_MESSAGE = (
    "Confirmation context is not ready or has expired. Preview or intent_preview the wallet "
    "operation again, wait for explicit user confirmation, then retry execute. Do not ask the "
    "user for a manual approval token."
)

selected_wallet_backend: str | None = None
selected_solana_network: str | None = None
selected_evm_network: str | None = None
selected_btc_network: str | None = None
approval_preview_cache: dict[str, dict[str, Any]] = {}
private_swap_order_cache: dict[str, dict[str, Any]] = {}


class WalletCliError(RuntimeError):
    def __init__(self, message: str, *, code: str = "", details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _plugin_root() -> Path:
    return Path(__file__).resolve().parent


def _repo_relative_package_root() -> Path:
    return Path(__file__).resolve().parents[3] / "agent-wallet"


def _openclaw_home() -> Path:
    return Path(os.getenv("OPENCLAW_HOME", "~/.openclaw")).expanduser().resolve()


@lru_cache(maxsize=1)
def _openclaw_plugin_config() -> dict[str, Any]:
    config_path = _openclaw_home() / "openclaw.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        return {}
    plugins = payload.get("plugins")
    if not isinstance(plugins, dict):
        return {}
    entries = plugins.get("entries")
    if not isinstance(entries, dict):
        return {}
    agent_wallet = entries.get("agent-wallet")
    if not isinstance(agent_wallet, dict):
        return {}
    config = agent_wallet.get("config")
    return config if isinstance(config, dict) else {}


def _host_default_config() -> dict[str, Any]:
    plugin_config = _openclaw_plugin_config()
    defaults: dict[str, Any] = {}
    for key in HOST_DEFAULT_CONFIG_KEYS:
        value = plugin_config.get(key)
        if value is not None:
            defaults[key] = copy.deepcopy(value)
    return defaults


def _configured_backend() -> str | None:
    value = _openclaw_plugin_config().get("backend")
    if value is None:
        return None
    try:
        return _normalize_wallet_backend(value)
    except RuntimeError:
        return None


def _configured_network_for_backend(backend: str) -> str | None:
    value = _openclaw_plugin_config().get("network")
    if value in (None, ""):
        return None
    try:
        if backend == "wdk_evm_local":
            return _normalize_selectable_evm_network(value)
        if backend == "wdk_btc_local":
            return _normalize_btc_network(value)
        return _normalize_solana_network(value)
    except RuntimeError:
        return None


def _resolve_package_root() -> Path:
    candidates = [
        os.getenv("AGENT_WALLET_PACKAGE_ROOT"),
        os.getenv("OPENCLAW_AGENT_WALLET_PACKAGE_ROOT"),
        _openclaw_plugin_config().get("packageRoot"),
        str(_openclaw_home() / "agent-wallet-runtime" / "current" / "agent-wallet"),
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
        "Could not resolve the agent-wallet package root. Set AGENT_WALLET_PACKAGE_ROOT or "
        "OPENCLAW_AGENT_WALLET_PACKAGE_ROOT."
    )


def _python_bin(package_root: Path) -> str:
    for candidate in (
        os.getenv("AGENT_WALLET_PYTHON"),
        os.getenv("OPENCLAW_AGENT_WALLET_PYTHON"),
        _openclaw_plugin_config().get("pythonBin"),
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


def _cli_env(package_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    current = str(env.get("PYTHONPATH", "")).strip()
    env["PYTHONPATH"] = f"{package_root}{os.pathsep}{current}" if current else str(package_root)
    return env


def _canonical_json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _preview_digest(preview: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_text(preview).encode("utf-8")).hexdigest()


def _approval_cache_key(user_id: str, tool_name: str) -> str:
    return f"{user_id}::{tool_name}"


def _approval_preview_tool_name(tool_name: str) -> str:
    return APPROVAL_PREVIEW_TOOL_ALIASES.get(tool_name.strip(), tool_name.strip())


def _prune_approval_preview_cache() -> None:
    now = time.time()
    for key in list(approval_preview_cache):
        if float(approval_preview_cache[key].get("expires_at") or 0) <= now:
            approval_preview_cache.pop(key, None)


def _cache_preview_for_approval(user_id: str, tool_name: str, payload: dict[str, Any]) -> None:
    cache_tool_name = _approval_preview_tool_name(tool_name)
    if not isinstance(payload, dict):
        return
    if payload.get("ok") is False:
        return
    data = payload.get("data")
    if not isinstance(data, dict):
        return
    if str(data.get("mode") or "") not in {"preview", "prepare", "intent_preview"}:
        return
    summary = data.get("confirmation_summary")
    if not isinstance(summary, dict):
        return
    _prune_approval_preview_cache()
    approval_preview_cache[_approval_cache_key(user_id, cache_tool_name)] = {
        "digest": _preview_digest(data),
        "expires_at": time.time()
        + (
            PRIVATE_SWAP_CACHE_TTL_SECONDS
            if cache_tool_name == PRIVATE_SWAP_APPROVAL_TOOL_NAME
            else PREVIEW_CACHE_TTL_SECONDS
        ),
        "preview": data,
        "summary": summary,
    }
    if cache_tool_name == PRIVATE_SWAP_APPROVAL_TOOL_NAME:
        private_swap_order_cache.pop(_approval_cache_key(user_id, cache_tool_name), None)


def _latest_cached_preview(user_id: str, tool_name: str) -> dict[str, Any] | None:
    _prune_approval_preview_cache()
    return approval_preview_cache.get(_approval_cache_key(user_id, _approval_preview_tool_name(tool_name)))


def _approval_token_preview_digest(token: str) -> str:
    if not isinstance(token, str) or "." not in token:
        return ""
    encoded = token.split(".", 1)[0]
    try:
        padding = "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded + padding).decode("utf-8"))
    except Exception:
        return ""
    summary = payload.get("binding", {}).get("summary") if isinstance(payload, dict) else None
    if not isinstance(summary, dict):
        return ""
    digest = summary.get("_preview_digest")
    return digest.strip() if isinstance(digest, str) else ""


def _cached_preview_for_token(user_id: str, tool_name: str, token: str) -> dict[str, Any] | None:
    digest = _approval_token_preview_digest(token)
    if not digest:
        return None
    cached = _latest_cached_preview(user_id, tool_name)
    if not cached or cached.get("digest") != digest:
        return None
    preview = cached.get("preview")
    return preview if isinstance(preview, dict) else None


def _cache_pending_private_swap_order(
    user_id: str,
    tool_name: str,
    preview: dict[str, Any],
    details: dict[str, Any],
) -> None:
    if tool_name != PRIVATE_SWAP_APPROVAL_TOOL_NAME:
        return
    houdini_id = str(details.get("houdini_id") or "").strip()
    deposit_address = str(details.get("deposit_address") or "").strip()
    if not houdini_id or not deposit_address:
        return
    private_swap_order_cache[_approval_cache_key(user_id, tool_name)] = {
        "digest": _preview_digest(preview),
        "expires_at": time.time() + PRIVATE_SWAP_CACHE_TTL_SECONDS,
        "order": {
            "multi_id": str(details.get("multi_id") or "").strip() or None,
            "houdini_id": houdini_id,
            "deposit_address": deposit_address,
            "order": details.get("order") if isinstance(details.get("order"), dict) else {},
        },
    }


def _latest_pending_private_swap_order(
    user_id: str,
    tool_name: str,
    preview: dict[str, Any],
) -> dict[str, Any] | None:
    if tool_name != PRIVATE_SWAP_APPROVAL_TOOL_NAME:
        return None
    cached = private_swap_order_cache.get(_approval_cache_key(user_id, tool_name))
    if not cached:
        return None
    if float(cached.get("expires_at") or 0) <= time.time():
        private_swap_order_cache.pop(_approval_cache_key(user_id, tool_name), None)
        return None
    if cached.get("digest") != _preview_digest(preview):
        return None
    order = cached.get("order")
    return order if isinstance(order, dict) else None


def _clear_pending_private_swap_order(user_id: str, tool_name: str) -> None:
    if tool_name == PRIVATE_SWAP_APPROVAL_TOOL_NAME:
        private_swap_order_cache.pop(_approval_cache_key(user_id, tool_name), None)


def _list_pending_private_swap_orders(user_id: str) -> list[dict[str, Any]]:
    key = _approval_cache_key(user_id, PRIVATE_SWAP_APPROVAL_TOOL_NAME)
    pending = private_swap_order_cache.get(key)
    if not pending or float(pending.get("expires_at") or 0) <= time.time():
        private_swap_order_cache.pop(key, None)
        return []
    order = pending.get("order")
    if not isinstance(order, dict):
        return []
    return [{**order, "expires_at_ms": int(float(pending["expires_at"]) * 1000)}]


def _normalize_wallet_backend(value: Any) -> str:
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
        "evm_local": "wdk_evm_local",
        "evm-local": "wdk_evm_local",
        "btc": "wdk_btc_local",
        "bitcoin": "wdk_btc_local",
        "wdk_btc_local": "wdk_btc_local",
        "wdk-btc-local": "wdk_btc_local",
        "btc_local": "wdk_btc_local",
        "btc-local": "wdk_btc_local",
    }
    backend = aliases.get(normalized, normalized)
    if backend not in BACKENDS:
        raise RuntimeError("Wallet backend must be solana, evm, base, ethereum, btc, or bitcoin.")
    return backend


def _backend_label(backend: str) -> str:
    if backend == "wdk_evm_local":
        return "evm"
    if backend == "wdk_btc_local":
        return "bitcoin"
    return "solana"


def _normalize_evm_network(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "mainnet": "ethereum",
        "eth": "ethereum",
        "eth-mainnet": "ethereum",
        "base-mainnet": "base",
        "base_sepolia": "base-sepolia",
    }
    return aliases.get(normalized, normalized)


def _normalize_selectable_evm_network(value: Any) -> str:
    network = _normalize_evm_network(value)
    if network not in {"ethereum", "base"}:
        raise RuntimeError("EVM network must be 'ethereum' or 'base'.")
    return network


def _normalize_solana_network(value: Any) -> str | None:
    network = str(value or "").strip().lower()
    if not network:
        return None
    aliases = {
        "solana": "mainnet",
        "solana-mainnet": "mainnet",
        "mainnet_beta": "mainnet",
        "mainnet-beta": "mainnet",
    }
    normalized = aliases.get(network, network)
    if normalized in {"devnet", "testnet"}:
        raise RuntimeError("Solana devnet/testnet are no longer supported. Use mainnet.")
    if normalized != "mainnet":
        raise RuntimeError("Solana network must be mainnet.")
    return normalized


def _normalize_btc_network(value: Any) -> str | None:
    network = str(value or "").strip().lower()
    if not network:
        return None
    aliases = {
        "btc": "bitcoin",
        "bitcoin_mainnet": "bitcoin",
        "bitcoin-mainnet": "bitcoin",
        "mainnet": "bitcoin",
    }
    normalized = aliases.get(network, network)
    if normalized not in {"bitcoin", "testnet", "regtest"}:
        raise RuntimeError("Bitcoin network must be bitcoin, testnet, or regtest.")
    return normalized


def _default_backend() -> str:
    return _normalize_wallet_backend(
        os.getenv("AGENT_WALLET_BACKEND")
        or os.getenv("OPENCLAW_AGENT_WALLET_BACKEND")
        or _configured_backend()
        or "solana_local"
    )


def _default_evm_network() -> str | None:
    configured = _normalize_evm_network(os.getenv("WDK_EVM_NETWORK"))
    if configured in {"ethereum", "base"}:
        return configured
    return _configured_network_for_backend("wdk_evm_local")


def _default_solana_network() -> str:
    try:
        return (
            _normalize_solana_network(os.getenv("SOLANA_NETWORK"))
            or _configured_network_for_backend("solana_local")
            or "mainnet"
        )
    except RuntimeError:
        return "mainnet"


def _default_btc_network() -> str:
    try:
        return _normalize_btc_network(os.getenv("WDK_BTC_NETWORK")) or _configured_network_for_backend(
            "wdk_btc_local"
        ) or "bitcoin"
    except RuntimeError:
        return "bitcoin"


def _infer_backend_for_tool(tool_name: str) -> str | None:
    if (
        tool_name.startswith("get_evm_")
        or tool_name.startswith("manage_evm_")
        or tool_name.startswith("swap_evm_")
        or tool_name.startswith("transfer_evm_")
        or tool_name == "set_evm_network"
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


def _active_backend_for_tool(tool_name: str) -> str:
    return selected_wallet_backend or _infer_backend_for_tool(tool_name) or _default_backend()


def _network_for_backend(backend: str) -> str:
    if backend == "wdk_evm_local":
        return selected_evm_network or _default_evm_network() or "ethereum"
    if backend == "wdk_btc_local":
        return selected_btc_network or _default_btc_network()
    return selected_solana_network or _default_solana_network()


def _effective_config_for_backend(backend: str) -> dict[str, Any]:
    config = _host_default_config()
    config["backend"] = backend
    config["network"] = _network_for_backend(backend)
    return config


def _reject_secret_config_json(config: dict[str, Any]) -> None:
    present = sorted(key for key in SECRET_CONFIG_KEYS if str(config.get(key) or "").strip())
    if present:
        raise RuntimeError(
            "Sensitive keys are not allowed in Codex bridge config overrides: "
            + ", ".join(present)
        )


def _base_config(args: dict[str, Any], *, tool_name: str = "") -> dict[str, Any]:
    backend = (
        _normalize_wallet_backend(args.get("backend"))
        if args.get("backend") is not None
        else _active_backend_for_tool(tool_name)
    )
    config = _effective_config_for_backend(backend)
    if "config" in args:
        extra = args.get("config")
        if not isinstance(extra, dict):
            raise RuntimeError("config must be an object when provided.")
        _reject_secret_config_json(extra)
        config.update(extra)
    network_override = args.get("network")
    if network_override is not None:
        if backend == "wdk_evm_local":
            config["network"] = _normalize_selectable_evm_network(network_override)
        elif backend == "wdk_btc_local":
            config["network"] = _normalize_btc_network(network_override)
        else:
            config["network"] = _normalize_solana_network(network_override)
    return config


def _user_id() -> str:
    return (
        os.getenv("AGENT_WALLET_USER_ID")
        or os.getenv("OPENCLAW_AGENT_WALLET_USER_ID")
        or str(_openclaw_plugin_config().get("userId") or "").strip()
        or os.getenv("USER")
        or "codex-local-user"
    )


def _parse_cli_error(text: str) -> WalletCliError:
    stripped = str(text or "").strip()
    if not stripped:
        return WalletCliError("agent-wallet CLI failed.")
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return WalletCliError(stripped)
    if not isinstance(payload, dict):
        return WalletCliError(stripped)
    return WalletCliError(
        str(payload.get("error") or "agent-wallet CLI failed."),
        code=str(payload.get("code") or ""),
        details=payload.get("details") if isinstance(payload.get("details"), dict) else {},
    )


def _call_wallet_cli(command: str, extra_args: list[str]) -> dict[str, Any]:
    package_root = _resolve_package_root()
    completed = subprocess.run(
        [
            _python_bin(package_root),
            "-m",
            "agent_wallet.openclaw_cli",
            command,
            *extra_args,
        ],
        cwd=str(package_root),
        env=_cli_env(package_root),
        text=True,
        capture_output=True,
        timeout=float(os.getenv("AGENT_WALLET_CODEX_TIMEOUT", "180")),
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise _parse_cli_error(detail)
    try:
        return json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError as exc:
        raise WalletCliError(f"agent-wallet CLI returned invalid JSON: {exc}") from exc


def _invoke_tool(tool_name: str, arguments: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    return _call_wallet_cli(
        "invoke",
        [
            "--user-id",
            _user_id(),
            "--tool",
            tool_name,
            "--arguments-json",
            json.dumps(arguments),
            "--config-json",
            json.dumps(config),
        ],
    )


def _issue_approval_token(
    tool_name: str,
    config: dict[str, Any],
    preview_payload: dict[str, Any],
) -> str:
    summary = preview_payload.get("confirmation_summary")
    if not isinstance(summary, dict):
        raise RuntimeError(f"No confirmation_summary available for {tool_name}.")
    summary_for_token = dict(summary)
    summary_for_token["_preview_digest"] = _preview_digest(preview_payload)
    extra_args = [
        "--user-id",
        _user_id(),
        "--tool",
        tool_name,
        "--summary-json",
        json.dumps(summary_for_token),
        "--config-json",
        json.dumps(config),
    ]
    if preview_payload.get("is_mainnet") is True:
        extra_args.append("--mainnet-confirmed")
    if tool_name == PRIVATE_SWAP_APPROVAL_TOOL_NAME:
        extra_args.extend(["--ttl-seconds", "1800"])
    payload = _call_wallet_cli("issue-approval", extra_args)
    token = str(payload.get("approval_token") or "").strip()
    if not token:
        raise RuntimeError(f"issue-approval did not return an approval_token for {tool_name}.")
    return token


def _is_solana_swap_intent_execute(params: dict[str, Any]) -> bool:
    return str(params.get("mode") or "") == "intent_execute"


def _requires_approved_preview_payload(tool_name: str, params: dict[str, Any]) -> bool:
    if tool_name == "swap_solana_tokens" and _is_solana_swap_intent_execute(params):
        return False
    return tool_name in PREVIEW_BOUND_SWAP_TOOLS


def _looks_like_approval_context_error(message: str) -> bool:
    text = str(message or "").lower()
    return any(
        phrase in text
        for phrase in (
            "approval_token",
            "approval token",
            "approval context",
            "approved preview",
            "preview payload",
            "previewed operation",
        )
    )


def _normalize_approval_context_error(error: Exception) -> Exception:
    if not _looks_like_approval_context_error(str(error)):
        return error
    if isinstance(error, WalletCliError):
        return WalletCliError(
            f"{APPROVAL_CONTEXT_MISSING_MESSAGE} Original wallet error: {error}",
            code=error.code,
            details=error.details,
        )
    return RuntimeError(f"{APPROVAL_CONTEXT_MISSING_MESSAGE} Original wallet error: {error}")


def _attach_approval_for_execute(
    tool_name: str,
    config: dict[str, Any],
    effective_params: dict[str, Any],
) -> dict[str, Any] | None:
    mode = str(effective_params.get("mode") or "")
    if mode not in {"execute", "intent_execute"}:
        return None
    if tool_name == "swap_solana_tokens" and mode == "execute":
        raise RuntimeError(
            "Legacy exact-preview execute is disabled for Solana Jupiter swaps in Codex. "
            "Use intent_preview, wait for explicit user confirmation, then call intent_execute."
        )
    cached = _latest_cached_preview(_user_id(), tool_name)
    if cached and isinstance(cached.get("preview"), dict):
        preview = cached["preview"]
        effective_params["approval_token"] = _issue_approval_token(tool_name, config, preview)
        if _requires_approved_preview_payload(tool_name, effective_params):
            effective_params["_approved_preview"] = preview
        return cached
    approval_token = str(effective_params.get("approval_token") or "").strip()
    if approval_token and _requires_approved_preview_payload(tool_name, effective_params):
        cached_preview = _cached_preview_for_token(_user_id(), tool_name, approval_token)
        if cached_preview is not None and "_approved_preview" not in effective_params:
            effective_params["_approved_preview"] = cached_preview
    if effective_params.get("approval_token"):
        return None
    raise RuntimeError(APPROVAL_CONTEXT_MISSING_MESSAGE)


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


def _sanitize_schema(schema: dict[str, Any]) -> dict[str, Any]:
    sanitized = copy.deepcopy(schema)
    if sanitized.get("type") != "object":
        sanitized["type"] = "object"
    for key in ("oneOf", "anyOf", "allOf", "enum", "not"):
        sanitized.pop(key, None)
    properties = sanitized.get("properties")
    if isinstance(properties, dict):
        properties.pop("approval_token", None)
    else:
        sanitized["properties"] = {}
    required = sanitized.get("required")
    if isinstance(required, list):
        filtered = [field for field in required if field != "approval_token"]
        if filtered:
            sanitized["required"] = filtered
        else:
            sanitized.pop("required", None)
    sanitized.setdefault("additionalProperties", False)
    return sanitized


def _manual_tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "get_active_wallet_backend",
            "description": (
                "Show which wallet backend is active for this Codex MCP session and whether it "
                "differs from the startup default."
            ),
            "input_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            "read_only": True,
        },
        {
            "name": "set_wallet_backend",
            "description": (
                "Switch the active wallet backend for this Codex MCP session between Solana, EVM, "
                "and Bitcoin without editing runtime config files."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "backend": {
                        "type": "string",
                        "description": "solana, evm, base, ethereum, btc, or bitcoin.",
                    },
                    "wallet": {
                        "type": "string",
                        "description": "Alias for backend.",
                    },
                    "network": {
                        "type": "string",
                        "description": "Optional network override for the selected backend.",
                    },
                },
                "additionalProperties": False,
            },
            "read_only": False,
        },
        {
            "name": "set_evm_network",
            "description": (
                "Set the active EVM network for this Codex MCP session to ethereum or base."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "network": {
                        "type": "string",
                        "description": "ethereum or base.",
                    }
                },
                "required": ["network"],
                "additionalProperties": False,
            },
            "read_only": False,
        },
    ]


def _build_tool_definitions() -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for backend_name in ("solana_local", "wdk_evm_local", "wdk_btc_local"):
        for spec in _tool_specs(backend_name):
            merged.setdefault(spec["name"], spec)
    for spec in merged.values():
        spec["input_schema"] = _sanitize_schema(spec["input_schema"])
        if spec.get("read_only") is False:
            spec["description"] = (
                f"{spec['description']} Preview first when supported. Execute reuses cached "
                "approval context inside the Codex bridge."
            )
    for spec in _manual_tool_definitions():
        merged[spec["name"]] = spec
    return [merged[name] for name in sorted(merged)]


async def _handle_get_active_wallet_backend() -> dict[str, Any]:
    backend = selected_wallet_backend or _default_backend()
    return {
        "active_backend": backend,
        "active_wallet": _backend_label(backend),
        "active_network": _network_for_backend(backend),
        "configured_backend": _default_backend(),
        "session_override_active": bool(selected_wallet_backend),
        "available_wallets": ["solana", "evm", "bitcoin"],
        "usage": (
            "Use set_wallet_backend to switch between Solana, EVM, and Bitcoin for this Codex "
            "session. The runtime startup config remains unchanged."
        ),
    }


async def _handle_set_wallet_backend(params: dict[str, Any]) -> dict[str, Any]:
    global selected_wallet_backend, selected_solana_network, selected_evm_network, selected_btc_network

    requested = params.get("backend", params.get("wallet"))
    backend = _normalize_wallet_backend(requested)
    if backend == "wdk_evm_local":
        implied = params.get("network") or selected_evm_network or _default_evm_network() or "ethereum"
        selected_evm_network = _normalize_selectable_evm_network(implied)
    elif backend == "wdk_btc_local":
        selected_btc_network = _normalize_btc_network(
            params.get("network") or selected_btc_network or _default_btc_network()
        )
    else:
        selected_solana_network = _normalize_solana_network(
            params.get("network") or selected_solana_network or _default_solana_network()
        )

    config = _effective_config_for_backend(backend)
    payload = _invoke_tool(
        "get_evm_network" if backend == "wdk_evm_local" else "get_wallet_capabilities",
        {} if backend != "wdk_evm_local" else {"network": config["network"]},
        config,
    )
    if payload.get("ok") is False:
        raise RuntimeError(str(payload.get("error") or "set_wallet_backend failed"))
    selected_wallet_backend = backend
    return {
        "selected_backend": backend,
        "selected_wallet": _backend_label(backend),
        "selected_network": _network_for_backend(backend),
        "configured_backend": _default_backend(),
        "session_override_active": True,
        "config_file_changed": False,
        "usage": (
            "Subsequent wallet calls in this Codex MCP session use this wallet backend by "
            "default. The runtime startup config remains unchanged."
        ),
        "data": payload.get("data", {}),
    }


async def _handle_set_evm_network(params: dict[str, Any]) -> dict[str, Any]:
    global selected_wallet_backend, selected_evm_network

    network = _normalize_selectable_evm_network(params.get("network"))
    config = _effective_config_for_backend("wdk_evm_local")
    config["network"] = network
    payload = _invoke_tool("get_evm_network", {"network": network}, config)
    if payload.get("ok") is False:
        raise RuntimeError(str(payload.get("error") or "set_evm_network failed"))
    selected_wallet_backend = "wdk_evm_local"
    selected_evm_network = network
    return {
        "selected_backend": "wdk_evm_local",
        "selected_wallet": "evm",
        "selected_network": network,
        "session_active_network": network,
        "session_override_active": True,
        "usage": (
            "Subsequent EVM wallet calls in this Codex MCP session use this network by default. "
            "You can still override a single EVM call with its network parameter."
        ),
        "data": payload.get("data", {}),
    }


async def _handle_wallet_tool(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "list_pending_solana_private_swaps":
        return {"orders": _list_pending_private_swap_orders(_user_id())}

    config = _base_config(params, tool_name=tool_name)
    backend = _normalize_wallet_backend(config.get("backend"))
    if backend == "wdk_evm_local" and params.get("network") is None and selected_evm_network:
        params = {**params, "network": selected_evm_network}
        config["network"] = selected_evm_network

    effective_params = dict(params)
    if tool_name != "continue_solana_private_swap":
        _attach_approval_for_execute(tool_name, config, effective_params)
    else:
        cached = _latest_cached_preview(_user_id(), PRIVATE_SWAP_APPROVAL_TOOL_NAME)
        if cached and isinstance(cached.get("preview"), dict):
            effective_params["_approved_preview"] = cached["preview"]
            effective_params["approval_token"] = _issue_approval_token(
                PRIVATE_SWAP_APPROVAL_TOOL_NAME,
                config,
                cached["preview"],
            )
            pending = _latest_pending_private_swap_order(
                _user_id(), PRIVATE_SWAP_APPROVAL_TOOL_NAME, cached["preview"]
            )
            if pending and effective_params.get("_resume_private_swap_order") is None:
                effective_params["_resume_private_swap_order"] = pending
        elif not effective_params.get("approval_token"):
            raise RuntimeError(APPROVAL_CONTEXT_MISSING_MESSAGE)

    try:
        payload = _invoke_tool(tool_name, effective_params, config)
    except Exception as exc:
        raise _normalize_approval_context_error(exc) from exc

    _cache_preview_for_approval(_user_id(), tool_name, payload)
    if tool_name == "swap_solana_privately" and payload.get("ok") is True:
        data = payload.get("data")
        approved_preview = effective_params.get("_approved_preview")
        if (
            isinstance(data, dict)
            and data.get("execution_state") == "awaiting_deposit_funding"
            and isinstance(approved_preview, dict)
        ):
            _cache_pending_private_swap_order(_user_id(), tool_name, approved_preview, data)
        elif isinstance(data, dict):
            _clear_pending_private_swap_order(_user_id(), tool_name)
    if tool_name == "continue_solana_private_swap" and payload.get("ok") is True:
        data = payload.get("data")
        if isinstance(data, dict) and data.get("execution_state") == "funding_submitted":
            _clear_pending_private_swap_order(_user_id(), PRIVATE_SWAP_APPROVAL_TOOL_NAME)

    if payload.get("ok") is False:
        raise RuntimeError(str(payload.get("error") or f"{tool_name} failed"))
    return payload.get("data", {})


def build_server():
    from fastmcp import FastMCP
    from fastmcp.tools import FunctionTool

    mcp = FastMCP(
        "Agent Wallet",
        instructions=(
            "Use the local AgentLayer wallet runtime through explicit wallet tools. Keep wallet "
            "secrets local. Preview writes first when supported, and execute only after explicit "
            "user confirmation."
        ),
    )

    async def _dispatch(tool_name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        if tool_name == "get_active_wallet_backend":
            return await _handle_get_active_wallet_backend()
        if tool_name == "set_wallet_backend":
            return await _handle_set_wallet_backend(params)
        if tool_name == "set_evm_network":
            return await _handle_set_evm_network(params)
        return await _handle_wallet_tool(tool_name, params)

    for spec in _build_tool_definitions():
        tool_name = spec["name"]

        def _tool_handler_factory(name: str):
            async def _tool_handler(**kwargs: Any) -> dict[str, Any]:
                return await _dispatch(name, kwargs)

            return _tool_handler

        mcp.add_tool(
            FunctionTool(
                name=tool_name,
                description=spec["description"],
                parameters=spec["input_schema"],
                output_schema={
                    "type": "object",
                    "additionalProperties": True,
                },
                fn=_tool_handler_factory(tool_name),
            )
        )
    return mcp


def main() -> None:
    build_server().run(show_banner=False)


if __name__ == "__main__":
    main()
