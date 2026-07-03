"""User-facing boot-key export/import for paper backup and machine recovery.

The boot key is a retrievable string (baseline A), so recovery is simple: show
it for a paper backup, or write a recorded value back into the keystore on a new
machine. Full recovery kit = boot key + the already-encrypted sealed_keys.json +
wallet files. See BOOT_KEY_KEYCHAIN_ARCHITECTURE.md.
"""

from __future__ import annotations

from agent_wallet.config import read_boot_key_from_keystore, resolve_boot_key
from agent_wallet.keystore import BOOT_KEY_ITEM, resolve_keystore
from agent_wallet.wallet_layer.base import WalletBackendError

_EXPORT_WARNING = (
    "SENSITIVE: anyone with this boot key AND your ~/.openclaw encrypted files "
    "controls every wallet (Solana/EVM/BTC). Write it down and store it offline."
)


def export_boot_key() -> str:
    """Return the live boot key. Raises if none is resolvable."""
    key = resolve_boot_key()
    if not key:
        raise WalletBackendError(
            "No boot key is available to export. The wallet is not set up on this machine."
        )
    return key


def import_boot_key(value: str) -> dict:
    """Write a recorded boot key into the OS keystore and verify the read-back."""
    key = str(value or "").strip()
    if not key:
        raise WalletBackendError("A non-empty boot key is required for import.")
    store = resolve_keystore()
    store.set(BOOT_KEY_ITEM, key)
    if read_boot_key_from_keystore() != key:
        raise WalletBackendError(
            f"Boot key import could not be verified from the {store.backend_id} keystore."
        )
    return {"imported": True, "backend": store.backend_id}


def export_warning() -> str:
    return _EXPORT_WARNING
