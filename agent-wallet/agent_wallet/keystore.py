"""Cross-platform, dependency-free secret storage for the wallet boot key.

Backends shell out to tools already present on each desktop OS:
  - macOS:   /usr/bin/security (generic password in the login keychain)
  - Windows: powershell DPAPI (ConvertFrom/ConvertTo-SecureString), per-user+machine
  - Linux:   secret-tool (libsecret) iff a Secret Service is reachable
  - fallback: a 0600 plaintext file (current behavior) — never chosen over a
              working keystore.

The store holds ONE install-level secret (the boot key). See
BOOT_KEY_KEYCHAIN_ARCHITECTURE.md.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Protocol, runtime_checkable

from agent_wallet.config import resolve_openclaw_home
from agent_wallet.file_ops import atomic_write_text, chmod_if_exists

KEYSTORE_SERVICE = "ai.agentlayer.wallet"
BOOT_KEY_ITEM = "boot_key"
_PROBE_ITEM = "__probe__"
_KEYSTORE_BACKEND_ENV = "AGENT_WALLET_KEYSTORE_BACKEND"

_SECURITY_BIN = "/usr/bin/security"
_SUBPROCESS_TIMEOUT = 10.0


def _service() -> str:
    """Keychain/Secret-Service service name. Overridable so tests never touch the
    real shared slot (the OS keychain is global, not scoped to OPENCLAW_HOME)."""
    return os.getenv("AGENT_WALLET_KEYSTORE_SERVICE", "").strip() or KEYSTORE_SERVICE


def _backend_preference() -> str:
    """Selected keystore backend.

    auto (default) prefers the native OS keystore (macOS Keychain / Windows DPAPI /
    Linux Secret Service) and falls back to a 0600 plaintext file. macOS Keychain
    is prompt-free because set() writes with `-A` (open ACL, no partition-list).
    Override with AGENT_WALLET_KEYSTORE_BACKEND=plaintext|macos-keychain|native|...
    """
    return os.getenv(_KEYSTORE_BACKEND_ENV, "auto").strip().lower()


class KeyStoreError(Exception):
    """Raised when a keystore backend operation fails unexpectedly."""


@runtime_checkable
class KeyStore(Protocol):
    backend_id: str

    def available(self) -> bool: ...
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


def _timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _run(
    argv: list[str],
    *,
    input_text: str | None = None,
    timeout: float = _SUBPROCESS_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, object] = {
        "capture_output": True,
        "text": True,
        "timeout": timeout,
        "check": False,
    }
    if input_text is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = input_text
    try:
        return subprocess.run(argv, **kwargs)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            argv,
            124,
            _timeout_output(exc.stdout),
            _timeout_output(exc.stderr) or f"timed out after {timeout:g}s",
        )


class MacKeychainStore:
    backend_id = "macos-keychain"

    def available(self) -> bool:
        return platform.system() == "Darwin" and Path(_SECURITY_BIN).exists()

    def get(self, name: str) -> str | None:
        proc = _run([_SECURITY_BIN, "find-generic-password", "-s", _service(), "-a", name, "-w"])
        if proc.returncode != 0:
            return None  # item not found (44) or other non-fatal lookup miss
        value = proc.stdout.rstrip("\n")
        return value or None

    def set(self, name: str, value: str) -> None:
        # Recreate the item fresh with an open ACL. This is the ONLY reliably
        # prompt-free way to write a login-keychain item non-interactively:
        #   -A          -> accessible to any application without a prompt, and it
        #                  bypasses the Sierra+ partition-list mechanism entirely.
        #   delete+add  -> never -U-update an existing item; updating one created
        #                  with a different ACL (or setting its partition list)
        #                  pops a GUI keychain-password dialog in the background.
        # Trade-off: any process running as this user can read the key without a
        # prompt — the same runtime exposure as a 0600 file. At-rest protection
        # (backups, synced home dirs, a stolen disk) is fully preserved.
        _run([_SECURITY_BIN, "delete-generic-password", "-s", _service(), "-a", name])
        proc = _run([
            _SECURITY_BIN, "add-generic-password",
            "-s", _service(), "-a", name,
            "-w", value, "-A",
        ])
        if proc.returncode != 0:
            raise KeyStoreError(f"security add-generic-password failed: {proc.stderr.strip()}")

    def delete(self, name: str) -> None:
        _run([_SECURITY_BIN, "delete-generic-password", "-s", _service(), "-a", name])


class WindowsDpapiStore:
    backend_id = "windows-dpapi"

    def _blob_path(self, name: str) -> Path:
        return resolve_openclaw_home() / "keystore" / f"{name}.dpapi"

    def available(self) -> bool:
        return platform.system() == "Windows" and shutil.which("powershell") is not None

    def get(self, name: str) -> str | None:
        path = self._blob_path(name)
        if not path.exists():
            return None
        blob = path.read_text(encoding="utf-8").strip()
        if not blob:
            return None
        script = (
            "$ErrorActionPreference='Stop';"
            "$b=[Console]::In.ReadToEnd().Trim();"
            "$ss=ConvertTo-SecureString $b;"
            "$p=[Runtime.InteropServices.Marshal]::PtrToStringUni("
            "[Runtime.InteropServices.Marshal]::SecureStringToBSTR($ss));"
            "[Console]::Out.Write($p)"
        )
        proc = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], input_text=blob)
        if proc.returncode != 0:
            return None
        return proc.stdout or None

    def set(self, name: str, value: str) -> None:
        script = (
            "$ErrorActionPreference='Stop';"
            "$v=[Console]::In.ReadToEnd();"
            "$ss=ConvertTo-SecureString $v -AsPlainText -Force;"
            "[Console]::Out.Write((ConvertFrom-SecureString $ss))"
        )
        proc = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], input_text=value)
        if proc.returncode != 0 or not proc.stdout.strip():
            raise KeyStoreError(f"DPAPI ConvertFrom-SecureString failed: {proc.stderr.strip()}")
        atomic_write_text(self._blob_path(name), proc.stdout.strip() + "\n", mode=0o600)

    def delete(self, name: str) -> None:
        path = self._blob_path(name)
        try:
            path.unlink()
        except FileNotFoundError:
            pass


class LinuxSecretServiceStore:
    backend_id = "linux-secretservice"

    def available(self) -> bool:
        if platform.system() != "Linux" or shutil.which("secret-tool") is None:
            return False
        # A probe lookup succeeds (rc 0/1) only when a Secret Service answers;
        # a missing/unreachable service errors out (rc >1) or times out.
        try:
            proc = _run(["secret-tool", "lookup", "service", _service(), "account", "__probe__"])
        except subprocess.TimeoutExpired:
            return False
        return proc.returncode in (0, 1)

    def get(self, name: str) -> str | None:
        proc = _run(["secret-tool", "lookup", "service", _service(), "account", name])
        if proc.returncode != 0:
            return None
        value = proc.stdout.rstrip("\n")
        return value or None

    def set(self, name: str, value: str) -> None:
        proc = _run(
            ["secret-tool", "store", "--label", f"{_service()} {name}",
             "service", _service(), "account", name],
            input_text=value,
        )
        if proc.returncode != 0:
            raise KeyStoreError(f"secret-tool store failed: {proc.stderr.strip()}")

    def delete(self, name: str) -> None:
        _run(["secret-tool", "clear", "service", _service(), "account", name])


class PlaintextFileStore:
    """Fallback: a 0600 file under OPENCLAW_HOME/keystore. Always available."""

    backend_id = "plaintext-file"

    def _path(self, name: str) -> Path:
        return resolve_openclaw_home() / "keystore" / f"{name}.plaintext"

    def available(self) -> bool:
        return True

    def get(self, name: str) -> str | None:
        path = self._path(name)
        if not path.exists():
            return None
        chmod_if_exists(path)
        value = path.read_text(encoding="utf-8").strip()
        return value or None

    def set(self, name: str, value: str) -> None:
        atomic_write_text(self._path(name), value.strip() + "\n", mode=0o600)

    def delete(self, name: str) -> None:
        try:
            self._path(name).unlink()
        except FileNotFoundError:
            pass


def resolve_keystore() -> KeyStore:
    """Return the first available OS-native backend, else the plaintext fallback."""
    preference = _backend_preference()
    if preference in {"plain", "plaintext", "plaintext-file", "file"}:
        return PlaintextFileStore()

    candidates: list[KeyStore]
    if preference in {"macos", "macos-keychain", "keychain"}:
        candidates = [MacKeychainStore()]
    elif preference in {"windows", "windows-dpapi", "dpapi"}:
        candidates = [WindowsDpapiStore()]
    elif preference in {"linux", "linux-secretservice", "secretservice"}:
        candidates = [LinuxSecretServiceStore()]
    elif preference == "native":
        candidates = [MacKeychainStore(), WindowsDpapiStore(), LinuxSecretServiceStore()]
    else:
        # Auto: native OS keystore first, plaintext fallback last. macOS Keychain
        # is prompt-free now that set() uses `-A` (open ACL, no partition-list) and
        # _backend_usable falls back gracefully if a session still can't authorize.
        candidates = [MacKeychainStore(), WindowsDpapiStore(), LinuxSecretServiceStore()]

    for candidate in candidates:
        try:
            if candidate.available() and _backend_usable(candidate):
                return candidate
        except Exception:
            continue
    return PlaintextFileStore()


def _backend_usable(candidate: KeyStore) -> bool:
    """Return true when a native backend can read the live key or write safely.

    A desktop keystore binary can exist while the session cannot authorize
    non-interactive writes. Treat that as unavailable so install/migration uses
    the bounded fallback instead of hanging or repeatedly failing.
    """
    try:
        if candidate.get(BOOT_KEY_ITEM):
            return True
    except Exception:
        pass

    probe_value = "ok"
    try:
        candidate.set(_PROBE_ITEM, probe_value)
        return candidate.get(_PROBE_ITEM) == probe_value
    except Exception:
        return False
    finally:
        try:
            candidate.delete(_PROBE_ITEM)
        except Exception:
            pass
