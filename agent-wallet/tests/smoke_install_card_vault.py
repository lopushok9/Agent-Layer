"""Installer provisions matching vault identities without prompting or unlocking."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_wallet.config import resolve_card_vault_user_id


def main():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("vault_installer", root / "scripts" / "install_agent_wallet.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    def provision(command, **kwargs):
        assert command[1:4] == ["-m", "agent_wallet.card_vault_cli", "provision"]
        assert kwargs["timeout"] == 30
        assert kwargs["capture_output"] is True
        assert kwargs["env"]["PYTHONPATH"] == str(root)
        calls.append(command[-1])
        return subprocess.CompletedProcess(command, 0, json.dumps({"ok": True, "status": "ready", "created": False}))
    args = argparse.Namespace(user_id="configured-owner", dry_run=False, config_path="/nonexistent/agentlayer-test-config.json")
    with patch.dict(os.environ, {"USER": "os-owner", "AGENT_WALLET_USER_ID": "env-owner", "OPENCLAW_AGENT_WALLET_USER_ID": "env-owner"}), patch.object(module.platform, "system", return_value="Darwin"), patch.object(module.subprocess, "run", side_effect=provision):
        result = module._bootstrap_card_vault(Path(sys.executable), root, args)
        assert result["status"] == "ready"
        assert set(calls) == {"configured-owner", "os-owner", "env-owner"}
    with tempfile.TemporaryDirectory() as directory:
        config = Path(directory, "openclaw.json")
        config.write_text(json.dumps({"plugins": {"entries": {"agent-wallet": {"config": {"userId": "existing-host-owner"}}}}}))
        args.config_path = str(config)
        calls.clear()
        with patch.object(module.platform, "system", return_value="Darwin"), patch.object(module.subprocess, "run", side_effect=provision):
            assert module._bootstrap_card_vault(Path(sys.executable), root, args)["status"] == "ready"
            assert "existing-host-owner" in calls
    args.config_path = "/nonexistent/agentlayer-test-config.json"
    with patch.object(module.subprocess, "run", side_effect=AssertionError("No native access in dry run")):
        args.dry_run = True
        assert module._bootstrap_card_vault(Path(sys.executable), root, args)["status"] == "skipped_dry_run"
    args.dry_run = False
    with patch.object(module.platform, "system", return_value="Linux"), patch.object(module.subprocess, "run", side_effect=AssertionError("No plaintext fallback")):
        assert module._bootstrap_card_vault(Path(sys.executable), root, args)["status"] == "unsupported_platform"
    with patch.object(module.platform, "system", return_value="Darwin"), patch.object(module.subprocess, "run", side_effect=subprocess.CalledProcessError(1, [], stderr="secret-test-value")):
        result = module._bootstrap_card_vault(Path(sys.executable), root, args)
        assert result["status"] == "attention_required"
        assert "secret-test-value" not in json.dumps(result)
    with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"OPENCLAW_HOME": home, "AGENT_WALLET_USER_ID": "", "OPENCLAW_AGENT_WALLET_USER_ID": "", "USER": "os-owner"}):
        assert resolve_card_vault_user_id() == "os-owner"
        Path(home, "openclaw.json").write_text(json.dumps({"plugins": {"entries": {"agent-wallet": {"config": {"userId": "configured-owner"}}}}}))
        assert resolve_card_vault_user_id() == "configured-owner"
        with patch.dict(os.environ, {"AGENT_WALLET_USER_ID": "explicit-owner"}):
            assert resolve_card_vault_user_id() == "explicit-owner"
    print("smoke_install_card_vault: ok")


if __name__ == "__main__":
    main()
