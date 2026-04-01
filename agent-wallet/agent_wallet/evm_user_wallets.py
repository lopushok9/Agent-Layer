"""Host-side helpers for binding local EVM wallets to OpenClaw users."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_wallet.config import resolve_openclaw_home, settings
from agent_wallet.providers.wdk_evm_local import WdkEvmLocalClient
from agent_wallet.user_wallets import normalize_user_id
from agent_wallet.wallet_layer.base import WalletBackendError


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


def resolve_user_evm_wallet_path(user_id: str, network: str | None = None) -> Path:
    effective_network = _normalize_evm_network(network or settings.solana_network)
    user_dir = resolve_openclaw_home() / "users" / normalize_user_id(user_id) / "wallets"
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
) -> dict[str, Any]:
    binding = get_user_evm_wallet_binding(user_id, network=network)
    client = WdkEvmLocalClient(_resolve_service_url(service_url))
    payload = client.post_sync(
        "/v1/evm/wallets/unlock",
        {
            "walletId": binding["wallet_id"],
            "password": password,
            "timeoutSeconds": 0,
        },
    )
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
) -> dict[str, Any]:
    binding = get_user_evm_wallet_binding(user_id, network=network)
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
