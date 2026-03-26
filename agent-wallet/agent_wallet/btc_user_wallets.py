"""Host-side helpers for binding local BTC wallets to OpenClaw users."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_wallet.config import resolve_openclaw_home, settings
from agent_wallet.providers.wdk_btc_local import WdkBtcLocalClient
from agent_wallet.user_wallets import normalize_user_id
from agent_wallet.wallet_layer.base import WalletBackendError


def _normalize_btc_network(value: str | None) -> str:
    network = str(value or "").strip().lower()
    aliases = {"mainnet": "bitcoin"}
    network = aliases.get(network, network)
    if network not in {"bitcoin", "testnet", "regtest"}:
        return "bitcoin"
    return network


def _resolve_service_url(service_url: str | None = None) -> str:
    effective = (service_url or settings.wdk_btc_service_url).strip()
    if not effective:
        raise WalletBackendError("wdk_btc_service_url is required for BTC wallet host operations.")
    return effective


def resolve_user_btc_wallet_path(user_id: str, network: str | None = None) -> Path:
    effective_network = _normalize_btc_network(network or settings.solana_network)
    user_dir = resolve_openclaw_home() / "users" / normalize_user_id(user_id) / "wallets"
    return user_dir / f"btc-{effective_network}-agent.json"


def _write_wallet_binding(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def get_user_btc_wallet_binding(user_id: str, network: str | None = None) -> dict[str, Any]:
    path = resolve_user_btc_wallet_path(user_id, network=network)
    if not path.exists():
        raise WalletBackendError(f"BTC wallet binding does not exist yet: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not str(payload.get("wallet_id") or "").strip():
        raise WalletBackendError(f"BTC wallet binding is invalid: {path}")
    return payload


def create_user_btc_wallet(
    user_id: str,
    *,
    password: str,
    label: str | None = None,
    network: str | None = None,
    service_url: str | None = None,
    reveal_seed_phrase: bool = False,
    account_index: int | None = None,
) -> dict[str, Any]:
    effective_network = _normalize_btc_network(network or settings.solana_network)
    effective_account_index = settings.wdk_btc_account_index if account_index is None else int(account_index)
    client = WdkBtcLocalClient(_resolve_service_url(service_url))
    created = client.post_sync(
        "/v1/btc/wallets/create",
        {
            "label": (label or "").strip() or "Agent BTC Wallet",
            "password": password,
            "network": effective_network,
            "revealSeedPhrase": bool(reveal_seed_phrase),
        },
    )
    address = client.post_sync(
        "/v1/btc/address/resolve",
        {
            "walletId": created["walletId"],
            "accountIndex": effective_account_index,
            "network": effective_network,
        },
    )
    binding = {
        "user_id": user_id,
        "wallet_id": str(created["walletId"]),
        "label": str(created.get("label") or "Agent BTC Wallet"),
        "network": effective_network,
        "account_index": effective_account_index,
        "address": str(address.get("address") or ""),
        "storage_format": "local_vault",
        "service_kind": "wdk-btc-wallet",
        "created_at": created.get("createdAt"),
        "updated_at": created.get("updatedAt"),
    }
    _write_wallet_binding(resolve_user_btc_wallet_path(user_id, effective_network), binding)
    return {
        **binding,
        "unlocked": bool(created.get("unlocked", True)),
        "unlock_expires_at": created.get("unlockExpiresAt"),
        **({"seed_phrase": created["seedPhrase"]} if created.get("seedPhrase") else {}),
    }


def import_user_btc_wallet(
    user_id: str,
    *,
    password: str,
    seed_phrase: str,
    label: str | None = None,
    network: str | None = None,
    service_url: str | None = None,
    account_index: int | None = None,
) -> dict[str, Any]:
    effective_network = _normalize_btc_network(network or settings.solana_network)
    effective_account_index = settings.wdk_btc_account_index if account_index is None else int(account_index)
    client = WdkBtcLocalClient(_resolve_service_url(service_url))
    created = client.post_sync(
        "/v1/btc/wallets/import",
        {
            "label": (label or "").strip() or "Agent BTC Wallet",
            "password": password,
            "seedPhrase": seed_phrase,
            "network": effective_network,
        },
    )
    address = client.post_sync(
        "/v1/btc/address/resolve",
        {
            "walletId": created["walletId"],
            "accountIndex": effective_account_index,
            "network": effective_network,
        },
    )
    binding = {
        "user_id": user_id,
        "wallet_id": str(created["walletId"]),
        "label": str(created.get("label") or "Agent BTC Wallet"),
        "network": effective_network,
        "account_index": effective_account_index,
        "address": str(address.get("address") or ""),
        "storage_format": "local_vault",
        "service_kind": "wdk-btc-wallet",
        "created_at": created.get("createdAt"),
        "updated_at": created.get("updatedAt"),
    }
    _write_wallet_binding(resolve_user_btc_wallet_path(user_id, effective_network), binding)
    return {
        **binding,
        "unlocked": bool(created.get("unlocked", True)),
        "unlock_expires_at": created.get("unlockExpiresAt"),
    }


def unlock_user_btc_wallet(
    user_id: str,
    *,
    password: str,
    network: str | None = None,
    service_url: str | None = None,
) -> dict[str, Any]:
    binding = get_user_btc_wallet_binding(user_id, network=network)
    client = WdkBtcLocalClient(_resolve_service_url(service_url))
    payload = client.post_sync(
        "/v1/btc/wallets/unlock",
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


def lock_user_btc_wallet(
    user_id: str,
    *,
    network: str | None = None,
    service_url: str | None = None,
) -> dict[str, Any]:
    binding = get_user_btc_wallet_binding(user_id, network=network)
    client = WdkBtcLocalClient(_resolve_service_url(service_url))
    payload = client.post_sync(
        "/v1/btc/wallets/lock",
        {
            "walletId": binding["wallet_id"],
        },
    )
    return {
        **binding,
        "unlocked": bool(payload.get("unlocked", False)),
        "unlock_expires_at": None,
    }
