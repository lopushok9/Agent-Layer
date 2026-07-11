"""User-facing boot-key export/import for paper backup and machine recovery.

The boot key is a retrievable string (baseline A), so recovery is simple: show
it for a paper backup, or write a recorded value back into the keystore on a new
machine. Full recovery kit = boot key + the already-encrypted sealed_keys.json +
wallet files. See BOOT_KEY_KEYCHAIN_ARCHITECTURE.md.
"""

from __future__ import annotations

from agent_wallet.config import clear_secret_caches, resolve_boot_key
from agent_wallet.keystore import BOOT_KEY_ITEM, record_keystore_backend, resolve_keystore
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
    """Validate and write a recorded boot key, then verify the read-back."""
    key = str(value or "").strip()
    if not key:
        raise WalletBackendError("A non-empty boot key is required for import.")
    from agent_wallet.sealed_keys import resolve_sealed_keys_path, unseal_keys

    if resolve_sealed_keys_path().exists():
        try:
            unseal_keys(key)
        except Exception as exc:
            raise WalletBackendError(
                "The supplied boot key does not unlock the existing sealed wallet state."
            ) from exc
    store = resolve_keystore()
    store.set(BOOT_KEY_ITEM, key)
    if store.get(BOOT_KEY_ITEM) != key:
        raise WalletBackendError(
            f"Boot key import could not be verified from the {store.backend_id} keystore."
        )
    state = record_keystore_backend(store)
    clear_secret_caches()
    return {"imported": True, "backend": store.backend_id, "backend_state": state}


def export_warning() -> str:
    return _EXPORT_WARNING
