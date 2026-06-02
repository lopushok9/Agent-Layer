"""Smoke test: server.py injects an update notice into MCP instructions.

The agent-facing channel appends a one-time "newer version available" block to
the FastMCP ``instructions`` string when the cached latest version is newer than
the installed one, and leaves the base instructions untouched otherwise.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "agent-wallet"
SERVER_PY = REPO_ROOT / "codex/plugins/agent-wallet/server.py"
TMP = Path("/tmp/openclaw-server-update-notice")

BASE = "BASE INSTRUCTIONS"


def _load_server():
    spec = importlib.util.spec_from_file_location("agent_wallet_server", SERVER_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _setup_home() -> None:
    if TMP.exists():
        shutil.rmtree(TMP)
    cache_dir = TMP / "agent-wallet-runtime"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["OPENCLAW_HOME"] = str(TMP)
    os.environ["AGENT_WALLET_PACKAGE_ROOT"] = str(PACKAGE_ROOT)
    os.environ.pop("AGENT_WALLET_DISABLE_UPDATE_CHECK", None)


def _write_cache(latest: str) -> None:
    path = TMP / "agent-wallet-runtime" / "update-check.json"
    # checked_at fresh so the background refresh skips the network during tests.
    path.write_text(json.dumps({"latest_version": latest, "checked_at": time.time()}), encoding="utf-8")


def main() -> None:
    server = _load_server()
    try:
        # Newer version available -> notice appended.
        _setup_home()
        _write_cache("99.0.0")
        out = server._update_notice_instructions(BASE)
        assert out.startswith(BASE), out
        assert "99.0.0" in out, out
        assert "update --yes" in out, out

        # No newer version -> base instructions unchanged.
        _setup_home()
        import agent_wallet

        _write_cache(agent_wallet.__version__)
        out = server._update_notice_instructions(BASE)
        assert out == BASE, out

        # Disabled -> base instructions unchanged even with a newer version.
        _setup_home()
        _write_cache("99.0.0")
        os.environ["AGENT_WALLET_DISABLE_UPDATE_CHECK"] = "1"
        out = server._update_notice_instructions(BASE)
        assert out == BASE, out

        print("OK smoke_server_update_notice")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
