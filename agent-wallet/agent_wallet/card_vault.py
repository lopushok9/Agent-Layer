"""Local encrypted card records with owner authentication through macOS Keychain.

Legacy password-wrapped keys remain readable solely for explicit migration.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import stat
import uuid
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

from nacl import exceptions, pwhash, secret, utils
from nacl.public import PrivateKey, PublicKey, SealedBox

from agent_wallet.config import resolve_openclaw_home
from agent_wallet.file_ops import atomic_write_text
from agent_wallet.wallet_layer.base import WalletBackendError

KIND = "agentlayer-card-vault"
VERSION = 1
SYSTEM_VERSION = 2
MAX_BYTES = 2 * 1024 * 1024


def _file_locks():
    # Unsupported card custody must not prevent the rest of the wallet backend
    # (including Windows DPAPI startup) from importing. Never fall back to an
    # unlocked vault operation on platforms without these locks.
    try:
        import fcntl
    except ImportError:
        raise WalletBackendError("Card vault operations require macOS or Linux file locking.") from None
    return fcntl


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.b64decode(value, validate=True)


class CardVault:
    def __init__(self, user_id: str, *, home: Path | None = None):
        if not isinstance(user_id, str) or not user_id.strip():
            raise WalletBackendError("Card vault requires an explicit runtime user ID.")
        self.scope = hashlib.sha256(user_id.encode()).hexdigest()
        self.root = (home or resolve_openclaw_home()) / "card-vault" / self.scope
        self.config_path = self.root / "vault.json"

    def _read(self, path: Path) -> dict[str, Any]:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "r", encoding="utf-8") as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
                    raise ValueError("unsafe file")
                if info.st_size > MAX_BYTES:
                    raise ValueError("oversized file")
                value = json.load(handle)
            if not isinstance(value, dict):
                raise ValueError("invalid object")
            return value
        except (OSError, ValueError, TypeError):
            raise WalletBackendError("Card vault file is missing, unsafe, or invalid.") from None

    def _check_directory(self) -> None:
        try:
            info = self.root.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
                raise ValueError()
        except (OSError, ValueError):
            raise WalletBackendError("Vault directory must be owned by you with mode 0700.") from None

    def _sync_directory(self) -> None:
        fd = os.open(self.root, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @contextmanager
    def record_lock(self, reference: str):
        fcntl = _file_locks()
        path = self._path(reference).with_suffix(".lock")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    @asynccontextmanager
    async def async_record_lock(self, reference: str):
        fcntl = _file_locks()
        path = self._path(reference).with_suffix(".lock")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        deadline = time.monotonic() + 5
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise WalletBackendError("A card update is already in progress. Check its status again shortly.") from None
                    await asyncio.sleep(0.1)
            yield
        finally:
            os.close(fd)

    def _config(self) -> dict[str, Any]:
        self._check_directory()
        config = self._read(self.config_path)
        try:
            if config["kind"] != KIND or config["version"] not in {VERSION, SYSTEM_VERSION} or config["scope"] != self.scope:
                raise ValueError()
            PublicKey(_unb64(config["public_key"]))
            if config["version"] == VERSION:
                # Fixed cost for reading legacy password-protected vaults.
                if config["kdf"] != "argon2id-interactive":
                    raise ValueError()
            else:
                from agent_wallet.card_vault_keychain import PROTECTION
                if config["protection"] != PROTECTION or not re.fullmatch(r"[a-f0-9]{32}", config["key_id"]):
                    raise ValueError()
                if any(key in config for key in ("private_key", "salt", "kdf")):
                    raise ValueError()
        except (KeyError, ValueError, TypeError):
            raise WalletBackendError("Unsupported or invalid card vault configuration.") from None
        return config

    def check_ready(self) -> None:
        config = self._config()
        if config["version"] == SYSTEM_VERSION:
            self._system_store().check(self._key_account(config))
        # Test durable encrypted writes before an order can spend money.
        probe = self.deposit({"type": "preflight"})
        self._path(probe).unlink()

    @staticmethod
    def _wrap_key(private_key: PrivateKey, password: str) -> dict[str, str]:
        if len(password) < 12:
            raise WalletBackendError("Use a vault password of at least 12 characters.")
        salt = utils.random(pwhash.argon2id.SALTBYTES)
        key = pwhash.argon2id.kdf(
            secret.SecretBox.KEY_SIZE, password.encode(), salt,
            opslimit=pwhash.argon2id.OPSLIMIT_INTERACTIVE,
            memlimit=pwhash.argon2id.MEMLIMIT_INTERACTIVE,
        )
        return {"salt": _b64(salt), "private_key": _b64(bytes(secret.SecretBox(key).encrypt(bytes(private_key))))}

    def initialize(self, password: str) -> None:
        private_key = PrivateKey.generate()
        config = {
            "kind": KIND, "version": VERSION, "scope": self.scope,
            "public_key": _b64(bytes(private_key.public_key)),
            "kdf": "argon2id-interactive", **self._wrap_key(private_key, password),
        }
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        self._check_directory()
        # Publish a complete key file atomically, without replacing any existing key.
        temporary = self.root / f".init-{uuid.uuid4().hex}"
        try:
            atomic_write_text(temporary, json.dumps(config))
            os.link(temporary, self.config_path, follow_symlinks=False)
            self._sync_directory()
        finally:
            temporary.unlink(missing_ok=True)

    def _system_store(self):
        from agent_wallet.card_vault_keychain import MacCardKeychain
        return MacCardKeychain(self.root)

    def _key_account(self, config: dict[str, Any]) -> str:
        return f"{self.scope}:{config['key_id']}"

    def _system_config(self, private_key: PrivateKey) -> dict[str, Any]:
        from agent_wallet.card_vault_keychain import PROTECTION
        return {
            "kind": KIND, "version": SYSTEM_VERSION, "scope": self.scope,
            "public_key": _b64(bytes(private_key.public_key)),
            "protection": PROTECTION, "key_id": uuid.uuid4().hex,
        }

    @contextmanager
    def owner_lock(self):
        fcntl = _file_locks()
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        self._check_directory()
        fd = os.open(self.root / ".owner.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def ensure_system(self) -> dict[str, Any]:
        """Idempotent install/update provisioning; never reads a private key or shows UI."""
        with self.owner_lock():
            if self.config_path.exists() or self.config_path.is_symlink():
                config = self._config()
                if config["version"] == VERSION:
                    return {"status": "migration_required", "created": False}
                self._system_store().check(self._key_account(config))
                return {"status": "ready", "created": False}
            # Never create a different recipient for existing encrypted records.
            if any(self.root.glob("*.card")):
                raise WalletBackendError("Card vault key metadata is missing. Restore it from backup; existing cards were not replaced.")
            private_key = PrivateKey.generate()
            config = self._system_config(private_key)
            self._system_store().create(self._key_account(config), bytes(private_key))
            atomic_write_text(self.config_path, json.dumps(config))
            self._sync_directory()
            return {"status": "ready", "created": True}

    def migrate_to_system(self, password: str) -> PrivateKey:
        """Preserve the existing recipient; replace only its key-protection mechanism."""
        with self.owner_lock():
            if self._config()["version"] == SYSTEM_VERSION:
                return self.unlock()
            private_key = self.unlock(password)
            config = self._system_config(private_key)
            store = self._system_store()
            account = self._key_account(config)
            store.create(account, bytes(private_key))
            # Explicit owner authentication proves recovery before removing the old wrapper.
            if store.get(account) != bytes(private_key):
                raise WalletBackendError("System vault key verification failed. Existing password protection is preserved.")
            atomic_write_text(self.config_path, json.dumps(config))
            self._sync_directory()
            return private_key

    def unlock(self, password: str | None = None) -> PrivateKey:
        config = self._config()
        if config["version"] == SYSTEM_VERSION:
            private = PrivateKey(self._system_store().get(self._key_account(config)))
            if bytes(private.public_key) != _unb64(config["public_key"]):
                raise WalletBackendError("macOS Keychain key does not match this card vault.")
            return private
        if password is None:
            raise WalletBackendError("This legacy vault needs one-time migration: wallet vault migrate.")
        try:
            key = pwhash.argon2id.kdf(
                secret.SecretBox.KEY_SIZE, password.encode(), _unb64(config["salt"]),
                opslimit=pwhash.argon2id.OPSLIMIT_INTERACTIVE,
                memlimit=pwhash.argon2id.MEMLIMIT_INTERACTIVE,
            )
            private = PrivateKey(secret.SecretBox(key).decrypt(_unb64(config["private_key"])))
            if bytes(private.public_key) != _unb64(config["public_key"]):
                raise ValueError()
            return private
        except (exceptions.CryptoError, ValueError, KeyError, TypeError):
            raise WalletBackendError("Incorrect vault password or damaged vault key.") from None

    def _path(self, reference: str) -> Path:
        if not isinstance(reference, str) or not re.fullmatch(r"[a-f0-9]{32}", reference):
            raise WalletBackendError("Invalid vault reference.")
        return self.root / f"{reference}.card"

    def _seal(self, reference: str, payload: dict[str, Any], *, part: str) -> None:
        config = self._config()
        path = self._path(reference) if part == "record" else self._path(reference).with_suffix("." + part)
        plaintext = json.dumps({"scope": self.scope, "reference": reference, "part": part, "payload": payload})
        if len(plaintext.encode()) > MAX_BYTES // 2:
            raise WalletBackendError("Card vault record exceeds size limit.")
        ciphertext = SealedBox(PublicKey(_unb64(config["public_key"]))).encrypt(plaintext.encode())
        atomic_write_text(path, json.dumps({"version": VERSION, "sealed": _b64(ciphertext)}))
        self._sync_directory()

    def deposit(self, payload: dict[str, Any], *, reference: str | None = None) -> str:
        reference = reference or uuid.uuid4().hex
        self._seal(reference, payload, part="record")
        return reference

    def store_update(self, reference: str, *, latest: dict[str, Any] | None = None, auth: dict[str, str]) -> None:
        if not self._path(reference).is_file():
            raise WalletBackendError("Saved card record was not found for this user.")
        # Keep auth separate so token rotation cannot erase already saved details.
        self._seal(reference, {"auth": auth}, part="auth")
        if latest is not None:
            self._seal(reference, {"latest": latest}, part="update")

    def _decrypt_part(self, reference: str, private_key: PrivateKey, *, part: str) -> dict[str, Any]:
        path = self._path(reference) if part == "record" else self._path(reference).with_suffix("." + part)
        envelope = self._read(path)
        try:
            if envelope["version"] != VERSION:
                raise ValueError()
            value = json.loads(SealedBox(private_key).decrypt(_unb64(envelope["sealed"])))
            if value["scope"] != self.scope or value["reference"] != reference or value.get("part", "record") != part:
                raise ValueError()
            if not isinstance(value["payload"], dict):
                raise ValueError()
            return value["payload"]
        except (exceptions.CryptoError, ValueError, KeyError, TypeError):
            raise WalletBackendError("Card vault record failed authentication.") from None

    def read(self, reference: str, private_key: PrivateKey) -> dict[str, Any]:
        record = self._decrypt_part(reference, private_key, part="record")
        for part in ("update", "auth"):
            path = self._path(reference).with_suffix("." + part)
            if path.exists() or path.is_symlink():
                update = self._decrypt_part(reference, private_key, part=part)
                if isinstance(update.get("latest"), dict):
                    record["latest"] = update["latest"]
                if isinstance(update.get("auth"), dict):
                    record.setdefault("order", {})["auth"] = update["auth"]
        return record

    def remove_record(self, reference: str) -> None:
        # Call under record_lock. Revoke the local pending capability first.
        self._path(reference).with_suffix(".use").unlink(missing_ok=True)
        self._path(reference).with_suffix(".agent").unlink(missing_ok=True)
        self._path(reference).with_suffix(".update").unlink(missing_ok=True)
        self._path(reference).with_suffix(".auth").unlink(missing_ok=True)
        self._path(reference).unlink()
        self._sync_directory()

    def references(self) -> list[str]:
        self._config()
        return sorted(p.stem for p in self.root.glob("*.card") if re.fullmatch(r"[a-f0-9]{32}", p.stem))
