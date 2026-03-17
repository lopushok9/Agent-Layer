"""User-scoped wallet provisioning and backend factory helpers."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from agent_wallet.bootstrap import (
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
    use_per_user_key_derivation,
)
from agent_wallet.encrypted_storage import (
    _derive_user_scoped_key,
    decrypt_secret_material,
    encrypt_secret_material,
    is_encrypted_wallet_payload,
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


def _resolve_effective_network(network: str | None = None) -> str:
    return (network or settings.solana_network).strip().lower() or "mainnet"


def _resolve_user_wallet_master_key(
    user_id: str,
    network: str,
    *,
    raw_master_key: str | None = None,
) -> str:
    effective_master_key = (
        raw_master_key.strip() if raw_master_key is not None else resolve_wallet_master_key()
    )
    if not effective_master_key:
        raise WalletBackendError(
            "Encrypted per-user wallets require AGENT_WALLET_BOOT_KEY and a sealed master_key in sealed_keys.json."
        )
    if use_per_user_key_derivation():
        return _derive_user_scoped_key(
            effective_master_key,
            user_id=user_id,
            network=network,
        )
    return effective_master_key


def _candidate_user_wallet_master_keys(
    user_id: str,
    network: str,
    *,
    raw_master_key: str | None = None,
) -> list[tuple[str, str]]:
    effective_master_key = (
        raw_master_key.strip() if raw_master_key is not None else resolve_wallet_master_key()
    )
    if not effective_master_key:
        return []

    candidates: list[tuple[str, str]] = []
    if use_per_user_key_derivation():
        candidates.append(
            (
                "per-user-derived",
                _derive_user_scoped_key(
                    effective_master_key,
                    user_id=user_id,
                    network=network,
                ),
            )
        )
    candidates.append(("global-master", effective_master_key))
    return candidates


def _load_user_wallet_secret_material(
    path: Path,
    *,
    user_id: str,
    network: str,
    raw_master_key: str | None = None,
) -> tuple[str, str, str | None]:
    raw_text = path.read_text(encoding="utf-8").strip()
    if not is_encrypted_wallet_payload(raw_text):
        return raw_text, "plaintext", None

    last_exc: WalletBackendError | None = None
    for key_scope, candidate in _candidate_user_wallet_master_keys(
        user_id,
        network,
        raw_master_key=raw_master_key,
    ):
        try:
            return (
                decrypt_secret_material(raw_text, master_key=candidate),
                "encrypted",
                key_scope,
            )
        except WalletBackendError as exc:
            last_exc = exc
    if last_exc is not None:
        raise last_exc
    raise WalletBackendError(
        "Encrypted per-user wallets require AGENT_WALLET_BOOT_KEY and a sealed master_key in sealed_keys.json."
    )


def ensure_user_solana_wallet(user_id: str, network: str | None = None) -> dict[str, str]:
    """Provision a per-user Solana wallet if it does not exist yet."""
    effective_network = _resolve_effective_network(network)
    path = resolve_user_wallet_path(user_id, network=effective_network)
    if path.exists():
        secret_material, storage_format, key_scope = _load_user_wallet_secret_material(
            path,
            user_id=user_id,
            network=effective_network,
        )
        signer = SolanaLocalKeypairSigner.from_secret_material(secret_material)
        ensure_wallet_pin(path, address=signer.address, network=effective_network)
        if storage_format == "plaintext":
            if not allow_plaintext_user_wallet_migration():
                raise WalletBackendError(
                    "Legacy plaintext user wallet files are no longer allowed. "
                    "Enable migration and provide a sealed master_key to upgrade them."
                )
            write_encrypted_wallet_file(
                path,
                secret_material,
                master_key=_resolve_user_wallet_master_key(user_id, effective_network),
                metadata=_user_wallet_metadata(user_id, signer.address, network=effective_network),
            )
            storage_format = "encrypted"
            key_scope = "per-user-derived"
        elif (
            storage_format == "encrypted"
            and key_scope == "global-master"
            and allow_plaintext_user_wallet_migration()
        ):
            write_encrypted_wallet_file(
                path,
                secret_material,
                master_key=_resolve_user_wallet_master_key(user_id, effective_network),
                metadata=_user_wallet_metadata(user_id, signer.address, network=effective_network),
            )
            key_scope = "per-user-derived"
        return {
            "user_id": user_id,
            "address": signer.address,
            "path": str(path),
            "storage_format": storage_format,
            "key_scope": key_scope or "plaintext",
        }

    refuse_recreation_if_pinned(path, network=effective_network)

    material = generate_solana_wallet_material()
    write_encrypted_wallet_file(
        path,
        material["secret_material"],
        master_key=_resolve_user_wallet_master_key(user_id, effective_network),
        metadata=_user_wallet_metadata(user_id, material["address"], network=effective_network),
    )
    ensure_wallet_pin(path, address=material["address"], network=effective_network)
    return {
        "user_id": user_id,
        "address": material["address"],
        "path": str(path),
        "storage_format": "encrypted",
        "key_scope": "per-user-derived",
    }


def get_user_wallet_storage_info(user_id: str, network: str | None = None) -> dict[str, str]:
    """Describe the current storage state for a per-user wallet."""
    path = resolve_user_wallet_path(user_id, network=network)
    if not path.exists():
        raise WalletBackendError(f"User wallet does not exist yet: {path}")
    effective_network = _resolve_effective_network(network)
    secret_material, storage_format, key_scope = _load_user_wallet_secret_material(
        path,
        user_id=user_id,
        network=effective_network,
    )
    signer = SolanaLocalKeypairSigner.from_secret_material(secret_material)
    pin = load_wallet_pin(path)
    return {
        "user_id": user_id,
        "address": signer.address,
        "path": str(path),
        "storage_format": storage_format,
        "key_scope": key_scope or "plaintext",
        "network": effective_network,
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

    effective_network = _resolve_effective_network(network)
    secret_material, storage_format, _ = _load_user_wallet_secret_material(
        path,
        user_id=user_id,
        network=effective_network,
        raw_master_key=current_master_key,
    )
    signer = SolanaLocalKeypairSigner.from_secret_material(secret_material)
    write_encrypted_wallet_file(
        path,
        secret_material,
        master_key=_resolve_user_wallet_master_key(
            user_id,
            effective_network,
            raw_master_key=new_master_key,
        ),
        metadata=_user_wallet_metadata(user_id, signer.address, network=network),
    )
    return {
        "user_id": user_id,
        "address": signer.address,
        "path": str(path),
        "previous_storage_format": storage_format,
        "storage_format": "encrypted",
        "network": effective_network,
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

    effective_network = _resolve_effective_network(network)
    secret_material, storage_format, _ = _load_user_wallet_secret_material(
        path,
        user_id=user_id,
        network=effective_network,
        raw_master_key=current_master_key,
    )
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
        "network": effective_network,
    }


def create_wallet_backend_for_user(
    user_id: str,
    *,
    sign_only: bool | None = None,
    network: str | None = None,
    rpc_url: str | None = None,
) -> SolanaWalletBackend:
    """Create a user-scoped Solana backend for OpenClaw runtime integration."""
    effective_network = _resolve_effective_network(network)
    wallet_info = ensure_user_solana_wallet(user_id, network=effective_network)
    secret_material, _, _ = _load_user_wallet_secret_material(
        Path(wallet_info["path"]),
        user_id=user_id,
        network=effective_network,
    )
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
