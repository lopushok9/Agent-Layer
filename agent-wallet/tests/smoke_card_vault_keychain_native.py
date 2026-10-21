"""macOS Security.framework checks in a disposable, explicitly selected keychain.

Never reads/writes the login keychain, changes the default keychain, or shows UI.
"""
from __future__ import annotations

import ctypes as C
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_wallet.card_vault_keychain import MacCardKeychain
from agent_wallet.wallet_layer.base import WalletBackendError


def main():
    if sys.platform != "darwin":
        print("smoke_card_vault_keychain_native: skipped (macOS only)")
        return
    with tempfile.TemporaryDirectory(prefix="agentlayer-vault-native-") as directory:
        store = MacCardKeychain(Path(directory))
        sec = store.sec
        sec.SecKeychainCreate.restype = C.c_int32
        sec.SecKeychainCreate.argtypes = [C.c_char_p, C.c_uint32, C.c_void_p, C.c_ubyte, C.c_void_p, C.POINTER(C.c_void_p)]
        sec.SecKeychainDelete.restype = C.c_int32
        sec.SecKeychainDelete.argtypes = [C.c_void_p]
        keychain = C.c_void_p()
        fixture_password = b"offline-native-test-keychain-password"
        with store._interaction(False):
            store._check(sec.SecKeychainCreate(str(Path(directory) / "fixture.keychain-db").encode(), len(fixture_password), fixture_password, False, None, C.byref(keychain)))
        @contextmanager
        def fixture_keychain():
            yield keychain
        store._keychain = fixture_keychain
        try:
            store.create("fixture", b"a" * 32)
            store.check("fixture")
            with store._interaction(False), store._item("fixture") as item:
                data, length = C.c_void_p(), C.c_uint32()
                code = sec.SecKeychainItemCopyContent(item, None, None, C.byref(length), C.byref(data))
                try:
                    assert code in {-25308, -25293}, f"Expected authentication denial, got {code}"
                finally:
                    if data:
                        sec.SecKeychainItemFreeContent(None, data)
                # Reject a permissive policy before attempting a secret read.
                weak, label = C.c_void_p(), store._string("Unsafe fixture ACL")
                try:
                    store._check(sec.SecAccessCreate(label, None, C.byref(weak)))
                    try:
                        store._validate_access(weak)
                    except WalletBackendError:
                        pass
                    else:
                        raise AssertionError("Permissive ACL was accepted")
                finally:
                    store._release(weak, label)
            try:
                store.create("fixture", b"b" * 32)
            except WalletBackendError:
                pass
            else:
                raise AssertionError("Existing Keychain key was replaced")
        finally:
            with store._interaction(False):
                store._check(sec.SecKeychainDelete(keychain))
            store._release(keychain)
    print("smoke_card_vault_keychain_native: ok (protected creation, ACL checks, silent-read denial, no overwrite)")


if __name__ == "__main__":
    main()
