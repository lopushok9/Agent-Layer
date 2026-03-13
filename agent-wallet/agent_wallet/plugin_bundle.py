"""Helpers for exposing agent-wallet as an OpenClaw-style plugin bundle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_wallet.openclaw_adapter import OpenClawWalletAdapter
from agent_wallet.wallet_layer.base import AgentWalletBackend


def _package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def get_plugin_manifest() -> dict[str, Any]:
    """Load the OpenClaw plugin manifest from disk."""
    manifest_path = _package_root() / "openclaw.plugin.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def get_skill_text() -> str:
    """Load the wallet operator skill text."""
    skill_path = _package_root() / "skills" / "wallet-operator" / "SKILL.md"
    return skill_path.read_text(encoding="utf-8")


def build_openclaw_plugin_bundle(backend: AgentWalletBackend) -> dict[str, Any]:
    """Build a runtime-ready bundle for OpenClaw-style plugin registration."""
    adapter = OpenClawWalletAdapter(backend)
    return {
        "manifest": get_plugin_manifest(),
        "instructions": "\n\n".join(
            [
                adapter.get_runtime_instructions(),
                get_skill_text(),
            ]
        ),
        "tools": [tool.model_dump() for tool in adapter.list_tools()],
        "invoke": adapter.invoke,
    }
