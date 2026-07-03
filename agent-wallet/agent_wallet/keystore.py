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

_SECURITY_BIN = "/usr/bin/security"
_SUBPROCESS_TIMEOUT = 10.0


def _service() -> str:
    """Keychain/Secret-Service service name. Overridable so tests never touch the
    real shared slot (the OS keychain is global, not scoped to OPENCLAW_HOME)."""
    return os.getenv("AGENT_WALLET_KEYSTORE_SERVICE", "").strip() or KEYSTORE_SERVICE


class KeyStoreError(Exception):
    """Raised when a keystore backend operation fails unexpectedly."""


@runtime_checkable
class KeyStore(Protocol):
    backend_id: str

    def available(self) -> bool: ...
    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


def _run(argv: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
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
        # -U update if exists; -T grants the security binary (our sole accessor)
        # so background reads via find-generic-password do not prompt.
        proc = _run([
            _SECURITY_BIN, "add-generic-password",
            "-s", _service(), "-a", name,
            "-w", value, "-U", "-T", _SECURITY_BIN,
        ])
        if proc.returncode != 0:
            raise KeyStoreError(f"security add-generic-password failed: {proc.stderr.strip()}")
        # Suppress the Sierra+ partition-list ACL prompt for non-interactive reads.
        _run([
            _SECURITY_BIN, "set-generic-password-partition-list",
            "-s", _service(), "-a", name,
            "-S", "unsigned:", "-k", "",
        ])

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
    for candidate in (MacKeychainStore(), WindowsDpapiStore(), LinuxSecretServiceStore()):
        try:
            if candidate.available():
                return candidate
        except Exception:
            continue
    return PlaintextFileStore()
