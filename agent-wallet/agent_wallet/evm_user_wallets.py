"""Host-side helpers for binding local EVM wallets to OpenClaw users."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from agent_wallet.config import (
    resolve_boot_key,
    resolve_evm_wallet_password,
    resolve_openclaw_home,
    settings,
)
from agent_wallet.providers.wdk_evm_local import WdkEvmLocalClient
from agent_wallet.user_wallets import normalize_user_id
from agent_wallet.wallet_layer.base import WalletBackendError

LOCAL_WDK_EVM_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _normalize_evm_network(value: str | None) -> str:
    network = str(value or "").strip().lower()
    aliases = {
        "mainnet": "ethereum",
        "eth": "ethereum",
        "eth-mainnet": "ethereum",
        "base-mainnet": "base",
        "base_sepolia": "base-sepolia",
    }
    network = aliases.get(network, network)
    if network not in {"ethereum", "sepolia", "base", "base-sepolia"}:
        return "ethereum"
    return network


def _resolve_service_url(service_url: str | None = None) -> str:
    effective = (service_url or settings.wdk_evm_service_url).strip()
    if not effective:
        raise WalletBackendError("wdk_evm_service_url is required for EVM wallet host operations.")
    return effective


def _paired_network(network: str) -> str | None:
    mapping = {
        "ethereum": "base",
        "base": "ethereum",
        "sepolia": "base-sepolia",
        "base-sepolia": "sepolia",
    }
    return mapping.get(_normalize_evm_network(network))


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
    if _service_is_healthy(service_url):
        return
    if not _is_local_service_url(service_url):
        raise WalletBackendError(
            f"wdk-evm-wallet is unreachable at {_health_url(service_url)} and auto-start only supports localhost URLs."
        )
    wallet_root = _resolve_local_wdk_evm_root()
    if wallet_root is None:
        raise WalletBackendError(
            "wdk-evm-wallet is not healthy and the local launcher could not be found."
        )
    parsed = urlparse(service_url)
    env = os.environ.copy()
    env["HOST"] = parsed.hostname or "127.0.0.1"
    env["PORT"] = str(parsed.port or 8081)
    env["WDK_EVM_NETWORK"] = _normalize_evm_network(network)
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
        if _service_is_healthy(service_url):
            return
        if process.poll() is not None:
            raise WalletBackendError("wdk-evm-wallet exited before becoming healthy.")
        time.sleep(0.5)
    raise WalletBackendError(
        f"Timed out waiting for wdk-evm-wallet health at {_health_url(service_url)}."
    )


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
