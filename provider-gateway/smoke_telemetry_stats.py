"""Smoke coverage for telemetry stats aggregation."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import date, timedelta

import telemetry_store


def main() -> None:
    # Repeated calls, failures, and non-wallet events must not inflate the
    # cumulative count; gaps must retain the preceding total.
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ev (install_id TEXT, event TEXT, received_ts INTEGER, ok INTEGER)")
    today = date.today()
    first = (today - timedelta(days=3)).isoformat()
    third = (today - timedelta(days=1)).isoformat()
    conn.executemany(
        "INSERT INTO ev VALUES (?, ?, strftime('%s', ?), ?)",
        [("a", "tool_invoke", first, 0), ("a", "tool_invoke", third, 1),
         ("b", "tool_invoke", third, 1), ("c", "session_start", first, 1)],
    )
    assert [row["count"] for row in telemetry_store._cumulative_wallet_installs(conn)] == [1, 1, 2, 2]
    conn.close()
    original_env = {
        "TELEMETRY_DB_PATH": os.environ.get("TELEMETRY_DB_PATH"),
        "NPM_DOWNLOADS_ENABLED": os.environ.get("NPM_DOWNLOADS_ENABLED"),
        "TELEMETRY_EXCLUDE_INSTALL_IDS": os.environ.get("TELEMETRY_EXCLUDE_INSTALL_IDS"),
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
            x402_event = telemetry_store.validate_event(
                {
                    "event": "x402_payment_settled",
                    "install_id": "abcdef1234567890",
                    "host": "codex",
                    "backend": "wdk_evm_local",
                    "plugin_version": "0.1.49",
                    "ok": True,
                    "ts": 3,
                    "network": "eip155:8453",
                    "scheme": "exact",
                    "asset_family": "usdc",
                    "amount_bucket": "2_to_10_usd",
                    "settlement_status": "settled",
                    "error_class": "unknown",
                }
            )
            telemetry_store.record_event(x402_event)
            telemetry_store.record_rpc_usage(
                endpoint="evm_rpc",
                network="base",
                provider="alchemy",
                method="eth_chainId",
                status_bucket="2xx",
                latency_bucket="lt_100ms",
            )

            stats = telemetry_store.summary(30)
            assert stats["ok"] is True
            assert stats["total_events"] == 3
            assert stats["active_installs"] == 1
            assert stats["wallet_active_installs"] == 1
            assert stats["cumulative_wallet_active_installs"][-1]["count"] == 1
            assert stats["wallet_dau"] == 1
            assert {"key": "codex", "calls": 2, "installs": 1} in stats["by_host"]
            assert stats["wallet_by_host"] == [{"key": "codex", "calls": 1, "installs": 1}]
            assert {"key": "unknown", "calls": 1, "installs": 1} in stats["by_host"]
            assert stats["by_tool"] == [{"key": "get_wallet_balance", "calls": 1, "installs": 1}]
            assert stats["by_backend_tool"] == [
                {
                    "backend": "solana_local",
                    "tool": "get_wallet_balance",
                    "calls": 1,
                    "installs": 1,
                }
            ]
            assert {"key": "core_wallet", "calls": 1, "installs": 1} in stats["by_tool_category"]
            assert stats["x402"]["pay_tool_invocations"] == 0
            assert stats["x402"]["payment_settled"] == 1
            assert stats["x402"]["payment_settlement_rate"] is None
            assert stats["x402"]["by_network"] == [{"key": "eip155:8453", "calls": 1}]
            assert {"key": "install_success", "calls": 1, "installs": 1} in stats["by_event"]
            assert {"key": "npx", "calls": 1, "installs": 1} in stats["by_source"]
            assert {"key": "install", "calls": 1, "installs": 1} in stats["by_command"]
            assert any(item["key"] == "tool_invocations" for item in stats["success_by_family"])
            assert len(stats["daily"]["events"]) == 30
            assert stats["daily"]["events"][-1]["count"] >= 0
            assert stats["npm_downloads"]["ok"] is True
            assert stats["npm_downloads"]["all_time"] == 30
            assert stats["npm_downloads"]["last_30_days"] == 30
            assert stats["npm_downloads"]["daily"] == [
                {"day": "2026-05-01", "downloads": 10},
                {"day": "2026-05-02", "downloads": 20},
            ]
            assert stats["npm_downloads"]["daily_window"] == stats["npm_downloads"]["daily"]
            assert stats["rpc_usage"]["total_calls"] == 1
            assert stats["rpc_usage"]["by_endpoint"] == [{"key": "evm_rpc", "calls": 1}]
            assert stats["rpc_usage"]["by_method"] == [{"key": "eth_chainId", "calls": 1}]

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TELEMETRY_DB_PATH"] = os.path.join(tmp, "telemetry.db")
            os.environ["NPM_DOWNLOADS_ENABLED"] = "false"
            telemetry_store._CONN = None

            def emit(**raw) -> None:
                base = {"install_id": "abcdef1234567890", "host": "cursor", "plugin_version": "0.1.124", "ok": True}
                telemetry_store.record_event(telemetry_store.validate_event({**base, **raw}))

            # Hosts the clients emit must survive validation.
            assert telemetry_store.validate_event(
                {"event": "session_start", "install_id": "abcdef12", "host": "mcp"}
            )["host"] == "mcp"
            # Retired BTC backend and bogus modes are normalized away.
            btc = telemetry_store.validate_event(
                {"event": "tool_invoke", "install_id": "abcdef12", "tool": "get_wallet_balance",
                 "backend": "wdk_btc_local", "mode": "drop table"}
            )
            assert btc["backend"] == "unknown" and btc["mode"] == ""

            emit(event="install_success", host="unknown", command="install")
            emit(event="plugin_install_success", command="cursor_install")
            emit(event="session_start")
            emit(event="tool_invoke", tool="get_wallet_balance", backend="wdk_evm_local")
            emit(event="tool_invoke", tool="get_wallet_portfolio", backend="wdk_evm_local")
            emit(event="tool_invoke", tool="swap_evm_tokens", backend="wdk_evm_local", mode="preview")
            emit(event="tool_invoke", tool="swap_evm_tokens", backend="wdk_evm_local", mode="execute",
                 ok=False, error_class="approval")
            # A second install in the same category must not double count.
            emit(event="tool_invoke", tool="get_wallet_balance", install_id="1234567890abcdef", host="hermes")
            # Internal install: hidden by TELEMETRY_EXCLUDE_INSTALL_IDS.
            emit(event="tool_invoke", tool="x402_preview_request", install_id="deadbeefdeadbeef", host="openclaw")

            os.environ["TELEMETRY_EXCLUDE_INSTALL_IDS"] = "deadbeefdeadbeef, not-an-id!"
            stats = telemetry_store.summary(30)
            os.environ.pop("TELEMETRY_EXCLUDE_INSTALL_IDS", None)

            assert stats["excluded_install_ids"] == 1
            assert stats["excluded_events"] == 1
            assert all(row["key"] != "x402_preview_request" for row in stats["tools"])
            hosts = {row["key"]: row for row in stats["hosts"]}
            assert "openclaw" not in hosts
            cursor = hosts["cursor"]
            assert cursor["plugin_installs"] == 1
            assert cursor["launched_installs"] == 1
            assert cursor["wallet_users"] == 1
            assert cursor["tool_calls"] == 4
            assert cursor["success_rate"] == 0.75
            assert hosts["hermes"]["wallet_users"] == 1
            assert {"key": "core_wallet", "calls": 3, "installs": 2} in stats["by_tool_category"]
            swap = next(row for row in stats["tools"] if row["key"] == "swap_evm_tokens")
            assert (swap["previews"], swap["executes"], swap["ok_calls"]) == (1, 1, 1)
            assert stats["tool_errors"] == [
                {"tool": "swap_evm_tokens", "error_class": "approval", "calls": 1, "installs": 1}
            ]
            assert stats["success_rate"] == 4 / 5
            users = stats["users"]
            assert users["wallet_users"] == 2
            assert users["executing_users"] == 1
            assert users["returning_users"] == 0
            assert [row["installs"] for row in users["funnel"]] == [1, 1, 1, 1, 0]
            assert {"key": "execute", "calls": 1, "installs": 1} in stats["by_mode"]

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
