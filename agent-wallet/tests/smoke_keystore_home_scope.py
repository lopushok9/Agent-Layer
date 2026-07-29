"""Non-default wallet homes must never share the production keystore service."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet import keystore  # noqa: E402


def main() -> None:
    original_home = os.environ.get("OPENCLAW_HOME")
    original_user_home = os.environ.get("HOME")
    original_service = os.environ.get("AGENT_WALLET_KEYSTORE_SERVICE")
    temp_homes: list[Path] = []
    try:
        os.environ.pop("AGENT_WALLET_KEYSTORE_SERVICE", None)
        os.environ["OPENCLAW_HOME"] = str(keystore._account_home() / ".openclaw")
        assert keystore._service() == keystore.KEYSTORE_SERVICE

        first_home = Path(tempfile.mkdtemp(prefix="agentlayer-keystore-home-a-"))
        second_home = Path(tempfile.mkdtemp(prefix="agentlayer-keystore-home-b-"))
        temp_homes.extend((first_home, second_home))
        os.environ["HOME"] = str(first_home)
        os.environ["OPENCLAW_HOME"] = str(first_home / ".openclaw")
        first_service = keystore._service()
        assert first_service.startswith(f"{keystore.KEYSTORE_SERVICE}.home-")
        assert first_service != keystore.KEYSTORE_SERVICE
        assert keystore._legacy_unscoped_service() is None
        assert keystore.MacKeychainStore().service == first_service
        assert keystore.LinuxSecretServiceStore().service == first_service

        legacy_state = first_home / ".openclaw" / "keystore" / "backend.json"
        legacy_state.parent.mkdir(parents=True)
        legacy_state.write_text(
            '{"version":1,"backend":"macos-keychain",'
            '"service":"ai.agentlayer.wallet"}\n',
            encoding="utf-8",
        )
        assert keystore._legacy_unscoped_service() == keystore.KEYSTORE_SERVICE

        os.environ["HOME"] = str(second_home)
        os.environ["OPENCLAW_HOME"] = str(second_home / ".openclaw")
        second_service = keystore._service()
        assert second_service != first_service
        assert second_service != keystore.KEYSTORE_SERVICE

        os.environ["AGENT_WALLET_KEYSTORE_SERVICE"] = "ai.agentlayer.wallet.explicit-test"
        assert keystore._service() == "ai.agentlayer.wallet.explicit-test"
        assert keystore._legacy_unscoped_service() is None
    finally:
        if original_home is None:
            os.environ.pop("OPENCLAW_HOME", None)
        else:
            os.environ["OPENCLAW_HOME"] = original_home
        if original_user_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = original_user_home
        if original_service is None:
            os.environ.pop("AGENT_WALLET_KEYSTORE_SERVICE", None)
        else:
            os.environ["AGENT_WALLET_KEYSTORE_SERVICE"] = original_service
        keystore.clear_keystore_cache()
        for temp_home in temp_homes:
            shutil.rmtree(temp_home, ignore_errors=True)

    print("smoke_keystore_home_scope: ok")


if __name__ == "__main__":
    main()
