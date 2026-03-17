"""Sealed key storage backed by one boot key and an encrypted file on disk."""

from __future__ import annotations

import json
from pathlib import Path

from agent_wallet.encrypted_storage import decrypt_secret_material, encrypt_secret_material
from agent_wallet.file_ops import atomic_write_text
from agent_wallet.wallet_layer.base import WalletBackendError

SEALED_KEYS_FILENAME = "sealed_keys.json"


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
    return path


def unseal_keys(boot_key: str) -> dict[str, str]:
    """Decrypt all secrets from the sealed file."""
    if not boot_key.strip():
        return {}

    path = resolve_sealed_keys_path()
    if not path.exists():
        return {}

    plaintext = decrypt_secret_material(path.read_text(encoding="utf-8"), master_key=boot_key)
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
    return secrets
