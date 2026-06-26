"""Smoke coverage for telemetry stats aggregation."""

from __future__ import annotations

import os
import tempfile

import telemetry_store


def main() -> None:
    original_env = {
        "TELEMETRY_DB_PATH": os.environ.get("TELEMETRY_DB_PATH"),
        "NPM_DOWNLOADS_ENABLED": os.environ.get("NPM_DOWNLOADS_ENABLED"),
    }
    original_fetch = telemetry_store._fetch_npm_downloads_range
    original_end_date = telemetry_store._downloads_end_date
    try:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TELEMETRY_DB_PATH"] = os.path.join(tmp, "telemetry.db")
            os.environ.pop("NPM_DOWNLOADS_ENABLED", None)
            telemetry_store._CONN = None
            telemetry_store._NPM_CACHE = None
            telemetry_store._NPM_CACHE_TS = 0.0

            def fake_fetch(start: str, end: str) -> dict:
                return {
                    "start": start,
                    "end": end,
                    "package": "@agentlayer.tech/wallet",
                    "downloads": [
                        {"day": "2026-05-01", "downloads": 10},
                        {"day": "2026-05-02", "downloads": 20},
                    ],
                }

            telemetry_store._fetch_npm_downloads_range = fake_fetch
            telemetry_store._downloads_end_date = lambda: "2026-05-02"

            event = telemetry_store.validate_event(
                {
                    "event": "tool_invoke",
                    "install_id": "abcdef1234567890",
                    "host": "codex",
                    "tool": "get_wallet_balance",
                    "backend": "solana_local",
                    "plugin_version": "0.1.49",
                    "ok": True,
                    "ts": 1,
                }
            )
            telemetry_store.record_event(event)
            install_event = telemetry_store.validate_event(
                {
                    "event": "install_success",
                    "install_id": "abcdef1234567890",
                    "host": "unknown",
                    "source": "npx",
                    "command": "install",
                    "plugin_version": "0.1.49",
                    "ok": True,
                    "ts": 2,
                }
            )
            telemetry_store.record_event(install_event)

            stats = telemetry_store.summary(30)
            assert stats["ok"] is True
            assert stats["total_events"] == 2
            assert stats["active_installs"] == 1
            assert {"key": "codex", "calls": 1, "installs": 1} in stats["by_host"]
            assert {"key": "unknown", "calls": 1, "installs": 1} in stats["by_host"]
            assert stats["by_tool"] == [{"key": "get_wallet_balance", "calls": 1, "installs": 1}]
            assert {"key": "install_success", "calls": 1, "installs": 1} in stats["by_event"]
            assert {"key": "npx", "calls": 1, "installs": 1} in stats["by_source"]
            assert {"key": "install", "calls": 1, "installs": 1} in stats["by_command"]
            assert stats["npm_downloads"]["ok"] is True
            assert stats["npm_downloads"]["all_time"] == 30
            assert stats["npm_downloads"]["last_30_days"] == 30

        print("smoke_telemetry_stats: ok")
    finally:
        telemetry_store._fetch_npm_downloads_range = original_fetch
        telemetry_store._downloads_end_date = original_end_date
        telemetry_store._CONN = None
        telemetry_store._NPM_CACHE = None
        telemetry_store._NPM_CACHE_TS = 0.0
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    main()
