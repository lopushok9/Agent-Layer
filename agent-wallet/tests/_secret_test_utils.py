"""Helpers for configuring sealed runtime secrets in smoke tests."""

from __future__ import annotations

import os
from pathlib import Path

from agent_wallet.sealed_keys import seal_keys

LEGACY_RUNTIME_SECRET_ENV_VARS = (
    "AGENT_WALLET_MASTER_KEY",
    "AGENT_WALLET_APPROVAL_SECRET",
    "SOLANA_AGENT_PRIVATE_KEY",
)


def install_test_sealed_secrets(
    openclaw_home: Path,
    *,
    boot_key: str,
    master_key: str | None = None,
    approval_secret: str | None = None,
    private_key: str | None = None,
) -> str:
    """Install a sealed runtime secret bundle for smoke tests."""
    os.environ["OPENCLAW_HOME"] = str(openclaw_home)
    os.environ["AGENT_WALLET_BOOT_KEY"] = boot_key
    for var_name in LEGACY_RUNTIME_SECRET_ENV_VARS:
        os.environ.pop(var_name, None)

    secrets: dict[str, str] = {}
    if master_key is not None:
        secrets["master_key"] = master_key
    if approval_secret is not None:
        secrets["approval_secret"] = approval_secret
    if private_key is not None:
        secrets["private_key"] = private_key
    if secrets:
        seal_keys(boot_key, secrets)
    return boot_key
