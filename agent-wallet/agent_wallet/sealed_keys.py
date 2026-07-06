"""Sealed key storage backed by one boot key and an encrypted file on disk."""

from __future__ import annotations

import json
from pathlib import Path

from agent_wallet.encrypted_storage import decrypt_secret_material, encrypt_secret_material
from agent_wallet.file_ops import atomic_write_text
from agent_wallet.wallet_layer.base import WalletBackendError

SEALED_KEYS_FILENAME = "sealed_keys.json"

# Single-entry cache: (boot_key, path, mtime_ns, size) -> secrets. Unsealing
# runs a KDF, so repeated resolutions in one process must pay it only once.
# File identity in the key makes rotation (re-seal) self-invalidating.
_unseal_cache: dict[tuple[str, str, int, int], dict[str, str]] = {}


def clear_unseal_cache() -> None:
    """Drop cached unsealed secrets (wired into config.clear_secret_caches)."""
    _unseal_cache.clear()


def resolve_sealed_keys_path() -> Path:
    """Resolve the encrypted secret bundle path under the OpenClaw home directory."""
    from agent_wallet.config import resolve_openclaw_home

    return resolve_openclaw_home() / SEALED_KEYS_FILENAME


def seal_keys(boot_key: str, secrets: dict[str, str]) -> Path:
    """Encrypt all secrets into a single sealed file."""
    if not boot_key.strip():
        raise WalletBackendError("AGENT_WALLET_BOOT_KEY is required to seal secrets.")
    normalized: dict[str, str] = {}
    for key, value in secrets.items():
        if not isinstance(key, str) or not key.strip():
            raise WalletBackendError("Sealed secret names must be non-empty strings.")
        if not isinstance(value, str):
            raise WalletBackendError(f"Sealed secret '{key}' must be a string.")
        normalized[key.strip()] = value

    payload = json.dumps(normalized, indent=2)
    encrypted = encrypt_secret_material(payload, master_key=boot_key)
    path = resolve_sealed_keys_path()
    atomic_write_text(path, encrypted, mode=0o600)
    clear_unseal_cache()
    return path


def unseal_keys(boot_key: str) -> dict[str, str]:
    """Decrypt all secrets from the sealed file. Memoized by file identity."""
    if not boot_key.strip():
        return {}

    path = resolve_sealed_keys_path()
    if not path.exists():
        return {}

    try:
        stat = path.stat()
    except OSError:
        return {}
    cache_key = (boot_key, str(path), stat.st_mtime_ns, stat.st_size)
    cached = _unseal_cache.get(cache_key)
    if cached is not None:
        return dict(cached)

    raw_text = path.read_text(encoding="utf-8")
    plaintext = decrypt_secret_material(raw_text, master_key=boot_key)
    try:
        payload = json.loads(plaintext)
    except json.JSONDecodeError as exc:
        raise WalletBackendError("Sealed secret file is malformed.") from exc
    if not isinstance(payload, dict):
        raise WalletBackendError("Sealed secret file is malformed.")
    secrets: dict[str, str] = {}
    for key, value in payload.items():
        if isinstance(key, str) and isinstance(value, str):
            secrets[key] = value
    _maybe_migrate_envelope_kdf(boot_key, secrets, raw_text)
    _unseal_cache.clear()
    _unseal_cache[cache_key] = dict(secrets)
    return secrets


def _maybe_migrate_envelope_kdf(boot_key: str, secrets: dict[str, str], raw_text: str) -> None:
    """Lazily re-seal an argon2id file as hkdf-sha256 after a successful unseal.

    Best-effort: any failure leaves the (still readable) argon2id file in
    place. The boot key is machine-generated high entropy, so hkdf loses no
    security while dropping ~1s of KDF per cold process. Rollback caveat:
    pre-hkdf runtimes cannot read the rewritten file — kill switch is
    AGENT_WALLET_ENVELOPE_KDF_MIGRATION=0.
    """
    from agent_wallet.config import envelope_kdf_migration_enabled
    from agent_wallet.encrypted_storage import (
        KDF_ARGON2ID,
        KDF_HKDF_SHA256,
        _default_write_kdf,
        envelope_kdf,
    )

    try:
        if not envelope_kdf_migration_enabled():
            return
        if _default_write_kdf() == KDF_ARGON2ID:
            return  # forced-argon2id installs must not rewrite in place forever
        if envelope_kdf(raw_text) != KDF_ARGON2ID:
            return
        payload = json.dumps(secrets, indent=2)
        encrypted = encrypt_secret_material(payload, master_key=boot_key, kdf=KDF_HKDF_SHA256)
        atomic_write_text(resolve_sealed_keys_path(), encrypted, mode=0o600)
        clear_unseal_cache()
    except Exception:
        pass
