"""Encrypted storage helpers for per-user wallet secret material."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from agent_wallet.config import resolve_wallet_master_key
from agent_wallet.file_ops import atomic_write_text
from agent_wallet.wallet_layer.base import WalletBackendError

ENCRYPTED_WALLET_KIND = "openclaw-agent-wallet-secret"
ENCRYPTED_WALLET_VERSION = 1


def _load_secretbox():
    try:
        from nacl import pwhash, secret, utils
    except ImportError as exc:
        raise WalletBackendError(
            "PyNaCl is required for encrypted wallet storage."
        ) from exc
    return pwhash, secret, utils


def _derive_key(master_key: str, salt: bytes) -> bytes:
    if not master_key.strip():
        raise WalletBackendError(
            "AGENT_WALLET_MASTER_KEY is required for encrypted user wallet storage."
        )
    pwhash, secret, _ = _load_secretbox()
    return pwhash.argon2id.kdf(
        secret.SecretBox.KEY_SIZE,
        master_key.encode("utf-8"),
        salt,
        opslimit=pwhash.argon2id.OPSLIMIT_INTERACTIVE,
        memlimit=pwhash.argon2id.MEMLIMIT_INTERACTIVE,
    )


def is_encrypted_wallet_payload(raw_text: str) -> bool:
    """Return True if the provided text contains an encrypted wallet envelope."""
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return False
    return (
        isinstance(payload, dict)
        and payload.get("kind") == ENCRYPTED_WALLET_KIND
        and int(payload.get("version") or 0) == ENCRYPTED_WALLET_VERSION
    )


def encrypt_secret_material(
    secret_material: str,
    *,
    master_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Encrypt wallet secret material into a JSON envelope."""
    _, secret, utils = _load_secretbox()
    effective_master_key = master_key if master_key is not None else resolve_wallet_master_key()
    salt = utils.random(16)
    key = _derive_key(effective_master_key, salt)
    box = secret.SecretBox(key)
    encrypted = box.encrypt(secret_material.encode("utf-8"))
    payload: dict[str, Any] = {
        "kind": ENCRYPTED_WALLET_KIND,
        "version": ENCRYPTED_WALLET_VERSION,
        "cipher": "secretbox",
        "kdf": "argon2id",
        "salt_b64": base64.b64encode(salt).decode("ascii"),
        "nonce_b64": base64.b64encode(encrypted.nonce).decode("ascii"),
        "ciphertext_b64": base64.b64encode(encrypted.ciphertext).decode("ascii"),
    }
    if metadata:
        payload["metadata"] = metadata
    return json.dumps(payload, indent=2)


def decrypt_secret_material(
    raw_text: str,
    *,
    master_key: str | None = None,
) -> str:
    """Decrypt wallet secret material from a JSON envelope."""
    _, secret, _ = _load_secretbox()
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise WalletBackendError("Encrypted wallet file could not be parsed.") from exc

    if not isinstance(payload, dict) or payload.get("kind") != ENCRYPTED_WALLET_KIND:
        raise WalletBackendError("Wallet file is not an encrypted wallet envelope.")

    try:
        salt = base64.b64decode(payload["salt_b64"])
        nonce = base64.b64decode(payload["nonce_b64"])
        ciphertext = base64.b64decode(payload["ciphertext_b64"])
    except (KeyError, ValueError) as exc:
        raise WalletBackendError("Encrypted wallet file is malformed.") from exc

    effective_master_key = master_key if master_key is not None else resolve_wallet_master_key()
    key = _derive_key(effective_master_key, salt)
    box = secret.SecretBox(key)
    try:
        plaintext = box.decrypt(ciphertext, nonce)
    except Exception as exc:
        raise WalletBackendError("Encrypted wallet file could not be decrypted.") from exc
    return plaintext.decode("utf-8")


def load_wallet_secret_material(
    path: Path,
    *,
    master_key: str | None = None,
) -> tuple[str, str]:
    """Load wallet secret material and return it with the detected format."""
    raw_text = path.read_text(encoding="utf-8").strip()
    if is_encrypted_wallet_payload(raw_text):
        return decrypt_secret_material(raw_text, master_key=master_key), "encrypted"
    return raw_text, "plaintext"


def write_encrypted_wallet_file(
    path: Path,
    secret_material: str,
    *,
    master_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Write encrypted wallet secret material atomically to disk."""
    payload = encrypt_secret_material(
        secret_material,
        master_key=master_key,
        metadata=metadata,
    )
    atomic_write_text(path, payload, mode=0o600)
