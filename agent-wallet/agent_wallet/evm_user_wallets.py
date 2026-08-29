"""Host-side helpers for binding local EVM wallets to OpenClaw users."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from agent_wallet.config import (
    normalize_evm_network,
    resolve_boot_key,
    resolve_evm_wallet_password,
    resolve_openclaw_home,
    resolve_wdk_evm_service_url,
    settings,
)
from agent_wallet.file_ops import atomic_write_text
from agent_wallet.providers.wdk_evm_local import WdkEvmLocalClient
from agent_wallet.user_wallets import normalize_user_id
from agent_wallet.wallet_layer.base import WalletBackendError

LOCAL_WDK_EVM_HOSTS = {"127.0.0.1", "localhost", "::1"}
_SERVICE_OWNER_FILENAME = "service-owner.json"
_INSTANCE_ID_FILENAME = "instance-id"


def _normalize_evm_network(value: str | None) -> str:
    return normalize_evm_network(value)


def _resolve_service_url(service_url: str | None = None) -> str:
    effective = (service_url or resolve_wdk_evm_service_url()).strip()
    if not effective:
        raise WalletBackendError("wdk_evm_service_url is required for EVM wallet host operations.")
    return effective


def _paired_network(network: str) -> str | None:
    mapping = {
        "ethereum": "base",
        "base": "ethereum",
    }
    return mapping.get(_normalize_evm_network(network))


def _health_url(service_url: str) -> str:
    return f"{service_url.rstrip('/')}/health"


def _service_health(service_url: str) -> dict[str, Any] | None:
    """Return the parsed /health payload, or None if the service is down.

    An empty dict means the service answered 200 but the body was unparseable —
    treated as "running, version unknown" so we never restart on a parse blip.
    """
    try:
        with urlopen(_health_url(service_url), timeout=1.5) as response:
            if int(getattr(response, "status", 0) or 0) != 200:
                return None
            raw = response.read()
    except (URLError, TimeoutError, OSError):
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _service_is_healthy(service_url: str) -> bool:
    return _service_health(service_url) is not None


def _read_on_disk_service_version(wallet_root: Path) -> str | None:
    """Version the launcher in wallet_root would report once (re)started."""
    try:
        pkg = json.loads((wallet_root / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = str(pkg.get("version") or "").strip()
    return version or None


def _expected_local_service_data_dir() -> Path:
    configured = os.getenv("WDK_EVM_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (resolve_openclaw_home() / "wdk-evm-wallet").resolve()


def _expected_local_service_instance_id() -> str:
    path = _expected_local_service_data_dir() / _INSTANCE_ID_FILENAME
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except OSError:
        existing = ""
    if existing:
        return existing
    generated = secrets.token_hex(16)
    atomic_write_text(path, generated + "\n", mode=0o600)
    return generated


def _service_owner_path() -> Path:
    return _expected_local_service_data_dir() / _SERVICE_OWNER_FILENAME


def _read_service_owner() -> dict[str, Any] | None:
    try:
        payload = json.loads(_service_owner_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_service_owner(health: dict[str, Any], service_url: str) -> int:
    expected_instance = _expected_local_service_instance_id()
    instance_id = str(health.get("instanceId") or "").strip()
    try:
        pid = int(health.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    if instance_id != expected_instance or pid <= 0:
        raise WalletBackendError("wdk-evm-wallet health did not confirm local process ownership.")
    payload = {
        "version": 1,
        "pid": pid,
        "instance_id": instance_id,
        "port": urlparse(service_url).port or 8081,
        "data_dir": str(_expected_local_service_data_dir()),
        "service_version": str(health.get("version") or "").strip() or None,
    }
    atomic_write_text(_service_owner_path(), json.dumps(payload, indent=2) + "\n", mode=0o600)
    return pid


def _same_path(left: str | Path | None, right: str | Path | None) -> bool:
    if left is None or right is None:
        return False
    try:
        left_path = Path(str(left)).expanduser().resolve()
        right_path = Path(str(right)).expanduser().resolve()
    except OSError:
        return False
    return left_path == right_path


def _should_restart_local_service(
    health: dict[str, Any] | None,
    *,
    wallet_root: Path | None,
) -> bool:
    if health is None:
        return False
    expected_version = _read_on_disk_service_version(wallet_root) if wallet_root is not None else None
    running_version = str(health.get("version") or "").strip()
    if expected_version and running_version and running_version != expected_version:
        return True

    reported_data_dir = str(health.get("dataDir") or "").strip()
    if reported_data_dir and not _same_path(reported_data_dir, _expected_local_service_data_dir()):
        return True

    reported_instance = str(health.get("instanceId") or "").strip()
    if reported_data_dir and reported_instance != _expected_local_service_instance_id():
        return True

    return False


def _listening_pids(port: int) -> list[int]:
    """PIDs LISTENing on a local TCP port (via lsof), excluding our own."""
    lsof = shutil.which("lsof")
    if not lsof:
        return []
    try:
        completed = subprocess.run(  # noqa: S603
            [lsof, "-t", "-i", f"tcp:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    pids: list[int] = []
    for token in completed.stdout.split():
        token = token.strip()
        if token.isdigit():
            pid = int(token)
            if pid != os.getpid():
                pids.append(pid)
    return pids


def _daemon_takeover_disabled() -> bool:
    return os.getenv("OPENCLAW_EVM_DISABLE_DAEMON_TAKEOVER", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _takeover_refusal(port: int, listeners: list[int], data_dir: str, reason: str) -> str:
    pids = ", ".join(str(pid) for pid in listeners) if listeners else "unknown"
    return (
        f"Refusing to stop the wdk-evm-wallet on port {port}: {reason}. "
        f"Listening PIDs: {pids}. Daemon dataDir: {data_dir or 'unknown'}. "
        f"To clear it manually: lsof -nP -iTCP:{port} -sTCP:LISTEN, then kill <pid>."
    )


def _process_cwd(pid: int) -> Path | None:
    """Return a process working directory via lsof, or None when unverified."""
    lsof = shutil.which("lsof")
    if not lsof:
        return None
    try:
        completed = subprocess.run(  # noqa: S603
            [lsof, "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    for line in completed.stdout.splitlines():
        if line.startswith("n") and line[1:].strip():
            try:
                return Path(line[1:].strip()).resolve()
            except OSError:
                return None
    return None


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _process_released_service(pid: int, port: int, service_url: str) -> bool:
    if not _process_exists(pid):
        return True
    # A daemon signalled by a process other than its parent can remain briefly
    # as a zombie. Once its listener and health endpoint are both gone, it no
    # longer blocks the updated runtime and is considered released.
    return pid not in _listening_pids(port) and _service_health(service_url) is None


def _owner_matches(
    owner: dict[str, Any] | None,
    current_health: dict[str, Any],
    *,
    pid: int,
    port: int,
) -> bool:
    if owner is None:
        return not _service_owner_path().exists()
    try:
        owner_pid = int(owner.get("pid") or 0)
        owner_port = int(owner.get("port") or 0)
    except (TypeError, ValueError):
        return False
    return (
        owner_pid == pid
        and owner_port == port
        and _same_path(owner.get("data_dir"), _expected_local_service_data_dir())
        and str(owner.get("instance_id") or "")
        == str(current_health.get("instanceId") or "")
    )


def _resolve_stoppable_pid(current_health: dict[str, Any], port: int) -> int:
    """Return a strictly verified same-home daemon PID, or 0 to fail closed."""
    reported_data_dir = str(current_health.get("dataDir") or "").strip()
    if not _same_path(reported_data_dir, _expected_local_service_data_dir()):
        return 0
    listeners = _listening_pids(port)
    if not listeners:
        return 0
    try:
        reported_pid = int(current_health.get("pid") or 0)
    except (TypeError, ValueError):
        reported_pid = 0
    if reported_pid > 0:
        if reported_pid not in listeners:
            return 0
        candidate = reported_pid
    elif len(listeners) == 1:
        # One-time compatibility for a pre-PID daemon. The listener and its
        # working directory still have to identify the bundled service.
        candidate = listeners[0]
    else:
        return 0
    cwd = _process_cwd(candidate)
    if cwd is None or cwd.name != "wdk-evm-wallet":
        return 0
    if not _owner_matches(_read_service_owner(), current_health, pid=candidate, port=port):
        return 0
    return candidate


def _stop_local_service(service_url: str, health: dict[str, Any] | None = None) -> None:
    """Gracefully stop a local wdk-evm-wallet daemon so a fresh one can start.

    SIGTERM the listener(s), wait for /health to drop, then SIGKILL as a fallback.
    """
    port = urlparse(service_url).port or 8081
    current_health = health if health is not None else _service_health(service_url)
    if not current_health or current_health.get("service") != "wdk-evm-wallet":
        raise WalletBackendError(
            f"Refusing to stop an unidentified service on port {port}."
        )
    listeners = _listening_pids(port)
    reported_data_dir = str(current_health.get("dataDir") or "").strip()

    if _daemon_takeover_disabled():
        raise WalletBackendError(
            _takeover_refusal(
                port,
                listeners,
                reported_data_dir,
                "takeover is disabled by OPENCLAW_EVM_DISABLE_DAEMON_TAKEOVER",
            )
        )

    if not _same_path(reported_data_dir, _expected_local_service_data_dir()):
        raise WalletBackendError(
            _takeover_refusal(
                port,
                listeners,
                reported_data_dir,
                "the daemon belongs to a different wallet home",
            )
        )

    owned_pid = _resolve_stoppable_pid(current_health, port)
    if owned_pid <= 0:
        raise WalletBackendError(
            _takeover_refusal(
                port,
                listeners,
                reported_data_dir,
                "the listening process could not be identified",
            )
        )

    try:
        os.kill(owned_pid, 0)
    except ProcessLookupError:
        try:
            _service_owner_path().unlink()
        except FileNotFoundError:
            pass
        return
    except PermissionError as exc:
        raise WalletBackendError(
            _takeover_refusal(
                port,
                listeners,
                reported_data_dir,
                f"pid {owned_pid} belongs to another user ({exc})",
            )
        ) from exc

    try:
        os.kill(owned_pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        raise WalletBackendError(
            f"Cannot stop stale wdk-evm-wallet (pid {owned_pid}): {exc}."
        ) from exc
    deadline = time.time() + 10.0
    while time.time() < deadline:
        if _process_released_service(owned_pid, port, service_url):
            try:
                _service_owner_path().unlink()
            except FileNotFoundError:
                pass
            return
        time.sleep(0.3)
    # Re-run the socket/cwd/owner checks immediately before a hard stop. A PID
    # that exited and was reused must never inherit permission from old health.
    refreshed_health = _service_health(service_url)
    if (
        not refreshed_health
        or refreshed_health.get("service") != "wdk-evm-wallet"
        or _resolve_stoppable_pid(refreshed_health, port) != owned_pid
    ):
        raise WalletBackendError(
            _takeover_refusal(
                port,
                _listening_pids(port),
                str((refreshed_health or {}).get("dataDir") or ""),
                "process identity changed before the hard stop",
            )
        )
    try:
        os.kill(owned_pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if _process_released_service(owned_pid, port, service_url):
            try:
                _service_owner_path().unlink()
            except FileNotFoundError:
                pass
            return
        time.sleep(0.3)
    raise WalletBackendError(f"Failed to stop stale wdk-evm-wallet on port {port}.")


def _is_local_service_url(service_url: str) -> bool:
    parsed = urlparse(service_url)
    return parsed.scheme in {"http", "https"} and parsed.hostname in LOCAL_WDK_EVM_HOSTS


def _resolve_local_wdk_evm_root() -> Path | None:
    configured = os.getenv("OPENCLAW_EVM_WDK_WALLET_ROOT", "").strip()
    candidates = [configured] if configured else []
    candidates.extend(
        [
            str(Path(__file__).resolve().parents[2] / "wdk-evm-wallet"),
            str(resolve_openclaw_home() / "agent-wallet-runtime" / "current" / "wdk-evm-wallet"),
        ]
    )
    for candidate in candidates:
        root = Path(candidate).expanduser()
        if (root / "run-local.sh").exists():
            return root
    return None


def _auto_start_local_service(service_url: str, network: str) -> None:
    wallet_root = _resolve_local_wdk_evm_root()
    health = _service_health(service_url)
    if health is not None:
        # Already running. The daemon loads code once at boot (no hot-reload), so a
        # long-running process keeps serving stale code after a release. It can also
        # keep serving the wrong local vault after a temp/smoke install left another
        # daemon on the shared localhost port. Restart only when the local daemon no
        # longer matches the expected launcher version or expected dataDir. Remote
        # (non-local) healthy services we don't manage are left untouched.
        if not _is_local_service_url(service_url):
            return
        if not _should_restart_local_service(health, wallet_root=wallet_root):
            if str(health.get("instanceId") or "").strip():
                _write_service_owner(health, service_url)
            return
        _stop_local_service(service_url, health)
    if not _is_local_service_url(service_url):
        raise WalletBackendError(
            f"wdk-evm-wallet is unreachable at {_health_url(service_url)} and auto-start only supports localhost URLs."
        )
    if wallet_root is None:
        raise WalletBackendError(
            "wdk-evm-wallet is not healthy and the local launcher could not be found."
        )
    parsed = urlparse(service_url)
    env = os.environ.copy()
    env["HOST"] = parsed.hostname or "127.0.0.1"
    env["PORT"] = str(parsed.port or 8081)
    env["WDK_EVM_NETWORK"] = _normalize_evm_network(network)
    env["WDK_EVM_INSTANCE_ID"] = _expected_local_service_instance_id()
    process = subprocess.Popen(  # noqa: S603
        ["sh", str(wallet_root / "run-local.sh")],
        cwd=str(wallet_root),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.time() + 30.0
    while time.time() < deadline:
        health = _service_health(service_url)
        if health is not None:
            _write_service_owner(health, service_url)
            return
        if process.poll() is not None:
            raise WalletBackendError("wdk-evm-wallet exited before becoming healthy.")
        time.sleep(0.5)
    raise WalletBackendError(
        f"Timed out waiting for wdk-evm-wallet health at {_health_url(service_url)}."
    )


def ensure_local_evm_service_ready(service_url: str, network: str) -> None:
    """Public entry point for callers outside the OpenClaw user-wallet flow.

    Thin wrapper around `_auto_start_local_service`, which was previously only
    reachable through `ensure_user_evm_wallet_ready`/`resolve_user_evm_wallet_binding`
    (the multi-user OpenClaw gateway/Hermes path). The single-agent factory
    (`wallet_layer.factory.create_wallet_backend`) has no user_id and doesn't
    need one — the underlying ownership/health checks are already keyed off
    `service_url`/`OPENCLAW_HOME`, not the caller's user. Exposing this lets
    both paths share one recovery implementation instead of drifting apart.

    Raises `WalletBackendError` for anything the auto-start/eviction logic
    can't resolve on its own (e.g. a foreign-home daemon occupying the port);
    callers should let that surface as a clear tool error rather than a raw
    connection failure.
    """
    _auto_start_local_service(service_url, network)


def _resolve_user_evm_wallet_dir(user_id: str) -> Path:
    return resolve_openclaw_home() / "users" / normalize_user_id(user_id) / "wallets"


def resolve_user_evm_wallet_path(user_id: str, network: str | None = None) -> Path:
    effective_network = _normalize_evm_network(network or settings.solana_network)
    user_dir = _resolve_user_evm_wallet_dir(user_id)
    return user_dir / f"evm-{effective_network}-agent.json"


def _write_wallet_binding(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def get_user_evm_wallet_binding(user_id: str, network: str | None = None) -> dict[str, Any]:
    path = resolve_user_evm_wallet_path(user_id, network=network)
    if not path.exists():
        raise WalletBackendError(f"EVM wallet binding does not exist yet: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not str(payload.get("wallet_id") or "").strip():
        raise WalletBackendError(f"EVM wallet binding is invalid: {path}")
    return payload


def resolve_user_evm_wallet_binding(
    user_id: str,
    *,
    network: str | None = None,
    service_url: str | None = None,
    wallet_id: str | None = None,
    account_index: int | None = None,
) -> dict[str, Any]:
    effective_network = _normalize_evm_network(network or settings.solana_network)
    explicit_wallet_id = str(wallet_id or "").strip()
    if explicit_wallet_id:
        return ensure_user_evm_wallet_binding(
            user_id,
            network=effective_network,
            service_url=service_url,
            wallet_id=explicit_wallet_id,
            account_index=account_index,
        )
    return get_user_evm_wallet_binding(user_id, network=effective_network)


def list_user_evm_wallet_bindings(user_id: str) -> list[dict[str, Any]]:
    user_dir = _resolve_user_evm_wallet_dir(user_id)
    if not user_dir.exists():
        return []

    bindings: list[dict[str, Any]] = []
    for path in sorted(user_dir.glob("evm-*-agent.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        wallet_id = str(payload.get("wallet_id") or "").strip()
        if not wallet_id:
            continue
        bindings.append(payload)
    return bindings


def _maybe_store_evm_wallet_password(password: str) -> bool:
    value = str(password or "").strip()
    if not value:
        return False
    boot_key = resolve_boot_key()
    if not boot_key:
        return False
    from agent_wallet.sealed_keys import resolve_sealed_keys_path, seal_keys, unseal_keys

    sealed_path = resolve_sealed_keys_path()
    existing = unseal_keys(boot_key) if sealed_path.exists() else {}
    if existing.get("wdk_evm_wallet_password") == value:
        return False
    seal_keys(boot_key, {**existing, "wdk_evm_wallet_password": value})
    return True


def _ensure_evm_wallet_password() -> str:
    existing = resolve_evm_wallet_password()
    if existing:
        return existing
    boot_key = resolve_boot_key()
    if not boot_key:
        return ""
    generated = secrets.token_urlsafe(24)
    _maybe_store_evm_wallet_password(generated)
    return generated


def _bind_network_pair(
    user_id: str,
    *,
    wallet_id: str,
    network: str,
    service_url: str,
    account_index: int,
    address: str | None,
) -> None:
    paired = _paired_network(network)
    if not paired:
        return
    bind_user_evm_wallet(
        user_id,
        wallet_id=wallet_id,
        network=paired,
        service_url=service_url,
        account_index=account_index,
        tolerate_locked=True,
        fallback_address=address,
    )


def bind_user_evm_wallet(
    user_id: str,
    *,
    wallet_id: str,
    network: str | None = None,
    service_url: str | None = None,
    account_index: int | None = None,
    tolerate_locked: bool = False,
    fallback_address: str | None = None,
) -> dict[str, Any]:
    effective_network = _normalize_evm_network(network or settings.solana_network)
    effective_account_index = settings.wdk_evm_account_index if account_index is None else int(account_index)
    effective_wallet_id = str(wallet_id or "").strip()
    if not effective_wallet_id:
        raise WalletBackendError("wallet_id is required for EVM wallet binding.")

    client = WdkEvmLocalClient(_resolve_service_url(service_url))
    wallet_meta = client.post_sync("/v1/evm/wallets/get", {"walletId": effective_wallet_id})
    resolved_address = str(fallback_address or "").strip()
    try:
        address = client.post_sync(
            "/v1/evm/address/resolve",
            {
                "walletId": effective_wallet_id,
                "accountIndex": effective_account_index,
                "network": effective_network,
            },
        )
    except WalletBackendError as exc:
        is_locked = exc.code == "wallet_locked" or "wallet is locked" in str(exc).strip().lower()
        if not (tolerate_locked and is_locked):
            raise
    else:
        resolved_address = str(address.get("address") or "").strip()
    binding = {
        "user_id": user_id,
        "wallet_id": effective_wallet_id,
        "label": str(wallet_meta.get("label") or "Agent EVM Wallet"),
        "network": effective_network,
        "account_index": effective_account_index,
        "address": resolved_address,
        "storage_format": "local_vault",
        "service_kind": "wdk-evm-wallet",
        "created_at": wallet_meta.get("createdAt"),
        "updated_at": wallet_meta.get("updatedAt"),
    }
    _write_wallet_binding(resolve_user_evm_wallet_path(user_id, effective_network), binding)
    return binding


def ensure_user_evm_wallet_binding(
    user_id: str,
    *,
    network: str | None = None,
    service_url: str | None = None,
    wallet_id: str | None = None,
    account_index: int | None = None,
) -> dict[str, Any]:
    effective_network = _normalize_evm_network(network or settings.solana_network)
    path = resolve_user_evm_wallet_path(user_id, network=effective_network)
    explicit_wallet_id = str(wallet_id or "").strip()
    if path.exists():
        existing = get_user_evm_wallet_binding(user_id, network=effective_network)
        if explicit_wallet_id and str(existing.get("wallet_id") or "").strip() != explicit_wallet_id:
            return bind_user_evm_wallet(
                user_id,
                wallet_id=explicit_wallet_id,
                network=effective_network,
                service_url=service_url,
                account_index=account_index,
                tolerate_locked=True,
                fallback_address=str(existing.get("address") or "").strip() or None,
            )
        return existing

    if explicit_wallet_id:
        return bind_user_evm_wallet(
            user_id,
            wallet_id=explicit_wallet_id,
            network=effective_network,
            service_url=service_url,
            account_index=account_index,
            tolerate_locked=True,
        )

    bindings = list_user_evm_wallet_bindings(user_id)
    if not bindings:
        raise WalletBackendError(f"EVM wallet binding does not exist yet: {path}")

    wallet_ids = {
        str(binding.get("wallet_id") or "").strip()
        for binding in bindings
        if str(binding.get("wallet_id") or "").strip()
    }
    if not wallet_ids:
        raise WalletBackendError(f"EVM wallet binding does not exist yet: {path}")
    if len(wallet_ids) > 1:
        raise WalletBackendError(
            "Multiple EVM wallet bindings exist for this user. Set wdk_evm_wallet_id explicitly to auto-bind a new network."
        )

    return bind_user_evm_wallet(
        user_id,
        wallet_id=next(iter(wallet_ids)),
        network=effective_network,
        service_url=service_url,
        account_index=account_index,
    )


def ensure_user_evm_wallet_ready(
    user_id: str,
    *,
    network: str | None = None,
    service_url: str | None = None,
    wallet_id: str | None = None,
    account_index: int | None = None,
    auto_start_service: bool = True,
) -> dict[str, Any]:
    effective_network = _normalize_evm_network(network or settings.solana_network)
    effective_service_url = _resolve_service_url(service_url)
    effective_account_index = settings.wdk_evm_account_index if account_index is None else int(account_index)
    if auto_start_service:
        _auto_start_local_service(effective_service_url, effective_network)
    elif not _service_is_healthy(effective_service_url):
        raise WalletBackendError(
            f"wdk-evm-wallet is not healthy at {_health_url(effective_service_url)}."
        )

    client = WdkEvmLocalClient(effective_service_url)
    explicit_wallet_id = str(wallet_id or "").strip()
    binding: dict[str, Any] | None = None
    if explicit_wallet_id:
        binding = ensure_user_evm_wallet_binding(
            user_id,
            network=effective_network,
            service_url=effective_service_url,
            wallet_id=explicit_wallet_id,
            account_index=effective_account_index,
        )
    else:
        try:
            binding = get_user_evm_wallet_binding(user_id, network=effective_network)
        except WalletBackendError:
            binding = None

    if binding is None:
        existing_bindings = list_user_evm_wallet_bindings(user_id)
        wallet_ids = {
            str(item.get("wallet_id") or "").strip()
            for item in existing_bindings
            if str(item.get("wallet_id") or "").strip()
        }
        if len(wallet_ids) > 1:
            raise WalletBackendError(
                "Multiple EVM wallet bindings exist for this user. Set wdk_evm_wallet_id explicitly to auto-bind a new network."
            )
        if wallet_ids:
            binding = bind_user_evm_wallet(
                user_id,
                wallet_id=next(iter(wallet_ids)),
                network=effective_network,
                service_url=effective_service_url,
                account_index=effective_account_index,
                tolerate_locked=True,
                fallback_address=str(existing_bindings[0].get("address") or "").strip() or None,
            )
        else:
            service_wallets = client.list_wallets_sync()
            service_wallet_ids = {
                str(item.get("walletId") or "").strip()
                for item in service_wallets
                if str(item.get("walletId") or "").strip()
            }
            if len(service_wallet_ids) > 1:
                raise WalletBackendError(
                    "Multiple local EVM vault wallets exist. Set wdk_evm_wallet_id explicitly before automatic switching."
                )
            if service_wallet_ids:
                binding = bind_user_evm_wallet(
                    user_id,
                    wallet_id=next(iter(service_wallet_ids)),
                    network=effective_network,
                    service_url=effective_service_url,
                    account_index=effective_account_index,
                    tolerate_locked=True,
                )
            else:
                password = _ensure_evm_wallet_password()
                if not password:
                    raise WalletBackendError(
                        "EVM wallet is not set up yet and no sealed local EVM wallet password is available for automatic creation."
                    )
                created = create_user_evm_wallet(
                    user_id,
                    password=password,
                    network=effective_network,
                    service_url=effective_service_url,
                    account_index=effective_account_index,
                )
                binding = get_user_evm_wallet_binding(user_id, network=effective_network)
                _bind_network_pair(
                    user_id,
                    wallet_id=str(created.get("wallet_id") or ""),
                    network=effective_network,
                    service_url=effective_service_url,
                    account_index=effective_account_index,
                    address=str(created.get("address") or "").strip() or None,
                )

    resolved_wallet_id = str(binding.get("wallet_id") or explicit_wallet_id).strip()
    if not resolved_wallet_id:
        raise WalletBackendError("EVM wallet binding is missing wallet_id.")

    def _resolve_address() -> str:
        payload = client.post_sync(
            "/v1/evm/address/resolve",
            {
                "walletId": resolved_wallet_id,
                "accountIndex": effective_account_index,
                "network": effective_network,
            },
        )
        address = str(payload.get("address") or "").strip()
        if not address:
            raise WalletBackendError("wdk-evm-wallet did not return an address.")
        return address

    try:
        resolved_address = _resolve_address()
    except WalletBackendError as exc:
        is_locked = exc.code == "wallet_locked" or "wallet is locked" in str(exc).strip().lower()
        if not is_locked:
            raise
        password = resolve_evm_wallet_password()
        if not password:
            raise WalletBackendError(
                "EVM wallet exists but cannot be unlocked automatically because no sealed local EVM wallet password is available."
            ) from exc
        unlock_user_evm_wallet(
            user_id,
            password=password,
            network=effective_network,
            service_url=effective_service_url,
            wallet_id=resolved_wallet_id,
            account_index=effective_account_index,
        )
        resolved_address = _resolve_address()

    binding = bind_user_evm_wallet(
        user_id,
        wallet_id=resolved_wallet_id,
        network=effective_network,
        service_url=effective_service_url,
        account_index=effective_account_index,
        fallback_address=resolved_address,
    )
    _bind_network_pair(
        user_id,
        wallet_id=resolved_wallet_id,
        network=effective_network,
        service_url=effective_service_url,
        account_index=effective_account_index,
        address=resolved_address,
    )
    return binding


def create_user_evm_wallet(
    user_id: str,
    *,
    password: str,
    label: str | None = None,
    network: str | None = None,
    service_url: str | None = None,
    reveal_seed_phrase: bool = False,
    account_index: int | None = None,
) -> dict[str, Any]:
    effective_network = _normalize_evm_network(network or settings.solana_network)
    effective_account_index = settings.wdk_evm_account_index if account_index is None else int(account_index)
    client = WdkEvmLocalClient(_resolve_service_url(service_url))
    created = client.post_sync(
        "/v1/evm/wallets/create",
        {
            "label": (label or "").strip() or "Agent EVM Wallet",
            "password": password,
            "network": effective_network,
            "revealSeedPhrase": bool(reveal_seed_phrase),
        },
    )
    address = client.post_sync(
        "/v1/evm/address/resolve",
        {
            "walletId": created["walletId"],
            "accountIndex": effective_account_index,
            "network": effective_network,
            "password": password,
        },
    )
    binding = {
        "user_id": user_id,
        "wallet_id": str(created["walletId"]),
        "label": str(created.get("label") or "Agent EVM Wallet"),
        "network": effective_network,
        "account_index": effective_account_index,
        "address": str(address.get("address") or ""),
        "storage_format": "local_vault",
        "service_kind": "wdk-evm-wallet",
        "created_at": created.get("createdAt"),
        "updated_at": created.get("updatedAt"),
    }
    _write_wallet_binding(resolve_user_evm_wallet_path(user_id, effective_network), binding)
    _maybe_store_evm_wallet_password(password)
    return {
        **binding,
        "unlocked": bool(created.get("unlocked", True)),
        "unlock_expires_at": created.get("unlockExpiresAt"),
        **({"seed_phrase": created["seedPhrase"]} if created.get("seedPhrase") else {}),
    }


def import_user_evm_wallet(
    user_id: str,
    *,
    password: str,
    seed_phrase: str,
    label: str | None = None,
    network: str | None = None,
    service_url: str | None = None,
    account_index: int | None = None,
) -> dict[str, Any]:
    effective_network = _normalize_evm_network(network or settings.solana_network)
    effective_account_index = settings.wdk_evm_account_index if account_index is None else int(account_index)
    client = WdkEvmLocalClient(_resolve_service_url(service_url))
    created = client.post_sync(
        "/v1/evm/wallets/import",
        {
            "label": (label or "").strip() or "Agent EVM Wallet",
            "password": password,
            "seedPhrase": seed_phrase,
            "network": effective_network,
        },
    )
    address = client.post_sync(
        "/v1/evm/address/resolve",
        {
            "walletId": created["walletId"],
            "accountIndex": effective_account_index,
            "network": effective_network,
            "password": password,
        },
    )
    binding = {
        "user_id": user_id,
        "wallet_id": str(created["walletId"]),
        "label": str(created.get("label") or "Agent EVM Wallet"),
        "network": effective_network,
        "account_index": effective_account_index,
        "address": str(address.get("address") or ""),
        "storage_format": "local_vault",
        "service_kind": "wdk-evm-wallet",
        "created_at": created.get("createdAt"),
        "updated_at": created.get("updatedAt"),
    }
    _write_wallet_binding(resolve_user_evm_wallet_path(user_id, effective_network), binding)
    _maybe_store_evm_wallet_password(password)
    return {
        **binding,
        "unlocked": bool(created.get("unlocked", True)),
        "unlock_expires_at": created.get("unlockExpiresAt"),
    }


def unlock_user_evm_wallet(
    user_id: str,
    *,
    password: str,
    network: str | None = None,
    service_url: str | None = None,
    wallet_id: str | None = None,
    account_index: int | None = None,
) -> dict[str, Any]:
    binding = resolve_user_evm_wallet_binding(
        user_id,
        network=network,
        service_url=service_url,
        wallet_id=wallet_id,
        account_index=account_index,
    )
    client = WdkEvmLocalClient(_resolve_service_url(service_url))
    payload = client.post_sync(
        "/v1/evm/wallets/unlock",
        {
            "walletId": binding["wallet_id"],
            "password": password,
            "timeoutSeconds": 0,
        },
    )
    _maybe_store_evm_wallet_password(password)
    return {
        **binding,
        "unlocked": bool(payload.get("unlocked", True)),
        "unlock_expires_at": payload.get("unlockExpiresAt"),
    }


def lock_user_evm_wallet(
    user_id: str,
    *,
    network: str | None = None,
    service_url: str | None = None,
    wallet_id: str | None = None,
    account_index: int | None = None,
) -> dict[str, Any]:
    binding = resolve_user_evm_wallet_binding(
        user_id,
        network=network,
        service_url=service_url,
        wallet_id=wallet_id,
        account_index=account_index,
    )
    client = WdkEvmLocalClient(_resolve_service_url(service_url))
    payload = client.post_sync(
        "/v1/evm/wallets/lock",
        {
            "walletId": binding["wallet_id"],
        },
    )
    return {
        **binding,
        "unlocked": bool(payload.get("unlocked", False)),
        "unlock_expires_at": None,
    }
