"""Smoke test Codex approval attach behavior for autonomous Base swaps."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    server_path = repo_root / "codex" / "plugins" / "agent-wallet" / "server.py"
    module = _load_module(server_path, "codex_agent_wallet_server_autonomous_base")

    module.approval_preview_cache.clear()
    module._user_id = lambda: "autonomous-test-user"

    preview_payload = {
        "ok": True,
        "data": {
            "mode": "preview",
            "confirmation_summary": {
                "operation": "EVM swap",
                "network": "base",
                "token_in": "0x0000000000000000000000000000000000000001",
                "token_out": "0x0000000000000000000000000000000000000002",
                "input_amount_raw": "1000",
            },
        },
    }
    module._cache_preview_for_approval("autonomous-test-user", "swap_evm_tokens", preview_payload)

    # A cached preview yields the digest-bound summary for in-subprocess token
    # minting; the bridge no longer injects approval_token itself.
    params = {"mode": "execute", "network": "base"}
    used_cache, approval_args = module._attach_approval_for_execute(
        "swap_evm_tokens", {"network": "base"}, params
    )
    assert used_cache is not None
    assert "approval_token" not in params, "token is minted inside the invoke subprocess"
    assert isinstance(approval_args, dict)
    summary = approval_args["summary"]
    assert summary["operation"] == "EVM swap"
    assert summary["_preview_digest"], "summary must be digest-bound to the preview"
    assert approval_args["mainnet_confirmed"] is False

    module.approval_preview_cache.clear()
    autonomous_params = {"mode": "execute", "network": "base"}
    assert module._attach_approval_for_execute(
        "swap_evm_tokens",
        {"network": "base"},
        autonomous_params,
    ) == (None, None)
    assert "approval_token" not in autonomous_params

    autonomous_defi_params = {"mode": "execute", "network": "ethereum"}
    assert module._attach_approval_for_execute(
        "manage_evm_lido_position",
        {"network": "ethereum"},
        autonomous_defi_params,
    ) == (None, None)
    assert "approval_token" not in autonomous_defi_params

    try:
        module._attach_approval_for_execute(
            "swap_evm_tokens",
            {"network": "ethereum"},
            {"mode": "execute", "network": "ethereum"},
        )
    except RuntimeError as exc:
        assert "Confirmation context" in str(exc)
    else:
        raise AssertionError("ethereum swap execute without approval context should be rejected")

    print("smoke_codex_autonomous_base_swap_approval: ok")


if __name__ == "__main__":
    main()
