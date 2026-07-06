"""Codex MCP bridge for the existing AgentLayer wallet runtime."""

from __future__ import annotations

import atexit
import asyncio
import copy
import base64
import hashlib
import json
import os
import selectors
import signal
import subprocess
import sys
import threading
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
    "jupiterApiKey",
    "kaminoBaseUrl",
    "kaminoProgramId",
}
BACKENDS = ("solana_local", "wdk_btc_local", "wdk_evm_local")
PREVIEW_CACHE_TTL_SECONDS = 15 * 60
PREVIEW_BOUND_SWAP_TOOLS = {
    "swap_solana_tokens",
    "flash_trade_open_position",
    "flash_trade_close_position",
}
AUTONOMOUS_BASE_SWAP_TOOLS = {"swap_evm_tokens", "swap_evm_uniswap_tokens"}
AUTONOMOUS_DEFI_TOOLS = {
    "manage_evm_aave_position",
    "manage_evm_lido_position",
    "manage_evm_lido_withdrawal",
    "manage_evm_morpho_market_position",
    "manage_evm_morpho_vault_position",
}
APPROVAL_PREVIEW_TOOL_ALIASES = {
    "x402_pay_request": "x402_preview_request",
}
APPROVAL_CONTEXT_MISSING_MESSAGE = (
    "Confirmation context is not ready or has expired. Preview or intent_preview the wallet "
    "operation again, wait for explicit user confirmation, then retry execute. Do not ask the "
    "user for a manual approval token."
)
# Tools served by the long-lived resident read worker instead of a cold CLI
# subprocess. Seeded with the legacy floor; _build_tool_definitions() extends
# it with every adapter-declared read-only tool at server start.
RESIDENT_READ_ONLY_TOOLS = {
    "get_wallet_balance",
    "get_wallet_portfolio",
}

selected_wallet_backend: str | None = None
selected_solana_network: str | None = None
selected_evm_network: str | None = None
selected_btc_network: str | None = None
approval_preview_cache: dict[str, dict[str, Any]] = {}
resident_read_workers: dict[str, "_ResidentReadWorker"] = {}
# Guards approval_preview_cache against races once wallet calls run concurrently
# via asyncio.to_thread. Reentrant so prune helpers can be nested under writers.
_approval_cache_lock = threading.RLock()
_resident_worker_lock = threading.RLock()


class WalletCliError(RuntimeError):
    def __init__(self, message: str, *, code: str = "", details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ResidentReadWorkerTransportError(RuntimeError):
    """Raised when the long-lived read worker transport fails."""


def _plugin_root() -> Path:
    return Path(__file__).resolve().parent


def _repo_relative_package_root() -> Path:
    return Path(__file__).resolve().parents[3] / "agent-wallet"


def _openclaw_home() -> Path:
    return Path(os.getenv("OPENCLAW_HOME", "~/.openclaw")).expanduser().resolve()


@lru_cache(maxsize=1)
def _openclaw_plugin_config() -> dict[str, Any]:
    # Cached for the process lifetime: openclaw.json is read once per MCP server
    # start. Edits to plugin config require restarting the bridge to take effect.
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
    with _approval_cache_lock:
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
    with _approval_cache_lock:
        _prune_approval_preview_cache()
        approval_preview_cache[_approval_cache_key(user_id, cache_tool_name)] = {
            "digest": _preview_digest(data),
            "expires_at": time.time() + PREVIEW_CACHE_TTL_SECONDS,
            "preview": data,
            "summary": summary,
        }


def _latest_cached_preview(user_id: str, tool_name: str) -> dict[str, Any] | None:
    with _approval_cache_lock:
        _prune_approval_preview_cache()
        return approval_preview_cache.get(_approval_cache_key(user_id, _approval_preview_tool_name(tool_name)))


def _consume_cached_preview(user_id: str, tool_name: str) -> None:
    """Drop the cached preview once a successful execute has consumed it.

    Without this, a preview lingers for the full TTL and a duplicate execute
    call could re-run the operation from stale approval context — the runtime's
    single-use nonce registry cannot stop it, because the bridge runs each
    invoke in a fresh subprocess (empty registry) and mints a new token per
    execute. Requiring a fresh preview before the next execute is the safe rule.
    """
    with _approval_cache_lock:
        approval_preview_cache.pop(
            _approval_cache_key(user_id, _approval_preview_tool_name(tool_name)), None
        )


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
    }
    return aliases.get(normalized, normalized)


