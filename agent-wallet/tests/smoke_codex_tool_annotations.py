"""Verify safety annotations on the actual MCP tools/list transport, offline."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastmcp import Client


async def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    server_path = repo_root / "codex" / "plugins" / "agent-wallet" / "server.py"
    module_spec = importlib.util.spec_from_file_location("codex_annotation_test", server_path)
    assert module_spec and module_spec.loader
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)

    with tempfile.TemporaryDirectory(prefix="agentlayer-mcp-annotations-") as home:
        with patch.dict(os.environ, {
            "OPENCLAW_HOME": home,
            "AGENT_WALLET_PACKAGE_ROOT": str(repo_root / "agent-wallet"),
        }):
            definitions = module._build_tool_definitions()
            # Missing metadata must never silently classify a tool as safe.
            definitions.append({
                "name": "unclassified_test_tool",
                "description": "Offline registration fixture.",
                "input_schema": {"type": "object", "properties": {}},
            })
            by_name = {spec["name"]: spec for spec in definitions}
            reads = {
                "get_active_wallet_backend", "get_wallet_overview", "get_wallet_balance",
                "x402_search_services", "x402_get_service_details", "x402_preview_request",
            }
            writes = {
                "x402_pay_request", "transfer_evm_native", "swap_solana_tokens",
                "set_wallet_backend", "set_evm_network", "unclassified_test_tool",
            }
            assert reads | writes <= by_name.keys()
            active_backend = AsyncMock(return_value={"backend": "solana"})
            with (
                patch.object(module, "_build_tool_definitions", return_value=definitions),
                patch.object(module, "_update_notice_instructions", side_effect=lambda text: text),
                patch.object(module, "_handle_get_active_wallet_backend", active_backend),
                patch.object(module, "_record_bridge_tool_call"),
            ):
                async with Client(module.build_server()) as client:
                    tools = {tool.name: tool for tool in await client.list_tools()}
                    assert tools.keys() == by_name.keys()
                    annotations = {}
                    for name, spec in by_name.items():
                        wire = tools[name].model_dump(by_alias=True, exclude_none=True)
                        hints = wire["annotations"]
                        annotations[name] = hints
                        is_read = spec.get("read_only") is True
                        assert hints["readOnlyHint"] is is_read, name
                        assert hints["destructiveHint"] is not is_read, name
                    for name in reads:
                        assert annotations[name]["readOnlyHint"] is True, name
                    for name in writes:
                        assert annotations[name]["readOnlyHint"] is False, name
                        assert annotations[name]["destructiveHint"] is True, name
                    # Reads still reach their existing handler; no wallet, RPC or payment.
                    result = await client.call_tool("get_active_wallet_backend", {})
                    assert not result.is_error
                    assert result.data == {"backend": "solana"}
                    active_backend.assert_awaited_once_with()

    print("smoke_codex_tool_annotations: ok")


if __name__ == "__main__":
    asyncio.run(main())
