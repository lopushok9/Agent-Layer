"""macOS login Keychain storage requiring its password on every secret read.

Deliberately independent of the wallet boot-key store, whose ACL permits silent
reads. Uses Security.framework directly: no passwords or keys in shell argv,
subprocess stdout, environment variables, or plaintext fallback files.
"""
from __future__ import annotations

import ctypes as C
import hashlib
import platform
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

from agent_wallet.wallet_layer.base import WalletBackendError

PROTECTION = "macos-login-keychain-password"
REQUIRE_PASSWORD = 0x0001
_INTERACTION_LOCK = threading.RLock()


class MacCardKeychain:
    def __init__(self, root: Path):
        if sys.platform != "darwin":
            raise WalletBackendError("Automatic card vault currently requires macOS login Keychain. No insecure fallback is used.")
        version = tuple(int(part) for part in platform.mac_ver()[0].split(".") if part.isdigit())
        if version < (10, 13, 1):
            raise WalletBackendError("Card vault system authentication requires macOS 10.13.1 or newer.")
        self.service = "tech.agentlayer.card-vault." + hashlib.sha256(str(root.resolve()).encode()).hexdigest()
        self.cf = C.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        self.sec = C.CDLL("/System/Library/Frameworks/Security.framework/Security")
        ptr, status = C.c_void_p, C.c_int32
        signatures = {
            "CFRelease": (None, [ptr]),
            "CFStringCreateWithCString": (ptr, [ptr, C.c_char_p, C.c_uint32]),
            "CFArrayCreate": (ptr, [ptr, ptr, C.c_long, ptr]),
            "CFArrayGetCount": (C.c_long, [ptr]),
            "CFArrayGetValueAtIndex": (ptr, [ptr, C.c_long]),
            "CFDataCreate": (ptr, [ptr, ptr, C.c_long]),
            "CFDictionaryCreateMutable": (ptr, [ptr, C.c_long, ptr, ptr]),
            "CFDictionarySetValue": (None, [ptr, ptr, ptr]),
        }
        for name, (result, args) in signatures.items():
            fn = getattr(self.cf, name)
            fn.restype, fn.argtypes = result, args
        security = {
            "SecKeychainOpen": (status, [C.c_char_p, C.POINTER(ptr)]),
            "SecAccessCreate": (status, [ptr, ptr, C.POINTER(ptr)]),
            "SecAccessCopyACLList": (status, [ptr, C.POINTER(ptr)]),
            "SecAccessCopyMatchingACLList": (ptr, [ptr, ptr]),
            "SecACLCopyContents": (status, [ptr, C.POINTER(ptr), C.POINTER(ptr), C.POINTER(C.c_uint16)]),
            "SecACLSetContents": (status, [ptr, ptr, ptr, C.c_uint16]),
            "SecItemAdd": (status, [ptr, C.POINTER(ptr)]),
            "SecItemCopyMatching": (status, [ptr, C.POINTER(ptr)]),
            "SecKeychainItemCopyAccess": (status, [ptr, C.POINTER(ptr)]),
            "SecKeychainItemCopyContent": (status, [ptr, ptr, ptr, C.POINTER(C.c_uint32), C.POINTER(ptr)]),
            "SecKeychainItemFreeContent": (status, [ptr, ptr]),
            "SecKeychainGetUserInteractionAllowed": (status, [C.POINTER(C.c_ubyte)]),
            "SecKeychainSetUserInteractionAllowed": (status, [C.c_ubyte]),
        }
        for name, (result, args) in security.items():
            fn = getattr(self.sec, name)
            fn.restype, fn.argtypes = result, args

    def _constant(self, name: str) -> int:
        library = self.cf if name.startswith("kCF") else self.sec
        return C.c_void_p.in_dll(library, name).value

    def _callback(self, name: str) -> int:
        return C.addressof(C.c_char.in_dll(self.cf, name))

    def _string(self, text: str) -> int:
        return self.cf.CFStringCreateWithCString(None, text.encode(), 0x08000100)

    def _release(self, *references) -> None:
        for reference in references:
            if reference:
                self.cf.CFRelease(reference)

    @staticmethod
    def _check(code: int) -> None:
        if code:
            raise WalletBackendError(
                f"macOS Keychain denied or could not complete card vault access ({code}). "
                "Unlock your login Keychain and retry in a local terminal."
            )

    @contextmanager
    def _interaction(self, allowed: bool):
        # This Security.framework setting applies to the whole process.
        with _INTERACTION_LOCK:
            previous = C.c_ubyte()
            self._check(self.sec.SecKeychainGetUserInteractionAllowed(C.byref(previous)))
            self._check(self.sec.SecKeychainSetUserInteractionAllowed(allowed))
            try:
                yield
            finally:
                self.sec.SecKeychainSetUserInteractionAllowed(previous.value)

    @contextmanager
    def _keychain(self):
        # Pin the login keychain rather than following a user-selected default
        # keychain, which may have a different, application-specific password.
        keychain = C.c_void_p()
        base = Path.home() / "Library" / "Keychains"
        path = base / "login.keychain-db"
        if not path.exists():
            path = base / "login.keychain"
        try:
            self._check(self.sec.SecKeychainOpen(str(path).encode(), C.byref(keychain)))
            yield keychain
        finally:
            self._release(keychain)

    @contextmanager
    def _query(self, account: str):
        with self._keychain() as keychain:
            service, user = self._string(self.service), self._string(account)
            elements = (C.c_void_p * 1)(keychain.value)
            keychains = self.cf.CFArrayCreate(None, elements, 1, self._callback("kCFTypeArrayCallBacks"))
            query = self.cf.CFDictionaryCreateMutable(
                None, 0, self._callback("kCFTypeDictionaryKeyCallBacks"),
                self._callback("kCFTypeDictionaryValueCallBacks"),
            )
            try:
                self._set(query, "kSecClass", self._constant("kSecClassGenericPassword"))
                self._set(query, "kSecAttrService", service)
                self._set(query, "kSecAttrAccount", user)
                self._set(query, "kSecUseKeychain", keychain)
                self._set(query, "kSecMatchSearchList", keychains)
                self._set(query, "kSecReturnRef", self._constant("kCFBooleanTrue"))
                yield query
            finally:
                self._release(query, keychains, service, user)

    def _set(self, query, name: str, value) -> None:
        self.cf.CFDictionarySetValue(query, self._constant(name), value)

    def _acl_lists(self, access):
        # A permissive wildcard OR decrypt/ACL-change entry could bypass a stricter
        # entry. Check all entries granting any of those authorizations.
        for name in ("kSecACLAuthorizationAny", "kSecACLAuthorizationDecrypt", "kSecACLAuthorizationChangeACL"):
            entries = self.sec.SecAccessCopyMatchingACLList(access, self._constant(name))
            try:
                if entries:
                    for index in range(self.cf.CFArrayGetCount(entries)):
                        yield self.cf.CFArrayGetValueAtIndex(entries, index)
            finally:
                self._release(entries)

    def _validate_access(self, access) -> None:
        checked = 0
        for acl in self._acl_lists(access):
            applications, description = C.c_void_p(), C.c_void_p()
            flags = C.c_uint16()
            try:
                self._check(self.sec.SecACLCopyContents(acl, C.byref(applications), C.byref(description), C.byref(flags)))
                # NULL means trust everyone. An empty array means trust nobody.
                trusted = not applications or self.cf.CFArrayGetCount(applications) != 0
                # Since macOS 10.13.1 the OS ignores promptSelector and requires
                # the Keychain password for untrusted callers. Persisted flags
                # may be normalized by Security.framework; the empty trusted-app
                # list is the essential per-access boundary on supported systems.
                if trusted:
                    raise WalletBackendError("Card vault Keychain permissions allow silent access. Refusing to use this key.")
                checked += 1
            finally:
                self._release(applications, description)
        if not checked:
            raise WalletBackendError("Card vault Keychain authentication policy is missing.")

    def _validate_item(self, item) -> None:
        access = C.c_void_p()
        try:
            self._check(self.sec.SecKeychainItemCopyAccess(item, C.byref(access)))
            self._validate_access(access)
        finally:
            self._release(access)

    @contextmanager
    def _item(self, account: str):
        item = C.c_void_p()
        with self._query(account) as query:
            try:
                self._check(self.sec.SecItemCopyMatching(query, C.byref(item)))
                self._validate_item(item)
                yield item
            finally:
                self._release(item)

    def create(self, account: str, key: bytes) -> None:
        if len(key) != 32:
            raise WalletBackendError("Invalid card vault private key.")
        label = self._string("AgentLayer card vault — unlock saved cards")
        empty = self.cf.CFArrayCreate(None, None, 0, self._callback("kCFTypeArrayCallBacks"))
        access, entries, item = C.c_void_p(), C.c_void_p(), C.c_void_p()
        buffer = C.create_string_buffer(key)
        data = self.cf.CFDataCreate(None, buffer, len(key))
        try:
            with self._interaction(False):
                self._check(self.sec.SecAccessCreate(label, empty, C.byref(access)))
                self._check(self.sec.SecAccessCopyACLList(access, C.byref(entries)))
                for index in range(self.cf.CFArrayGetCount(entries)):
                    acl = self.cf.CFArrayGetValueAtIndex(entries, index)
                    self._check(self.sec.SecACLSetContents(acl, empty, label, REQUIRE_PASSWORD))
                self._validate_access(access)
                with self._query(account) as query:
                    self._set(query, "kSecAttrAccess", access)
                    self._set(query, "kSecAttrLabel", label)
                    self._set(query, "kSecValueData", data)
                    # SecItemAdd is create-only; existing keys are never replaced.
                    self._check(self.sec.SecItemAdd(query, C.byref(item)))
                    self._validate_item(item)
        finally:
            C.memset(buffer, 0, len(buffer))
            self._release(data, item, entries, access, empty, label)

    def check(self, account: str) -> None:
        """Check existence and ACL without reading secret data or displaying UI."""
        with self._interaction(False), self._item(account):
            pass

    def get(self, account: str) -> bytes:
        """The OS, not Python, collects the login Keychain password."""
        data, length = C.c_void_p(), C.c_uint32()
        with self._interaction(True), self._item(account) as item:
            try:
                self._check(self.sec.SecKeychainItemCopyContent(item, None, None, C.byref(length), C.byref(data)))
                # Recheck in case the user changed trust settings in the dialog.
                self._validate_item(item)
                if length.value != 32:
                    raise WalletBackendError("Invalid card vault key in macOS Keychain.")
                return C.string_at(data, length.value)
            finally:
                if data:
                    C.memset(data, 0, length.value)
                    self.sec.SecKeychainItemFreeContent(None, data)
