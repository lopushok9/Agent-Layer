"""User-scoped wallet provisioning and backend factory helpers."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from agent_wallet.bootstrap import (
    create_solana_wallet_file,
    ensure_wallet_pin,
    generate_solana_wallet_material,
    load_wallet_pin,
    refuse_recreation_if_pinned,
)
from agent_wallet.config import (
    allow_plaintext_user_wallet_migration,
    resolve_openclaw_home,
    resolve_solana_rpc_urls,
    resolve_wallet_master_key,
    settings,
    use_encrypted_user_wallets,
)
from agent_wallet.encrypted_storage import (
    encrypt_secret_material,
    load_wallet_secret_material,
    write_encrypted_wallet_file,
)
from agent_wallet.wallet_layer.base import WalletBackendError
from agent_wallet.wallet_layer.solana import SolanaLocalKeypairSigner, SolanaWalletBackend


def normalize_user_id(user_id: str) -> str:
    """Convert arbitrary user ids into stable filesystem-safe directory names."""
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", user_id.strip())
    cleaned = cleaned.strip("-._")
    if not cleaned:
        cleaned = "user"
    digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12]
    return f"{cleaned[:48]}-{digest}"


def resolve_user_wallet_path(user_id: str, network: str | None = None) -> Path:
    """Resolve the wallet file path for a given OpenClaw user."""
    effective_network = (network or settings.solana_network).strip().lower() or "mainnet"
    user_dir = resolve_openclaw_home() / "users" / normalize_user_id(user_id) / "wallets"
    return user_dir / f"solana-{effective_network}-agent.json"


def _user_wallet_metadata(user_id: str, address: str, network: str | None = None) -> dict[str, str]:
    effective_network = (network or settings.solana_network).strip().lower() or "mainnet"
    return {
        "address": address,
        "user_id": user_id,
        "network": effective_network,
    }


def ensure_user_solana_wallet(user_id: str, network: str | None = None) -> dict[str, str]:
    """Provision a per-user Solana wallet if it does not exist yet."""
    effective_network = (network or settings.solana_network).strip().lower() or "mainnet"
    path = resolve_user_wallet_path(user_id, network=effective_network)
    if path.exists():
        secret_material, storage_format = load_wallet_secret_material(path)
        signer = SolanaLocalKeypairSigner.from_secret_material(secret_material)
        ensure_wallet_pin(path, address=signer.address, network=effective_network)
        if storage_format == "plaintext" and use_encrypted_user_wallets():
            master_key = resolve_wallet_master_key()
            if master_key and allow_plaintext_user_wallet_migration():
                write_encrypted_wallet_file(
                    path,
                    secret_material,
                    master_key=master_key,
                    metadata=_user_wallet_metadata(user_id, signer.address, network=effective_network),
                )
                storage_format = "encrypted"
        return {
            "user_id": user_id,
            "address": signer.address,
            "path": str(path),
            "storage_format": storage_format,
        }

    refuse_recreation_if_pinned(path, network=effective_network)

    if use_encrypted_user_wallets():
        master_key = resolve_wallet_master_key()
        if not master_key:
            raise WalletBackendError(
                "AGENT_WALLET_MASTER_KEY is required to create encrypted per-user wallets."
            )
        material = generate_solana_wallet_material()
        write_encrypted_wallet_file(
            path,
            material["secret_material"],
            master_key=master_key,
            metadata=_user_wallet_metadata(user_id, material["address"], network=effective_network),
        )
        ensure_wallet_pin(path, address=material["address"], network=effective_network)
        return {
            "user_id": user_id,
            "address": material["address"],
            "path": str(path),
            "storage_format": "encrypted",
        }

    created = create_solana_wallet_file(path)
    ensure_wallet_pin(path, address=created["address"], network=effective_network)
    return {
        "user_id": user_id,
        "address": created["address"],
        "path": created["path"],
        "storage_format": "plaintext",
    }


def get_user_wallet_storage_info(user_id: str, network: str | None = None) -> dict[str, str]:
    """Describe the current storage state for a per-user wallet."""
    path = resolve_user_wallet_path(user_id, network=network)
    if not path.exists():
        raise WalletBackendError(f"User wallet does not exist yet: {path}")
    secret_material, storage_format = load_wallet_secret_material(path)
    signer = SolanaLocalKeypairSigner.from_secret_material(secret_material)
    pin = load_wallet_pin(path)
    return {
        "user_id": user_id,
        "address": signer.address,
        "path": str(path),
        "storage_format": storage_format,
        "network": (network or settings.solana_network).strip().lower() or "mainnet",
        "pinned_address": pin["address"] if pin else signer.address,
    }


def rotate_user_wallet_encryption(
    user_id: str,
    *,
    network: str | None = None,
    new_master_key: str,
    current_master_key: str | None = None,
) -> dict[str, str]:
    """Re-encrypt a per-user wallet with a new master key."""
    if not new_master_key.strip():
        raise WalletBackendError("new_master_key is required for wallet encryption rotation.")

    path = resolve_user_wallet_path(user_id, network=network)
    if not path.exists():
        raise WalletBackendError(f"User wallet does not exist yet: {path}")

    secret_material, storage_format = load_wallet_secret_material(path, master_key=current_master_key)
    signer = SolanaLocalKeypairSigner.from_secret_material(secret_material)
    write_encrypted_wallet_file(
        path,
        secret_material,
        master_key=new_master_key,
        metadata=_user_wallet_metadata(user_id, signer.address, network=network),
    )
    return {
        "user_id": user_id,
        "address": signer.address,
        "path": str(path),
        "previous_storage_format": storage_format,
        "storage_format": "encrypted",
        "network": (network or settings.solana_network).strip().lower() or "mainnet",
    }


def export_user_wallet_backup(
    user_id: str,
    *,
    network: str | None = None,
    export_master_key: str,
    current_master_key: str | None = None,
) -> dict[str, str]:
    """Export an encrypted backup payload for a per-user wallet."""
    if not export_master_key.strip():
        raise WalletBackendError("export_master_key is required for wallet backup export.")

    path = resolve_user_wallet_path(user_id, network=network)
    if not path.exists():
        raise WalletBackendError(f"User wallet does not exist yet: {path}")

    secret_material, storage_format = load_wallet_secret_material(path, master_key=current_master_key)
    signer = SolanaLocalKeypairSigner.from_secret_material(secret_material)
    exported_payload = encrypt_secret_material(
        secret_material,
        master_key=export_master_key,
        metadata={
            **_user_wallet_metadata(user_id, signer.address, network=network),
            "export_kind": "backup",
        },
    )
    return {
        "user_id": user_id,
        "address": signer.address,
        "path": str(path),
        "storage_format": storage_format,
        "backup_format": "encrypted",
        "backup_payload": exported_payload,
        "network": (network or settings.solana_network).strip().lower() or "mainnet",
    }


def create_wallet_backend_for_user(
    user_id: str,
    *,
    sign_only: bool | None = None,
    network: str | None = None,
    rpc_url: str | None = None,
) -> SolanaWalletBackend:
    """Create a user-scoped Solana backend for OpenClaw runtime integration."""
    effective_network = (network or settings.solana_network).strip().lower() or "mainnet"
    wallet_info = ensure_user_solana_wallet(user_id, network=effective_network)
    secret_material, _ = load_wallet_secret_material(Path(wallet_info["path"]))
    signer = SolanaLocalKeypairSigner.from_secret_material(secret_material)
    return SolanaWalletBackend(
        rpc_url=resolve_solana_rpc_urls(
            effective_network,
            rpc_url or settings.solana_rpc_url,
            settings.solana_rpc_urls,
        ),
        commitment=settings.solana_commitment,
        network=effective_network,
        signer=signer,
        address=wallet_info["address"],
        sign_only=settings.agent_wallet_sign_only if sign_only is None else sign_only,
    )
