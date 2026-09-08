"""Smoke coverage for CLI telemetry result status."""

from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from agent_wallet import openclaw_cli  # noqa: E402


def main() -> None:
    original_argv = sys.argv
    original_invoke = openclaw_cli._run_invoke
    original_telemetry = openclaw_cli._telemetry_record
    events: list[dict] = []
    try:
        async def failed_invoke(*_args, **_kwargs):
            return {"tool": "x402_pay_request", "ok": False, "error": "payment rejected"}

        openclaw_cli._run_invoke = failed_invoke
        openclaw_cli._telemetry_record = lambda tool, **kwargs: events.append(
            {"tool": tool, **kwargs}
        )
        sys.argv = [
            "openclaw_cli",
            "invoke",
            "--user-id",
            "telemetry-test-user",
            "--tool",
            "x402_pay_request",
            "--arguments-json",
            "{}",
            "--config-json",
            '{"backend":"wdk_evm_local"}',
        ]
        assert openclaw_cli.main() == 0
        assert events == [
            {"tool": "x402_pay_request", "backend": "wdk_evm_local", "ok": False}
        ]
    finally:
        sys.argv = original_argv
        openclaw_cli._run_invoke = original_invoke
        openclaw_cli._telemetry_record = original_telemetry

    print("smoke_telemetry_cli_result: ok")


if __name__ == "__main__":
    main()