def _normalize_selectable_evm_network(value: Any) -> str:
    network = _normalize_evm_network(value)
    if network in {"sepolia", "base-sepolia", "base_sepolia"}:
        raise RuntimeError("EVM testnets are no longer supported. Use ethereum or base.")
    if network not in {"ethereum", "base"}:
        raise RuntimeError("EVM network must be 'ethereum' or 'base'.")
    return network


def _implied_evm_network_from_backend_alias(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"base", "base-mainnet"}:
        return "base"
    if normalized in {"ethereum", "eth", "mainnet", "eth-mainnet"}:
        return "ethereum"
    return None


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
    if normalized in {"testnet", "regtest"}:
        raise RuntimeError("Bitcoin testnet/regtest are no longer supported. Use bitcoin.")
    if normalized != "bitcoin":
        raise RuntimeError("Bitcoin network must be bitcoin.")
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
    requested_backend = args.get("backend")
    backend = (
        _normalize_wallet_backend(requested_backend)
        if requested_backend is not None
        else _active_backend_for_tool(tool_name)
    )
    config = _effective_config_for_backend(backend)
    if backend == "wdk_evm_local":
        implied_evm_network = _implied_evm_network_from_backend_alias(requested_backend)
        if implied_evm_network and args.get("network") is None:
            config["network"] = implied_evm_network
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


def _cli_timeout_seconds() -> float:
    """Parse the CLI timeout from env, falling back to 180s on bad values."""
    raw = os.getenv("AGENT_WALLET_CODEX_TIMEOUT", "180")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 180.0
    return value if value > 0 else 180.0


