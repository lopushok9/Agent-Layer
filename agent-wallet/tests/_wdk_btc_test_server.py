"""Small fake local HTTP server for wdk-btc-wallet integration tests."""

from __future__ import annotations

import json
import threading
from contextlib import AbstractContextManager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class FakeWdkBtcWalletServer(AbstractContextManager["FakeWdkBtcWalletServer"]):
    wallet_id = "btc-wallet-123"

    def __init__(self, network: str = "testnet", host: str = "127.0.0.1", port: int = 0):
        self.network = network
        self.host = host
        self.port = int(port)
        self.address = (
            "tb1qagentwallet000000000000000000000000000000"
            if network == "testnet"
            else "bc1qagentwallet000000000000000000000000000000"
        )
        self.sent_payloads: list[dict[str, Any]] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        assert self._server is not None
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "FakeWdkBtcWalletServer":
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A003
                return

            def _send(self, status: int, payload: dict[str, Any]) -> None:
                encoded = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def _read_json(self) -> dict[str, Any]:
                raw_len = int(self.headers.get("Content-Length", "0"))
                if raw_len <= 0:
                    return {}
                raw = self.rfile.read(raw_len)
                return json.loads(raw.decode("utf-8"))

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/health":
                    self._send(
                        200,
                        {
                            "ok": True,
                            "service": "wdk-btc-wallet",
                            "wallet": "bitcoin",
                            "network": outer.network,
                        },
                    )
                    return
                self._send(404, {"ok": False, "error": "Not Found"})

            def do_POST(self) -> None:  # noqa: N802
                body = self._read_json()
                wallet_id = str(body.get("walletId") or "").strip()
                fee_rate = body.get("feeRate")
                fee = 423 if fee_rate else 141

                if self.path == "/v1/btc/wallets/get":
                    if wallet_id != outer.wallet_id:
                        self._send(400, {"ok": False, "error": "Unknown walletId."})
                        return
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "walletId": outer.wallet_id,
                                "label": "Agent BTC Wallet",
                                "network": outer.network,
                                "bip": 84,
                                "source": "created",
                                "createdAt": "2026-03-25T00:00:00Z",
                                "updatedAt": "2026-03-25T00:00:00Z",
                            },
                        },
                    )
                    return

                if self.path == "/v1/btc/wallets/create":
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "walletId": outer.wallet_id,
                                "label": str(body.get("label") or "Agent BTC Wallet"),
                                "network": str(body.get("network") or outer.network),
                                "bip": 84,
                                "source": "created",
                                "createdAt": "2026-03-25T00:00:00Z",
                                "updatedAt": "2026-03-25T00:00:00Z",
                                "unlocked": True,
                                "unlockExpiresAt": None,
                                **(
                                    {"seedPhrase": "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"}
                                    if body.get("revealSeedPhrase")
                                    else {}
                                ),
                            },
                        },
                    )
                    return

                if self.path == "/v1/btc/wallets/import":
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "walletId": outer.wallet_id,
                                "label": str(body.get("label") or "Agent BTC Wallet"),
                                "network": str(body.get("network") or outer.network),
                                "bip": 84,
                                "source": "imported",
                                "createdAt": "2026-03-25T00:00:00Z",
                                "updatedAt": "2026-03-25T00:00:00Z",
                                "unlocked": True,
                                "unlockExpiresAt": None,
                            },
                        },
                    )
                    return

                if self.path == "/v1/btc/wallets/unlock":
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "walletId": outer.wallet_id,
                                "label": "Agent BTC Wallet",
                                "unlocked": True,
                                "unlockExpiresAt": None,
                            },
                        },
                    )
                    return

                if self.path == "/v1/btc/wallets/reveal-seed":
                    if wallet_id != outer.wallet_id:
                        self._send(400, {"ok": False, "error": "Unknown walletId."})
                        return
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "walletId": outer.wallet_id,
                                "seedPhrase": (
                                    "abandon abandon abandon abandon abandon abandon "
                                    "abandon abandon abandon abandon abandon about"
                                ),
                            },
                        },
                    )
                    return

                if self.path == "/v1/btc/wallets/lock":
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "walletId": outer.wallet_id,
                                "unlocked": False,
                            },
                        },
                    )
                    return

                if self.path == "/v1/btc/address/resolve":
                    if wallet_id != outer.wallet_id:
                        self._send(400, {"ok": False, "error": "Wallet is locked."})
                        return
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "address": outer.address,
                                "network": str(body.get("network") or outer.network),
                            },
                        },
                    )
                    return

                if self.path == "/v1/btc/balance/get":
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "address": outer.address,
                                "balance": 121140,
                            },
                        },
                    )
                    return

                if self.path == "/v1/btc/transfers/get":
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "address": outer.address,
                                "transfers": [
                                    {
                                        "hash": "incoming-hash",
                                        "direction": "incoming",
                                        "value": 121140,
                                    }
                                ],
                            },
                        },
                    )
                    return

                if self.path == "/v1/btc/fee-rates/get":
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "feeRates": {
                                    "slow": 1,
                                    "normal": 2,
                                    "fast": 3,
                                }
                            },
                        },
                    )
                    return

                if self.path == "/v1/btc/max-spendable/get":
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "address": outer.address,
                                "maxSpendable": {
                                    "amount": 120699,
                                    "fee": fee,
                                    "changeValue": 300,
                                },
                            },
                        },
                    )
                    return

                if self.path == "/v1/btc/transfer/quote":
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "quote": {
                                    "fee": fee,
                                }
                            },
                        },
                    )
                    return

                if self.path == "/v1/btc/transfer/send":
                    outer.sent_payloads.append(body)
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "result": {
                                    "hash": "btc-test-hash",
                                    "fee": fee,
                                }
                            },
                        },
                    )
                    return

                self._send(404, {"ok": False, "error": "Not Found"})

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._server = None
        self._thread = None
        return None
