"""Smoke coverage for the telemetry HTML dashboard."""

from __future__ import annotations

import os
import tempfile

import telemetry_store
from starlette.testclient import TestClient

import app as gateway_app


def main() -> None:
    original_env = {
        "TELEMETRY_DB_PATH": os.environ.get("TELEMETRY_DB_PATH"),
        "NPM_DOWNLOADS_ENABLED": os.environ.get("NPM_DOWNLOADS_ENABLED"),
        "TELEMETRY_STATS_TOKEN": os.environ.get("TELEMETRY_STATS_TOKEN"),
    }
    original_fetch = telemetry_store._fetch_npm_downloads_range
    original_end_date = telemetry_store._downloads_end_date
    try:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TELEMETRY_DB_PATH"] = os.path.join(tmp, "telemetry.db")
            os.environ["TELEMETRY_STATS_TOKEN"] = "test-token"
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

            for raw in (
                {
                    "event": "tool_invoke",
                    "install_id": "abcdef1234567890",
                    "host": "codex",
                    "tool": "get_wallet_balance",
                    "backend": "solana_local",
                    "plugin_version": "0.1.49",
                    "ok": True,
                    "ts": 1,
                },
                {
                    "event": "install_success",
                    "install_id": "abcdef1234567890",
                    "host": "unknown",
                    "source": "npx",
                    "command": "install",
                    "plugin_version": "0.1.49",
                    "ok": True,
                    "ts": 2,
                },
            ):
                telemetry_store.record_event(telemetry_store.validate_event(raw))
            telemetry_store.record_rpc_usage(
                endpoint="evm_rpc",
                network="base",
                provider="alchemy",
                method="eth_chainId",
                status_bucket="2xx",
                latency_bucket="lt_100ms",
            )

            client = TestClient(gateway_app.app)

            html_response = client.get(
                "/v1/telemetry/stats?token=test-token",
                headers={"accept": "text/html"},
            )
            assert html_response.status_code == 200
            assert "text/html" in html_response.headers.get("content-type", "")
            assert "agentlayer telemetry dashboard" in html_response.text
            assert "total metric graphs" in html_response.text
            assert "events / day" in html_response.text
            assert "downloads / day" in html_response.text
            assert "rpc usage / day" in html_response.text
            assert "npm downloads all-time" in html_response.text
            assert "#ffffff" in html_response.text

            json_response = client.get("/v1/telemetry/stats?token=test-token&format=json")
            assert json_response.status_code == 200
            payload = json_response.json()
            assert payload["ok"] is True
            assert payload["rpc_usage"]["total_calls"] == 1

        print("smoke_telemetry_dashboard: ok")
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
