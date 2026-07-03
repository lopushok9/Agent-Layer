"""export returns the live key; import writes it into the keystore and verifies."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.keystore import BOOT_KEY_ITEM, resolve_keystore  # noqa: E402
from agent_wallet.wallet_layer.base import WalletBackendError  # noqa: E402


def main() -> None:
    temp_home = Path("/tmp/openclaw-boot-recovery-smoke")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    os.environ["OPENCLAW_HOME"] = str(temp_home)
    for var in ("AGENT_WALLET_BOOT_KEY", "AGENT_WALLET_BOOT_KEY_FILE"):
        os.environ.pop(var, None)

    import agent_wallet.config as config
    config.settings.agent_wallet_boot_key = ""
    config.settings.agent_wallet_boot_key_file = ""

    store = resolve_keystore()
    store.delete(BOOT_KEY_ITEM)

    from agent_wallet.boot_key_recovery import export_boot_key, import_boot_key

    try:
        # No key yet -> export raises.
        try:
            export_boot_key()
            raise AssertionError("export should have raised with no key present")
        except WalletBackendError:
            pass

        # import writes to the keystore and verifies.
        status = import_boot_key("RECOVERED-KEY")
        assert status["imported"] is True, status
        assert config.read_boot_key_from_keystore() == "RECOVERED-KEY"

        # export now returns it.
        assert export_boot_key() == "RECOVERED-KEY"
    finally:
        store.delete(BOOT_KEY_ITEM)

    print("smoke_boot_key_recovery OK:", store.backend_id)


if __name__ == "__main__":
    main()
