"""Owner-only terminal connection for Kernel; API keys never travel through tools."""
from __future__ import annotations

import asyncio
import getpass
import json
import os
import stat

from agent_wallet.config import resolve_boot_key, resolve_kernel_api_key, resolve_kernel_gateway_url, clear_secret_caches
from agent_wallet.kernel_browser import KernelClient
from agent_wallet.sealed_keys import resolve_sealed_keys_path, seal_keys, unseal_keys
from agent_wallet.wallet_layer.base import WalletBackendError


def run(command: str) -> int:
    if command == "kernel-status":
        personal = bool(resolve_kernel_api_key())
        print(json.dumps({"configured": personal, "provider": "kernel",
                          "connection_mode": "direct" if personal else "shared_auto",
                          "shared_gateway_url": resolve_kernel_gateway_url() if not personal else None}))
        return 0
    from agent_wallet.card_vault import _file_locks
    fcntl = _file_locks()
    from agent_wallet.card_vault_cli import require_terminal
    require_terminal()
    boot = resolve_boot_key()
    if not boot:
        raise WalletBackendError("Install the wallet runtime before connecting Kernel.")
    key = ""
    if command == "kernel-connect":
        key = getpass.getpass("Kernel API key (hidden): ").strip()
        if not 16 <= len(key) <= 2048 or not key.isascii() or any(c.isspace() for c in key):
            raise WalletBackendError("Invalid Kernel API key format.")
        # Read-only validation; no browser creation or paid checkout.
        asyncio.run(KernelClient(key).call("GET", "/browsers?limit=1"))
    path = resolve_sealed_keys_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path.with_suffix(".kernel.lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise WalletBackendError("Kernel connection lock must be an owner-only regular file.")
        fcntl.flock(fd, fcntl.LOCK_EX)
        secrets = unseal_keys(boot)
        if command == "kernel-connect":
            secrets["kernel_api_key"] = key
        else:
            secrets.pop("kernel_api_key", None)
        seal_keys(boot, secrets)
        clear_secret_caches()
    finally:
        key = ""
        os.close(fd)
    print("Kernel connected. API key stored in the encrypted runtime bundle." if command == "kernel-connect"
          else "Personal Kernel key removed. New browsers use shared access automatically when available. Existing direct sessions keep their inactivity timeout.")
    return 0
