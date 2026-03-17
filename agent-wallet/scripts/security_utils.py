"""Helpers for avoiding secret leakage in config patch scripts."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from agent_wallet.file_ops import atomic_write_text, chmod_if_exists

SENSITIVE_PLUGIN_KEYS = {"masterKey", "privateKey", "approvalSecret"}


def scrub_plugin_secrets(data: dict[str, Any]) -> dict[str, Any]:
    clone = copy.deepcopy(data)
    plugins = clone.get("plugins")
    if not isinstance(plugins, dict):
        return clone
    entries = plugins.get("entries")
    if not isinstance(entries, dict):
        return clone
    for entry in entries.values():
        if not isinstance(entry, dict):
            continue
        config = entry.get("config")
        if not isinstance(config, dict):
            continue
        for key in SENSITIVE_PLUGIN_KEYS:
            if key in config:
                config[key] = "[REDACTED]"
    return clone


def write_redacted_backup(path: Path, data: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(scrub_plugin_secrets(data), indent=2) + "\n", mode=0o600)
    chmod_if_exists(path, 0o600)
