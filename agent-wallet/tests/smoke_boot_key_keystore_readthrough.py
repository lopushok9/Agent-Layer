"""resolve_boot_key prefers the keystore over the legacy file, env still wins."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.keystore import BOOT_KEY_ITEM, resolve_keystore  # noqa: E402


def main() -> None:
    temp_home = Path("/tmp/openclaw-boot-readthrough-smoke")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    os.environ["OPENCLAW_HOME"] = str(temp_home)
    os.environ["AGENT_WALLET_KEYSTORE_SERVICE"] = "ai.agentlayer.wallet.smoketest"
    for var in ("AGENT_WALLET_BOOT_KEY", "AGENT_WALLET_BOOT_KEY_FILE"):
        os.environ.pop(var, None)

    import agent_wallet.config as config
    config.settings.agent_wallet_boot_key = ""
    config.settings.agent_wallet_boot_key_file = ""

    # Use whatever backend is active on this host (real keychain on macOS) so the
    # round-trip matches what resolve_boot_key() actually reads.
    store = resolve_keystore()
    store.delete(BOOT_KEY_ITEM)
    try:
        # 1. Keystore value is used when no env/file present.
        store.set(BOOT_KEY_ITEM, "from-keystore")
        assert config.resolve_boot_key() == "from-keystore"

        # 2. Env override still wins over the keystore.
        os.environ["AGENT_WALLET_BOOT_KEY"] = "from-env"
        assert config.resolve_boot_key() == "from-env"
        os.environ.pop("AGENT_WALLET_BOOT_KEY")

        # 3. Legacy file is used only when keystore is empty.
        store.delete(BOOT_KEY_ITEM)
        boot_file = temp_home / "agent-wallet-runtime" / "boot-key"
        boot_file.parent.mkdir(parents=True, exist_ok=True)
        boot_file.write_text("from-file\n", encoding="utf-8")
        os.environ["AGENT_WALLET_BOOT_KEY_FILE"] = str(boot_file)
        assert config.resolve_boot_key() == "from-file"
    finally:
        store.delete(BOOT_KEY_ITEM)

    print("smoke_boot_key_keystore_readthrough OK:", store.backend_id)


if __name__ == "__main__":
    main()