def _call_wallet_cli(command: str, extra_args: list[str]) -> dict[str, Any]:
    package_root = _resolve_package_root()
    timeout_seconds = _cli_timeout_seconds()
    try:
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
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        # Surface a clean, actionable message instead of the raw TimeoutExpired
        # repr, which would echo the full argv (approval_token, config JSON).
        raise WalletCliError(
            f"agent-wallet CLI '{command}' timed out after {timeout_seconds:g}s. "
            "Retry, or raise AGENT_WALLET_CODEX_TIMEOUT if the network is slow.",
            code="timeout",
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise _parse_cli_error(detail)
    # The CLI contract is a single JSON line on stdout. Parse the last non-empty
    # line so a stray print/warning ahead of it from the runtime cannot break an
    # otherwise-successful call.
    stdout = completed.stdout.strip()
    if not stdout:
        return {}
    last_line = stdout.splitlines()[-1].strip()
    try:
        return json.loads(last_line)
    except json.JSONDecodeError as exc:
        raise WalletCliError(f"agent-wallet CLI returned invalid JSON: {exc}") from exc


def _invoke_tool(
    tool_name: str,
    arguments: dict[str, Any],
    config: dict[str, Any],
    *,
    approval_summary: dict[str, Any] | None = None,
    approval_mainnet_confirmed: bool = False,
) -> dict[str, Any]:
    extra_args = [
        "--user-id",
        _user_id(),
        "--tool",
        tool_name,
        "--arguments-json",
        json.dumps(arguments),
        "--config-json",
        json.dumps(config),
    ]
    if approval_summary is not None:
        # The invoke subprocess mints the approval token itself, so an execute
        # costs one cold start instead of two (issue-approval + invoke).
        extra_args.extend(["--approval-summary-json", json.dumps(approval_summary)])
        if approval_mainnet_confirmed:
            extra_args.append("--approval-mainnet-confirmed")
    return _call_wallet_cli("invoke", extra_args)


class _ResidentReadWorker:
    def __init__(self, *, user_id: str, config: dict[str, Any]):
        self.user_id = user_id
        self.config = copy.deepcopy(config)
        self.package_root = _resolve_package_root()
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.RLock()
        self._request_id = 0
        self._stderr_lines: list[str] = []
        self._stderr_thread: threading.Thread | None = None
        self._last_used = time.monotonic()

    def touch(self) -> None:
        self._last_used = time.monotonic()

    def idle_seconds(self) -> float:
        return time.monotonic() - self._last_used

    def _command(self) -> list[str]:
        return [
            _python_bin(self.package_root),
            "-m",
            "agent_wallet.openclaw_cli",
            "read-worker",
            "--user-id",
            self.user_id,
            "--config-json",
            json.dumps(self.config),
        ]

    def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        try:
            for raw_line in process.stderr:
                line = raw_line.strip()
                if not line:
                    continue
                with self._lock:
                    self._stderr_lines.append(line)
                    if len(self._stderr_lines) > 20:
                        self._stderr_lines = self._stderr_lines[-20:]
        except Exception:
            return

    def _stderr_summary(self) -> str:
        with self._lock:
            if not self._stderr_lines:
                return ""
            return " | ".join(self._stderr_lines[-5:])

    def _ensure_started(self) -> subprocess.Popen[str]:
        with self._lock:
            process = self._process
            if process is not None and process.poll() is None:
                return process
            try:
                process = subprocess.Popen(
                    self._command(),
                    cwd=str(self.package_root),
                    env=_cli_env(self.package_root),
                    text=True,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=1,
                )
            except Exception as exc:
                raise ResidentReadWorkerTransportError(
                    f"Could not start resident read worker: {exc}"
                ) from exc
            self._process = process
            self._stderr_lines = []
            self._stderr_thread = threading.Thread(
                target=self._drain_stderr,
                name="agent-wallet-read-worker-stderr",
                daemon=True,
            )
            self._stderr_thread.start()
            return process

    def warm(self) -> None:
        """Spawn the worker eagerly, without waiting for a request/response.

        Lets the interpreter boot, module imports, and read-only onboarding
        happen off the critical path of the first real read-only tool call.
        """
        try:
            self._ensure_started()
        except ResidentReadWorkerTransportError:
            pass

    def close(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
        if process is None:
            return
        try:
            if process.poll() is None and process.stdin is not None:
                process.stdin.write(json.dumps({"op": "shutdown"}) + "\n")
                process.stdin.flush()
        except Exception:
            pass
        try:
            process.wait(timeout=1)
        except Exception:
            try:
                process.terminate()
                process.wait(timeout=1)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

    def invoke(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.touch()
            process = self._ensure_started()
            if process.stdin is None or process.stdout is None:
                self.close()
                raise ResidentReadWorkerTransportError("Resident read worker stdio is unavailable.")
            self._request_id += 1
            request_id = str(self._request_id)
            request = {
                "id": request_id,
                "tool": tool_name,
                "arguments": arguments,
            }
            try:
                process.stdin.write(json.dumps(request) + "\n")
                process.stdin.flush()
            except Exception as exc:
                self.close()
                raise ResidentReadWorkerTransportError(
                    f"Could not write to resident read worker: {exc}"
                ) from exc

            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            events = selector.select(timeout=_cli_timeout_seconds())
            selector.close()
            if not events:
                self.close()
                raise ResidentReadWorkerTransportError(
                    f"Resident read worker timed out after {_cli_timeout_seconds():g}s."
                )
            response_line = process.stdout.readline()
            if not response_line:
                self.close()
                stderr_summary = self._stderr_summary()
                detail = f" Worker stderr: {stderr_summary}" if stderr_summary else ""
                raise ResidentReadWorkerTransportError(
                    "Resident read worker exited without a response." + detail
                )
            try:
                response = json.loads(response_line)
            except json.JSONDecodeError as exc:
                self.close()
                raise ResidentReadWorkerTransportError(
                    f"Resident read worker returned invalid JSON: {exc}"
                ) from exc
            if str(response.get("id") or "") != request_id:
                self.close()
                raise ResidentReadWorkerTransportError(
                    "Resident read worker response id did not match the request."
                )
            if response.get("ok") is False:
                raise WalletCliError(
                    str(response.get("error") or "resident read worker failed."),
                    code=str(response.get("code") or ""),
                    details=response.get("details")
                    if isinstance(response.get("details"), dict)
                    else {},
                )
            payload = response.get("payload")
            if not isinstance(payload, dict):
                raise ResidentReadWorkerTransportError(
                    "Resident read worker returned a non-object payload."
                )
            return payload


def _resident_worker_cache_key(user_id: str, config: dict[str, Any]) -> str:
    return _canonical_json_text(
        {
            "user_id": user_id,
            "config": config,
        }
    )


def _resident_worker_idle_seconds() -> float:
    """Idle threshold (seconds) after which an unused resident worker for a
    config that is no longer the active one gets reaped. Falls back to 10
    minutes on bad values."""
    raw = os.getenv("AGENT_WALLET_READ_WORKER_IDLE_SECONDS", "600")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 600.0
    return value if value > 0 else 600.0


def _evict_idle_resident_read_workers(*, keep_key: str) -> None:
    """Close resident workers other than `keep_key` that have been idle past
    the configured threshold.

    Each distinct (user_id, config) pair (e.g. switching Solana network or
    wallet backend mid-session) keeps its own resident subprocess alive
    indefinitely otherwise, since nothing previously evicted them. This
    bounds that growth without adding a background timer thread: eviction
    piggybacks on the next lookup instead.
    """
    idle_limit = _resident_worker_idle_seconds()
    with _resident_worker_lock:
        stale_keys = [
            key
            for key, worker in resident_read_workers.items()
            if key != keep_key and worker.idle_seconds() > idle_limit
        ]
        stale_workers = [resident_read_workers.pop(key) for key in stale_keys]
    for worker in stale_workers:
        worker.close()


def _resident_read_worker_for_config(user_id: str, config: dict[str, Any]) -> _ResidentReadWorker:
    key = _resident_worker_cache_key(user_id, config)
    _evict_idle_resident_read_workers(keep_key=key)
    with _resident_worker_lock:
        worker = resident_read_workers.get(key)
        if worker is None:
            worker = _ResidentReadWorker(user_id=user_id, config=config)
            resident_read_workers[key] = worker
        return worker


def _shutdown_resident_read_workers() -> None:
    with _resident_worker_lock:
        workers = list(resident_read_workers.values())
        resident_read_workers.clear()
    for worker in workers:
        worker.close()


atexit.register(_shutdown_resident_read_workers)


def _handle_termination_signal(signum: int, frame: Any) -> None:
    """Close resident read worker subprocesses on SIGTERM, then terminate
    normally.

    atexit handlers only run on normal interpreter shutdown; Python's
    default SIGTERM disposition terminates the process immediately without
    unwinding to atexit. Hosts that gracefully stop this MCP server (e.g.
    closing a Claude Code / Codex session) send SIGTERM, so without this the
    resident worker subprocesses leaked past every normal shutdown, not just
    an abrupt kill -9. (SIGINT is not handled here: Python's default handler
    raises KeyboardInterrupt, which unwinds to a normal interpreter
    shutdown and already triggers the atexit hook above.)
    """
    _shutdown_resident_read_workers()
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def _install_termination_signal_handlers() -> None:
    try:
        signal.signal(signal.SIGTERM, _handle_termination_signal)
    except (ValueError, OSError):
        # e.g. signal.signal() called outside the main thread.
        pass


def _prewarm_resident_read_worker() -> None:
    """Best-effort background warm-up of the default resident read worker.

    server.py is a persistent stdio MCP process kept alive for the whole
    host session, but the resident worker itself only used to spawn lazily
    on the first read-only tool call (get_wallet_balance /
    get_wallet_portfolio, e.g. /wallet-sol), putting interpreter boot +
    onboarding on the critical path of that first call. Kick it off in a
    daemon thread instead so it overlaps with the user issuing the command.
    Failures here are silently ignored: the lazy path in
    _invoke_read_tool_blocking remains the source of truth and will retry.
    """
    if os.getenv("AGENT_WALLET_PREWARM_READ_WORKER", "1").strip().lower() in {"0", "false", "no"}:
        return

    def _run() -> None:
        try:
            config = _base_config({}, tool_name="get_wallet_portfolio")
            _resident_read_worker_for_config(_user_id(), config).warm()
        except Exception:
            pass

    threading.Thread(
        target=_run,
        name="agent-wallet-read-worker-prewarm",
        daemon=True,
    ).start()


def _approval_summary_for_preview(tool_name: str, preview_payload: dict[str, Any]) -> dict[str, Any]:
    """Build the digest-bound confirmation summary the invoke subprocess will
    mint an approval token from (in-process, replacing the old standalone
    issue-approval subprocess round trip)."""
    summary = preview_payload.get("confirmation_summary")
    if not isinstance(summary, dict):
        raise RuntimeError(f"No confirmation_summary available for {tool_name}.")
    summary_for_token = dict(summary)
    summary_for_token["_preview_digest"] = _preview_digest(preview_payload)
    return summary_for_token


def _invoke_resident_read_tool(tool_name: str, arguments: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    worker = _resident_read_worker_for_config(_user_id(), config)
    try:
        return worker.invoke(tool_name, arguments)
    except ResidentReadWorkerTransportError:
        worker.close()
        raise


def _is_solana_swap_intent_execute(params: dict[str, Any]) -> bool:
    return str(params.get("mode") or "") == "intent_execute"


def _requires_approved_preview_payload(tool_name: str, params: dict[str, Any]) -> bool:
    if tool_name == "swap_solana_tokens" and _is_solana_swap_intent_execute(params):
        return False
    return tool_name in PREVIEW_BOUND_SWAP_TOOLS


def _should_let_backend_authorize_autonomous_execution(
    tool_name: str,
    params: dict[str, Any],
    config: dict[str, Any],
) -> bool:
    is_base_swap_tool = tool_name in AUTONOMOUS_BASE_SWAP_TOOLS
    is_defi_tool = tool_name in AUTONOMOUS_DEFI_TOOLS
    if not is_base_swap_tool and not is_defi_tool:
        return False
    if str(params.get("mode") or "") != "execute":
        return False
    if str(params.get("approval_token") or "").strip():
        return False
    network = str(params.get("network") or config.get("network") or selected_evm_network or "").strip().lower()
    if is_base_swap_tool:
        return network == "base"
    return network in {"base", "ethereum"}


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
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Prepare approval context for an execute call.

    Returns ``(used_cache, approval_args)``: ``used_cache`` is the consumed
    bridge-managed preview (if any); ``approval_args`` carries the
    digest-bound summary the invoke subprocess mints its own token from,
    so no separate issue-approval subprocess is spawned.
    """
    mode = str(effective_params.get("mode") or "")
    if mode not in {"execute", "intent_execute"}:
        return None, None
    if tool_name == "swap_solana_tokens" and mode == "execute":
        raise RuntimeError(
            "Legacy exact-preview execute is disabled for Solana Jupiter swaps in Codex. "
            "Use intent_preview, wait for explicit user confirmation, then call intent_execute."
        )
    cached = _latest_cached_preview(_user_id(), tool_name)
    if cached and isinstance(cached.get("preview"), dict):
        preview = cached["preview"]
        approval_args = {
            "summary": _approval_summary_for_preview(tool_name, preview),
            "mainnet_confirmed": preview.get("is_mainnet") is True,
        }
        if _requires_approved_preview_payload(tool_name, effective_params):
            effective_params["_approved_preview"] = preview
        return cached, approval_args
    approval_token = str(effective_params.get("approval_token") or "").strip()
    if approval_token and _requires_approved_preview_payload(tool_name, effective_params):
        cached_preview = _cached_preview_for_token(_user_id(), tool_name, approval_token)
        if cached_preview is not None and "_approved_preview" not in effective_params:
            effective_params["_approved_preview"] = cached_preview
    if effective_params.get("approval_token"):
        return None, None
    if _should_let_backend_authorize_autonomous_execution(tool_name, effective_params, config):
        return None, None
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
            "name": "get_wallet_overview",
            "description": (
                "Get a one-off wallet overview for a requested backend/network without changing the "
                "active Codex wallet session. Returns the same enriched balance payload used by "
                "get_wallet_balance."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "backend": {
                        "type": "string",
                        "description": "solana, evm, base, ethereum, btc, or bitcoin.",
                    },
                    "network": {
                        "type": "string",
                        "description": "Optional network override. Use base or ethereum for EVM.",
                    },
                    "address": {
                        "type": "string",
                        "description": "Optional wallet address override.",
                    },
                },
                "additionalProperties": False,
            },
            "read_only": True,
        },
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
        if spec.get("read_only") is True:
            # Route every adapter-declared read-only tool through the resident
            # read worker: reads then cost one warm request instead of a cold
            # interpreter boot + onboarding per call. The worker enforces the
            # same read_only contract on its side, and transport failures fall
            # back to the cold subprocess path.
            RESIDENT_READ_ONLY_TOOLS.add(spec["name"])
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
    # Resolve the target network into a local first; only commit to the session
    # globals after the validating wallet call succeeds, so a failed switch never
    # leaves a stale backend paired with a freshly mutated network selection.
    if backend == "wdk_evm_local":
        implied = (
            params.get("network")
            or _implied_evm_network_from_backend_alias(requested)
            or selected_evm_network
            or _default_evm_network()
            or "ethereum"
        )
        resolved_network = _normalize_selectable_evm_network(implied)
    elif backend == "wdk_btc_local":
        resolved_network = _normalize_btc_network(
            params.get("network") or selected_btc_network or _default_btc_network()
        )
    else:
        resolved_network = _normalize_solana_network(
            params.get("network") or selected_solana_network or _default_solana_network()
        )

    config = _host_default_config()
    config["backend"] = backend
    config["network"] = resolved_network
    payload = await asyncio.to_thread(
        _invoke_tool,
        "get_evm_network" if backend == "wdk_evm_local" else "get_wallet_capabilities",
        {} if backend != "wdk_evm_local" else {"network": config["network"]},
        config,
    )
    if payload.get("ok") is False:
        raise RuntimeError(str(payload.get("error") or "set_wallet_backend failed"))
    if backend == "wdk_evm_local":
        selected_evm_network = resolved_network
    elif backend == "wdk_btc_local":
        selected_btc_network = resolved_network
    else:
        selected_solana_network = resolved_network
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
    payload = await asyncio.to_thread(_invoke_tool, "get_evm_network", {"network": network}, config)
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


async def _handle_get_wallet_overview(params: dict[str, Any]) -> dict[str, Any]:
    config = _base_config(params, tool_name="get_wallet_balance")
    backend = _normalize_wallet_backend(config.get("backend"))

    effective_params: dict[str, Any] = {}
    if params.get("address") is not None:
        effective_params["address"] = params.get("address")

    payload = await asyncio.to_thread(
        _invoke_read_tool_blocking, "get_wallet_balance", effective_params, config
    )
    if payload.get("ok") is False:
        raise RuntimeError(str(payload.get("error") or "get_wallet_overview failed"))
    data = payload.get("data", {})
    if not isinstance(data, dict):
        return {
            "requested_backend": _backend_label(backend),
            "requested_network": config.get("network"),
            "data": data,
        }
    data.setdefault("requested_backend", _backend_label(backend))
    data.setdefault("requested_network", config.get("network"))
    return data


def _invoke_wallet_tool_blocking(
    tool_name: str,
    config: dict[str, Any],
    effective_params: dict[str, Any],
) -> dict[str, Any]:
    """Synchronous wallet invocation: approval attach + CLI subprocess + cache.

    Runs off the event loop via ``asyncio.to_thread`` so a slow or hung wallet
    call never freezes the MCP server (tools/list, read-only calls, and
    cancellation stay responsive).
    """
    used_cache, approval_args = _attach_approval_for_execute(tool_name, config, effective_params)
    try:
        payload = _invoke_tool(
            tool_name,
            effective_params,
            config,
            approval_summary=(approval_args or {}).get("summary"),
            approval_mainnet_confirmed=bool((approval_args or {}).get("mainnet_confirmed")),
        )
    except Exception as exc:
        raise _normalize_approval_context_error(exc) from exc
    _cache_preview_for_approval(_user_id(), tool_name, payload)
    # A bridge-managed preview that was just executed successfully is single-use:
    # drop it so a duplicate execute cannot silently re-run the operation.
    if used_cache is not None and payload.get("ok") is not False:
        _consume_cached_preview(_user_id(), tool_name)
    return payload


def _invoke_read_tool_blocking(
    tool_name: str,
    effective_params: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    if tool_name not in RESIDENT_READ_ONLY_TOOLS:
        return _invoke_tool(tool_name, effective_params, config)
    try:
        return _invoke_resident_read_tool(tool_name, effective_params, config)
    except ResidentReadWorkerTransportError:
        return _invoke_tool(tool_name, effective_params, config)


async def _handle_wallet_tool(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    config = _base_config(params, tool_name=tool_name)
    backend = _normalize_wallet_backend(config.get("backend"))
    if backend == "wdk_evm_local" and params.get("network") is None and selected_evm_network:
        params = {**params, "network": selected_evm_network}
        config["network"] = selected_evm_network

    effective_params = dict(params)
    if tool_name in RESIDENT_READ_ONLY_TOOLS:
        payload = await asyncio.to_thread(
            _invoke_read_tool_blocking, tool_name, effective_params, config
        )
    else:
        payload = await asyncio.to_thread(
            _invoke_wallet_tool_blocking, tool_name, config, effective_params
        )

    if payload.get("ok") is False:
        raise RuntimeError(str(payload.get("error") or f"{tool_name} failed"))
    return payload.get("data", {})


BASE_INSTRUCTIONS = (
    "Use the local AgentLayer wallet runtime through explicit wallet tools. Keep wallet "
    "secrets local. Preview writes first when supported, and execute only after explicit "
    "user confirmation."
)


def _update_notice_instructions(base: str) -> str:
    """Append a one-time update notice to ``base`` when a newer version exists.

    Fully fail-open: any error (package not importable, malformed cache, etc.)
    returns ``base`` unchanged so the server always starts. The network refresh
    runs in a background daemon thread and only affects the *next* start; the
    notice itself is decided synchronously from the cache.
    """
    try:
        package_root_text = str(_resolve_package_root())
        inserted = package_root_text not in sys.path
        if inserted:
            sys.path.insert(0, package_root_text)
        try:
            from agent_wallet import update_check

            update_check.maybe_refresh_in_background()
            notice = update_check.pending_notice(mark_shown=True)
        finally:
            if inserted:
                try:
                    sys.path.remove(package_root_text)
                except ValueError:
                    pass
        if notice:
            return f"{base}\n\n⚠️ UPDATE AVAILABLE: {notice}"
    except Exception:
        pass
    return base


def build_server():
    from fastmcp import FastMCP
    from fastmcp.tools import FunctionTool

    mcp = FastMCP(
        "Agent Wallet",
        instructions=_update_notice_instructions(BASE_INSTRUCTIONS),
    )

    async def _dispatch(tool_name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        if tool_name == "get_wallet_overview":
            return await _handle_get_wallet_overview(params)
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
    _install_termination_signal_handlers()
    _prewarm_resident_read_worker()
    build_server().run(show_banner=False)


if __name__ == "__main__":
    main()
