"""Agent-safe card metadata and short-lived issuer retrieval credentials.

Encrypted under a purpose- and user-scoped runtime key. Never stores PAN/CVV.
Pending credentials can retrieve card data at Laso: this is a backend capability,
not cryptographic isolation from a compromised wallet runtime while pending.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import math
import re
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from nacl.exceptions import CryptoError
from nacl.secret import SecretBox

from agent_wallet.card_vault import CardVault
from agent_wallet.config import resolve_wallet_master_key
from agent_wallet.file_ops import atomic_write_text
from agent_wallet.wallet_layer.base import WalletBackendError

CARD_TYPES = {"Non-Reloadable U.S.", "Non-Reloadable International"}
STATUSES = {"pending", "queued", "ready", "failed", "cancelled", "expired", "depleted"}
TERMINAL = {"failed", "cancelled", "expired", "depleted"}
REFRESH_STATES = {"pending", "complete", "retry_later", "credentials_expired", "owner_access_required", "unavailable"}
JOB_TTL = 7 * 24 * 3600
MIN_REFRESH_INTERVAL = 3
MAX_STATE_BYTES = 128 * 1024


def card_object(body: dict[str, Any]) -> dict[str, Any]:
    card = body.get("card")
    return card if isinstance(card, dict) else body


def credentials(record: dict[str, Any]) -> dict[str, str]:
    order = record.get("order") or {}
    auth = order.get("auth") if isinstance(order.get("auth"), dict) else order
    # Only actual credential fields, never unexpected provider data.
    return {key: auth[key] for key in ("id_token", "refresh_token")
            if isinstance(auth.get(key), str) and 0 < len(auth[key]) <= 16384}


def details_ready(record: dict[str, Any]) -> bool:
    card = card_object(record.get("latest") or record.get("order") or {})
    details = card.get("card_details")
    if not isinstance(details, dict):
        return False
    number, cvv = details.get("card_number"), details.get("cvv")
    try:
        return (
            isinstance(number, str) and re.fullmatch(r"[0-9]{12,19}", number) is not None
            and isinstance(cvv, str) and re.fullmatch(r"[0-9]{3,4}", cvv) is not None
            and 1 <= int(details["exp_month"]) <= 12
            and 2000 <= int(details["exp_year"]) <= 2100
        )
    except (KeyError, ValueError, TypeError):
        return False


def _timestamp(value: Any) -> str | None:
    if type(value) not in {int, float} or not 946684800 <= value <= 4133980800:
        return None
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def _balance(value: Any) -> str | None:
    if type(value) not in {str, int, float}:
        return None
    try:
        amount = Decimal(str(value))
        if amount.is_finite() and 0 <= amount <= 1000000 and amount.as_tuple().exponent >= -6:
            return format(amount, "f")
    except (InvalidOperation, ValueError):
        pass
    return None


class CardCatalog:
    def __init__(self, vault: CardVault):
        self.vault = vault

    def _key(self) -> bytes:
        master = resolve_wallet_master_key()
        if not master:
            raise WalletBackendError("The sealed wallet runtime key is required for pending card retrieval.")
        return hmac.new(master.encode(), b"agentlayer-card-catalog-v1\0" + self.vault.scope.encode(), hashlib.sha256).digest()

    def preflight(self) -> None:
        self._key()

    def _path(self, reference: str):
        return self.vault._path(reference).with_suffix(".agent")

    def save(self, reference: str, state: dict[str, Any]) -> None:
        self.vault._config()
        value = {"scope": self.vault.scope, "reference": reference, "state": state}
        plaintext = json.dumps(value).encode()
        if len(plaintext) > MAX_STATE_BYTES:
            raise WalletBackendError("Card catalog state exceeds size limit.")
        encrypted = bytes(SecretBox(self._key()).encrypt(plaintext))
        atomic_write_text(self._path(reference), json.dumps({"kind": "agentlayer-card-catalog", "version": 1, "box": base64.b64encode(encrypted).decode()}))
        self.vault._sync_directory()

    def load(self, reference: str) -> dict[str, Any]:
        self.vault._config()
        if not self.vault._path(reference).is_file():
            raise WalletBackendError("Saved card record was not found for this user.")
        try:
            envelope = self.vault._read(self._path(reference))
            if envelope["kind"] != "agentlayer-card-catalog" or envelope["version"] != 1:
                raise ValueError()
            raw = SecretBox(self._key()).decrypt(base64.b64decode(envelope["box"], validate=True))
            if len(raw) > MAX_STATE_BYTES:
                raise ValueError()
            value = json.loads(raw)
            if value["scope"] != self.vault.scope or value["reference"] != reference or not isinstance(value["state"], dict):
                raise ValueError()
            return value["state"]
        except (CryptoError, ValueError, KeyError, TypeError):
            raise WalletBackendError("Card catalog authentication failed.") from None

    def _entry(self, record: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
        card = card_object(record.get("latest") or record.get("order") or {})
        details = card.get("card_details")
        details = details if isinstance(details, dict) else {}
        number = details.get("card_number")
        entry = dict(previous or {})
        status = card.get("status")
        entry.update({
            "status": status if isinstance(status, str) and status in STATUSES else "unknown",
            "card_type": record.get("card_type"),
            "details_stored": details_ready(record),
        })
        if isinstance(number, str) and re.fullmatch(r"[0-9]{12,19}", number):
            entry["last4"] = number[-4:]
        if "available_balance" in details:
            entry["balance"] = _balance(details["available_balance"])
        return entry

    def track(self, reference: str, record: dict[str, Any]) -> dict[str, Any]:
        from agent_wallet.card_runtime_secrets import CardRuntimeSecrets

        CardRuntimeSecrets(self.vault).capture(reference, record)
        now = time.time()
        entry = self._entry(record)
        card = card_object(record.get("order") or {})
        auth = credentials(record)
        card_id = card.get("card_id")
        active = (
            not entry["details_stored"] and entry["status"] not in TERMINAL
            and isinstance(record.get("card_type"), str) and record["card_type"] in CARD_TYPES
            and isinstance(card_id, str) and 0 < len(card_id) <= 128
            and bool(auth.get("id_token"))
        )
        job = {"card_id": card_id, "card_type": record["card_type"], "auth": auth,
               "expires_at": now + JOB_TTL, "next_at": now, "attempts": 0} if active else None
        state = {"entry": entry, "created_at": now, "checked_at": now if record.get("latest") else None,
                 "refresh_state": "pending" if active else "complete" if entry["details_stored"] or entry["status"] in TERMINAL else "owner_access_required",
                 "job": job}
        self.save(reference, state)
        return state

    def update(self, reference: str, state: dict[str, Any], record: dict[str, Any]) -> None:
        from agent_wallet.card_runtime_secrets import CardRuntimeSecrets

        # Persist the executor capsule before retiring retrieval credentials.
        CardRuntimeSecrets(self.vault).capture(reference, record)
        # Do not report credential retirement unless the new catalog state is durable.
        candidate = copy.deepcopy(state)
        candidate["entry"] = self._entry(record, candidate.get("entry"))
        candidate["checked_at"] = time.time()
        if candidate["entry"]["details_stored"] or candidate["entry"]["status"] in TERMINAL:
            candidate["job"] = None
            candidate["refresh_state"] = "complete"
        else:
            candidate["refresh_state"] = "pending" if candidate.get("job") else "owner_access_required"
        self.save(reference, candidate)
        state.clear()
        state.update(candidate)

    def safe(self, reference: str, state: dict[str, Any]) -> dict[str, Any]:
        # Filter even authenticated local metadata; never return the state/job object.
        entry = state.get("entry")
        entry = entry if isinstance(entry, dict) else {}
        job = state.get("job")
        job = job if isinstance(job, dict) else {}
        status, card_type = entry.get("status"), entry.get("card_type")
        last4 = entry.get("last4")
        refresh_state = state.get("refresh_state")
        next_at = job.get("next_at")
        expires_at = job.get("expires_at")
        active = bool(job) and _timestamp(expires_at) is not None and expires_at > time.time()
        if job and not active:
            refresh_state = "credentials_expired"
        return {
            "vault_reference": reference, "provider": "laso", "currency": "USD",
            "status": status if isinstance(status, str) and status in STATUSES else "unknown",
            "card_type": card_type if isinstance(card_type, str) and card_type in CARD_TYPES else None,
            "last4": last4 if isinstance(last4, str) and re.fullmatch(r"[0-9]{4}", last4) else None,
            "available_balance": _balance(entry.get("balance")), "balance_is_cached": True,
            "details_stored": entry.get("details_stored") is True,
            "private_use_stored": self.vault._path(reference).with_suffix(".use").is_file(),
            "created_at": _timestamp(state.get("created_at")), "last_checked_at": _timestamp(state.get("checked_at")),
            "refresh_available": active,
            "refresh_state": refresh_state if isinstance(refresh_state, str) and refresh_state in REFRESH_STATES else "unavailable",
            "next_check_at": _timestamp(next_at) if active else None,
            "retry_after_seconds": min(300, max(0, math.ceil(next_at - time.time()))) if active and _timestamp(next_at) else None,
            "stored_encrypted": True,
        }

    def get(self, reference: str) -> dict[str, Any]:
        path = self._path(reference)
        if not self.vault._path(reference).is_file():
            raise WalletBackendError("Saved card record was not found for this user.")
        if not path.exists() and not path.is_symlink():
            return self.safe(reference, {"refresh_state": "owner_access_required"})
        return self.safe(reference, self.load(reference))

    def list(self, *, limit: int = 20, after: str | None = None) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise WalletBackendError("limit must be an integer between 1 and 100.")
        if after is not None:
            self.vault._path(after)
        if not self.vault.config_path.exists() and not self.vault.config_path.is_symlink():
            if any(self.vault.root.glob("*.card")):
                raise WalletBackendError("Card vault metadata is missing; restore it before accessing saved cards.")
            return {"cards": [], "next_cursor": None}
        references = [ref for ref in self.vault.references() if after is None or ref > after]
        cards = []
        for ref in references[:limit]:
            try:
                cards.append(self.get(ref))
            except WalletBackendError:
                cards.append(self.safe(ref, {"refresh_state": "unavailable"}))
        return {"cards": cards, "next_cursor": references[limit - 1] if len(references) > limit else None}
