"""Owner-terminal import of existing cards; no card values in argv or output."""
from __future__ import annotations

import getpass
import re
import uuid
from datetime import datetime, timezone

from agent_wallet.card_catalog import CardCatalog, details_ready
from agent_wallet.card_runtime_secrets import RuntimeVaultStorage
from agent_wallet.card_vault import CardVault, SYSTEM_VERSION
from agent_wallet.wallet_layer.base import WalletBackendError


def import_interactive(vault: CardVault, card_type: str) -> dict:
    from agent_wallet.card_vault_cli import require_terminal

    require_terminal()
    vault.ensure_system()
    if vault._config()["version"] != SYSTEM_VERSION:
        raise WalletBackendError("Migrate the owner vault before importing: wallet vault migrate")
    catalog = CardCatalog(vault)
    catalog.preflight()
    RuntimeVaultStorage(vault, "use")._key()
    # getpass must never fall back to echoed stdin, even with a broken terminal.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            number = getpass.getpass("Card number (hidden): ")
            expiry = getpass.getpass("Expiry MM/YY or MM/YYYY (hidden): ")
            cvv = getpass.getpass("CVV (hidden): ")
        except getpass.GetPassWarning:
            raise WalletBackendError("Hidden terminal input is unavailable; import cancelled.") from None
    number = re.sub(r"[ -]", "", number)
    match = re.fullmatch(r"(0[1-9]|1[0-2])/([0-9]{2}|20[0-9]{2}|2100)", expiry.strip())
    if not match:
        raise WalletBackendError("Invalid expiry format; no card was imported.")
    month, year = int(match[1]), int(match[2])
    if year < 100:
        year += 2000
    details = {"card_number": number, "exp_month": str(month), "exp_year": str(year), "cvv": cvv.strip()}
    now = datetime.now(timezone.utc)
    record = {"type": "owner-imported-card", "source": "owner-terminal", "state": "imported",
              "created_at": now.isoformat(), "card_type": card_type,
              "order": {"status": "expired" if (year, month) < (now.year, now.month) else "ready", "card_details": details}}
    if not details_ready(record):
        raise WalletBackendError("Invalid card number, CVV or expiry; no card was imported.")
    digits = [int(c) for c in number]
    checksum = sum((d * 2 - 9 if d * 2 > 9 else d * 2) if i % 2 == len(digits) % 2 else d for i, d in enumerate(digits))
    if checksum % 10:
        raise WalletBackendError("Card number checksum is invalid; no card was imported.")
    reference = uuid.uuid4().hex
    try:
        with vault.owner_lock(), vault.record_lock(reference):
            vault.deposit(record, reference=reference)
            try:
                state = catalog.track(reference, record)
            except Exception:
                vault.remove_record(reference)
                raise
        return catalog.safe(reference, state)
    finally:
        details.clear()
        number = expiry = cvv = ""  # Best effort; Python cannot promise zeroization.
