"""Backend-only card use capsules; never return their values through agent tools.

Unlike owner sealed boxes, these capsules are decryptable by the wallet runtime.
They enable authorized executors without owner Keychain authentication per use.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

from nacl.exceptions import CryptoError
from nacl.secret import SecretBox

from agent_wallet.card_vault import CardVault
from agent_wallet.config import resolve_wallet_master_key
from agent_wallet.file_ops import atomic_write_text
from agent_wallet.wallet_layer.base import WalletBackendError

MAX_RUNTIME_BYTES = 128 * 1024


class RuntimeVaultStorage:
    """Purpose-separated encrypted state within one existing user card vault."""

    def __init__(self, vault: CardVault, purpose: str):
        if purpose not in {"use", "operation", "browser"}:
            raise WalletBackendError("Unsupported runtime vault purpose.")
        self.vault, self.purpose = vault, purpose

    def path(self, reference: str):
        return self.vault._path(reference).with_suffix("." + self.purpose)

    def _key(self) -> bytes:
        master = resolve_wallet_master_key()
        if not master:
            raise WalletBackendError("The sealed wallet runtime key is required for private card use.")
        return hmac.new(master.encode(), b"agentlayer-vault-runtime-v1\0" + self.purpose.encode() + b"\0" + self.vault.scope.encode(), hashlib.sha256).digest()

    def save(self, reference: str, state: dict[str, Any]) -> None:
        self.vault._config()
        value = {"scope": self.vault.scope, "reference": reference, "purpose": self.purpose, "state": state}
        plaintext = json.dumps(value, allow_nan=False).encode()
        if len(plaintext) > MAX_RUNTIME_BYTES:
            raise WalletBackendError("Runtime vault state exceeds size limit.")
        box = bytes(SecretBox(self._key()).encrypt(plaintext))
        atomic_write_text(self.path(reference), json.dumps({"version": 1, "box": base64.b64encode(box).decode()}))
        self.vault._sync_directory()

    def load(self, reference: str) -> dict[str, Any]:
        self.vault._config()
        try:
            envelope = self.vault._read(self.path(reference))
            if envelope["version"] != 1:
                raise ValueError()
            plaintext = SecretBox(self._key()).decrypt(base64.b64decode(envelope["box"], validate=True))
            if len(plaintext) > MAX_RUNTIME_BYTES:
                raise ValueError()
            value = json.loads(plaintext)
            if (value["scope"] != self.vault.scope or value["reference"] != reference
                    or value["purpose"] != self.purpose or not isinstance(value["state"], dict)):
                raise ValueError()
            return value["state"]
        except (CryptoError, ValueError, KeyError, TypeError):
            raise WalletBackendError("Runtime vault state authentication failed.") from None


class CardRuntimeSecrets:
    def __init__(self, vault: CardVault):
        self.vault = vault
        self.storage = RuntimeVaultStorage(vault, "use")

    def capture(self, reference: str, record: dict[str, Any]) -> None:
        from agent_wallet.card_catalog import card_object, details_ready

        if not details_ready(record):
            return
        details = card_object(record.get("latest") or record.get("order") or {})["card_details"]
        fields = {
            "card.number": details["card_number"],
            "card.cvv": details["cvv"],
            "card.exp_month": f'{int(details["exp_month"]):02d}',
            "card.exp_year": str(int(details["exp_year"])),
        }
        address = details.get("billing_address")
        if isinstance(address, dict):
            for name in ("name", "line_1", "line_2", "city", "state", "zip", "country"):
                value = address.get(name)
                if isinstance(value, str) and len(value) <= 512:
                    fields["card.billing." + name] = value
        self.storage.save(reference, {"fields": fields})

    def available(self, reference: str) -> bool:
        self.vault._config()
        self.vault._read(self.vault._path(reference))
        path = self.storage.path(reference)
        return path.exists() or path.is_symlink()

    def load_for_executor(self, reference: str) -> dict[str, str]:
        # Call only inside an authorized executor, never as an agent-facing read.
        self.vault._read(self.vault._path(reference))
        state = self.storage.load(reference)
        fields = state.get("fields")
        if not isinstance(fields, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in fields.items()):
            raise WalletBackendError("Invalid runtime card capsule.")
        return fields
