"""Encrypted storage helpers for per-user wallet secret material."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

from agent_wallet.config import resolve_wallet_master_key
from agent_wallet.file_ops import atomic_write_text
from agent_wallet.wallet_layer.base import WalletBackendError

ENCRYPTED_WALLET_KIND = "openclaw-agent-wallet-secret"
ENCRYPTED_WALLET_VERSION = 1
USER_SCOPED_KEY_SALT = b"openclaw-agent-wallet-user-key-v1"

KDF_ARGON2ID = "argon2id"
KDF_HKDF_SHA256 = "hkdf-sha256"
_HKDF_INFO = b"openclaw-agent-wallet-envelope-hkdf-v1"


def _load_secretbox():
    try:
        from nacl import pwhash, secret, utils
    except ImportError as exc:
        raise WalletBackendError(
            "PyNaCl is required for encrypted wallet storage."
        ) from exc
    return pwhash, secret, utils


# Derived envelope keys are expensive (argon2id ~1s each), so cache them by
# (kdf, master_key, salt). In-memory only, never serialized; bounded so a
# pathological caller cannot grow it without limit.
_derived_key_cache: dict[tuple[str, str, bytes], bytes] = {}
_DERIVED_KEY_CACHE_MAX = 64


def clear_derived_key_cache() -> None:
    """Drop cached derived keys (wired into config.clear_secret_caches)."""
    _derived_key_cache.clear()


def _kdf_argon2id(master_key: str, salt: bytes) -> bytes:
    pwhash, secret, _ = _load_secretbox()
    return pwhash.argon2id.kdf(
        secret.SecretBox.KEY_SIZE,
        master_key.encode("utf-8"),
        salt,
        opslimit=pwhash.argon2id.OPSLIMIT_INTERACTIVE,
        memlimit=pwhash.argon2id.MEMLIMIT_INTERACTIVE,
    )


def _kdf_hkdf_sha256(master_key: str, salt: bytes) -> bytes:
    # RFC 5869 extract+expand, one 32-byte block. Only safe because every
    # caller passes machine-generated high-entropy key material (boot key /
    # sealed master key) — password-hardness is what argon2id was paying for,
    # and user passwords never reach this module.
    prk = hmac.new(salt, master_key.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(prk, _HKDF_INFO + b"\x01", hashlib.sha256).digest()


def _default_write_kdf() -> str:
    raw = os.getenv("AGENT_WALLET_ENVELOPE_KDF", "").strip().lower()
    return KDF_ARGON2ID if raw == KDF_ARGON2ID else KDF_HKDF_SHA256


def envelope_kdf(raw_text: str) -> str:
    """Return the kdf recorded in an encrypted envelope ('' when not one)."""
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict) or payload.get("kind") != ENCRYPTED_WALLET_KIND:
        return ""
    return str(payload.get("kdf") or KDF_ARGON2ID)


def _derive_key(master_key: str, salt: bytes, *, kdf: str = KDF_ARGON2ID) -> bytes:
    if not master_key.strip():
        raise WalletBackendError(
            "Encrypted wallet storage requires AGENT_WALLET_BOOT_KEY and a sealed master_key."
        )
    if kdf == KDF_HKDF_SHA256:
        # Cheap enough to skip the cache entirely.
        return _kdf_hkdf_sha256(master_key, bytes(salt))
    if kdf != KDF_ARGON2ID:
        raise WalletBackendError(f"Encrypted wallet file uses an unsupported kdf: {kdf}")
    cache_key = (kdf, master_key, bytes(salt))
    cached = _derived_key_cache.get(cache_key)
    if cached is not None:
        return cached
    key = _kdf_argon2id(master_key, salt)
    if len(_derived_key_cache) >= _DERIVED_KEY_CACHE_MAX:
        _derived_key_cache.clear()
    _derived_key_cache[cache_key] = key
    return key


def _derive_user_scoped_key(
    master_key: str,
    *,
    user_id: str,
    network: str,
) -> str:
    """Derive a deterministic per-user key from the global master key."""
    if not master_key.strip():
        raise WalletBackendError(
            "Encrypted wallet storage requires AGENT_WALLET_BOOT_KEY and a sealed master_key."
        )
    normalized_network = network.strip().lower() or "mainnet"
    prk = hmac.new(USER_SCOPED_KEY_SALT, master_key.encode("utf-8"), hashlib.sha256).digest()
    info = f"openclaw-wallet:{user_id}:{normalized_network}".encode("utf-8")
    okm = hmac.new(prk, info + b"\x01", hashlib.sha256).digest()
    return okm.hex()


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
    kdf: str | None = None,
) -> str:
    """Encrypt wallet secret material into a JSON envelope.

    ``kdf`` selects the key derivation for this envelope; None resolves the
    process default (hkdf-sha256 unless AGENT_WALLET_ENVELOPE_KDF=argon2id).
    """
    effective_kdf = kdf if kdf is not None else _default_write_kdf()
    if effective_kdf not in {KDF_ARGON2ID, KDF_HKDF_SHA256}:
        raise WalletBackendError(f"Unsupported envelope kdf: {effective_kdf}")
    _, secret, utils = _load_secretbox()
    effective_master_key = master_key if master_key is not None else resolve_wallet_master_key()
    salt = utils.random(16)
    key = _derive_key(effective_master_key, salt, kdf=effective_kdf)
    box = secret.SecretBox(key)
    encrypted = box.encrypt(secret_material.encode("utf-8"))
    payload: dict[str, Any] = {
        "kind": ENCRYPTED_WALLET_KIND,
        "version": ENCRYPTED_WALLET_VERSION,
        "cipher": "secretbox",
        "kdf": effective_kdf,
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
    kdf = str(payload.get("kdf") or KDF_ARGON2ID)
    key = _derive_key(effective_master_key, salt, kdf=kdf)
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
