"""`invoke --approval-summary-json` mints the approval token in-process.

Previously a bridge-managed execute cost two cold subprocesses: one
`issue-approval` run and one `invoke` run, each paying full interpreter boot
and onboarding. The invoke subcommand now accepts the confirmation summary
and mints the token inside the same process, right before the tool call.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _FakeResult:
    def model_dump(self):
        return {"ok": True, "data": {}}


class _FakeAdapter:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def invoke(self, tool_name, arguments):
        self.calls.append((tool_name, dict(arguments)))
        return _FakeResult()


class _FakeContext:
    def __init__(self):
        self.adapter = _FakeAdapter()
        self.approvals: list[dict] = []

    def issue_execute_approval(self, *, tool_name, confirmation_summary, mainnet_confirmed=False, ttl_seconds=None):
        self.approvals.append(
            {
                "tool_name": tool_name,
                "summary": confirmation_summary,
                "mainnet_confirmed": mainnet_confirmed,
                "ttl_seconds": ttl_seconds,
            }
        )
        return "fake-approval-token"


def check_cli_inline_mint() -> None:
    from agent_wallet import openclaw_cli

    context = _FakeContext()
    real_build = openclaw_cli._build_runtime_context
    openclaw_cli._build_runtime_context = lambda user_id, config, **kwargs: context
    try:
        # 1. Summary provided, no caller token: mint and inject.
        asyncio.run(
            openclaw_cli._run_invoke(
                "user-1",
                "swap_evm_tokens",
                {"mode": "execute"},
                {},
                approval_summary={"amount": "1"},
                approval_mainnet_confirmed=True,
            )
        )
        tool, args = context.adapter.calls[-1]
        assert tool == "swap_evm_tokens"
        assert args["approval_token"] == "fake-approval-token", args
        assert context.approvals[-1]["mainnet_confirmed"] is True
        assert context.approvals[-1]["summary"] == {"amount": "1"}

        # 2. Caller-provided token is never overwritten.
        asyncio.run(
            openclaw_cli._run_invoke(
                "user-1",
                "swap_evm_tokens",
                {"mode": "execute", "approval_token": "caller-token"},
                {},
                approval_summary={"amount": "1"},
            )
        )
        _, args = context.adapter.calls[-1]
        assert args["approval_token"] == "caller-token", args
        assert len(context.approvals) == 1, "no extra mint for caller-provided token"

        # 3. No summary: behavior unchanged.
        asyncio.run(openclaw_cli._run_invoke("user-1", "get_wallet_balance", {}, {}))
        _, args = context.adapter.calls[-1]
        assert "approval_token" not in args
    finally:
        openclaw_cli._build_runtime_context = real_build


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_bridge_single_subprocess_execute() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    server_path = repo_root / "codex" / "plugins" / "agent-wallet" / "server.py"
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["OPENCLAW_HOME"] = tmp
        os.environ["AGENT_WALLET_PREWARM_READ_WORKER"] = "0"
        module = _load_module(server_path, "codex_agent_wallet_server_inline_approval")

        commands: list[tuple[str, list[str]]] = []

        preview_payload = {
            "ok": True,
            "data": {
                "mode": "preview",
                "is_mainnet": True,
                "confirmation_summary": {"token_in": "USDC", "amount": "1"},
            },
        }
        execute_payload = {"ok": True, "data": {"mode": "execute", "signature": "sig"}}

        def fake_call_wallet_cli(command, extra_args):
            commands.append((command, list(extra_args)))
            if command != "invoke":
                raise AssertionError(f"unexpected CLI command: {command}")
            args_json_idx = extra_args.index("--arguments-json") + 1
            import json as _json

            arguments = _json.loads(extra_args[args_json_idx])
            if str(arguments.get("mode") or "") == "execute":
                return execute_payload
            return preview_payload

        module._call_wallet_cli = fake_call_wallet_cli

        config = {"backend": "wdk_evm_local", "network": "base"}
        module._invoke_wallet_tool_blocking(
            "swap_evm_tokens", dict(config), {"mode": "preview", "network": "base"}
        )
        module._invoke_wallet_tool_blocking(
            "swap_evm_tokens", dict(config), {"mode": "execute", "network": "base"}
        )

        issued = [c for c, _ in commands if c == "issue-approval"]
        assert not issued, "execute must not spawn a separate issue-approval subprocess"
        assert [c for c, _ in commands] == ["invoke", "invoke"], commands

        execute_args = commands[-1][1]
        assert "--approval-summary-json" in execute_args, execute_args
        assert "--approval-mainnet-confirmed" in execute_args, execute_args
        summary_json = execute_args[execute_args.index("--approval-summary-json") + 1]
        import json as _json

        summary = _json.loads(summary_json)
        assert summary.get("token_in") == "USDC"
        assert summary.get("_preview_digest"), "summary must carry the preview digest"


def main() -> None:
    check_cli_inline_mint()
    check_bridge_single_subprocess_execute()
    print("smoke_invoke_inline_approval OK")


if __name__ == "__main__":
    main()
