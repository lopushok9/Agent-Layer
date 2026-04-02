"""Small fake local HTTP server for wdk-evm-wallet integration tests."""

from __future__ import annotations

import json
import threading
from contextlib import AbstractContextManager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class FakeWdkEvmWalletServer(AbstractContextManager["FakeWdkEvmWalletServer"]):
    wallet_id = "evm-wallet-123"

    def __init__(
        self,
        network: str = "sepolia",
        host: str = "127.0.0.1",
        port: int = 0,
        auth_token: str = "test-local-evm-token",
    ):
        self.network = network
        self.host = host
        self.port = int(port)
        self.auth_token = str(auth_token).strip()
        self.address = "0x1111111111111111111111111111111111111111"
        self.token = "0x2222222222222222222222222222222222222222"
        self.sent_payloads: list[dict[str, Any]] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        assert self._server is not None
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def chain_id(self) -> int:
        return self.chain_id_for(self.network)

    @staticmethod
    def chain_id_for(network: str) -> int:
        mapping = {
            "ethereum": 1,
            "sepolia": 11155111,
            "base": 8453,
            "base-sepolia": 84532,
        }
        return mapping[network]

    def __enter__(self) -> "FakeWdkEvmWalletServer":
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

            def _authorized(self) -> bool:
                if not outer.auth_token:
                    return True
                header = str(self.headers.get("Authorization") or "").strip()
                return header == f"Bearer {outer.auth_token}"

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
                            "service": "wdk-evm-wallet",
                            "wallet": "evm",
                            "network": outer.network,
                            "chainId": outer.chain_id,
                        },
                    )
                    return
                if self.path == "/v1/evm/wallets":
                    if not self._authorized():
                        self._send(401, {"ok": False, "error": "Unauthorized."})
                        return
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": [
                                {
                                    "walletId": outer.wallet_id,
                                    "label": "Agent EVM Wallet",
                                    "network": outer.network,
                                    "source": "created",
                                    "unlocked": True,
                                    "unlockExpiresAt": None,
                                }
                            ],
                        },
                    )
                    return
                if self.path == "/v1/evm/network":
                    if not self._authorized():
                        self._send(401, {"ok": False, "error": "Unauthorized."})
                        return
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "activeNetwork": outer.network,
                                "profiles": {
                                    outer.network: {
                                        "chainId": outer.chain_id,
                                        "providerUrl": "http://localhost/fake",
                                        "nativeSymbol": "ETH",
                                    }
                                },
                                "selectedProfile": {
                                    "chainId": outer.chain_id,
                                    "providerUrl": "http://localhost/fake",
                                    "nativeSymbol": "ETH",
                                },
                            },
                        },
                    )
                    return
                self._send(404, {"ok": False, "error": "Not Found"})

            def do_POST(self) -> None:  # noqa: N802
                if not self._authorized():
                    self._send(401, {"ok": False, "error": "Unauthorized."})
                    return
                body = self._read_json()
                wallet_id = str(body.get("walletId") or "").strip()
                requested_network = str(body.get("network") or outer.network)
                requested_chain_id = outer.chain_id_for(requested_network)

                if self.path == "/v1/evm/wallets/get":
                    if wallet_id != outer.wallet_id:
                        self._send(400, {"ok": False, "error": "Unknown walletId."})
                        return
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "walletId": outer.wallet_id,
                                "label": "Agent EVM Wallet",
                                "network": outer.network,
                                "source": "created",
                                "createdAt": "2026-03-25T00:00:00Z",
                                "updatedAt": "2026-03-25T00:00:00Z",
                            },
                        },
                    )
                    return

                if self.path == "/v1/evm/wallets/create":
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "walletId": outer.wallet_id,
                                "label": str(body.get("label") or "Agent EVM Wallet"),
                                "network": str(body.get("network") or outer.network),
                                "source": "created",
                                "createdAt": "2026-03-25T00:00:00Z",
                                "updatedAt": "2026-03-25T00:00:00Z",
                                "unlocked": True,
                                "unlockExpiresAt": None,
                                **(
                                    {
                                        "seedPhrase": (
                                            "abandon abandon abandon abandon abandon abandon "
                                            "abandon abandon abandon abandon abandon about"
                                        )
                                    }
                                    if body.get("revealSeedPhrase")
                                    else {}
                                ),
                            },
                        },
                    )
                    return

                if self.path == "/v1/evm/wallets/import":
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "walletId": outer.wallet_id,
                                "label": str(body.get("label") or "Agent EVM Wallet"),
                                "network": str(body.get("network") or outer.network),
                                "source": "imported",
                                "createdAt": "2026-03-25T00:00:00Z",
                                "updatedAt": "2026-03-25T00:00:00Z",
                                "unlocked": True,
                                "unlockExpiresAt": None,
                            },
                        },
                    )
                    return

                if self.path == "/v1/evm/wallets/unlock":
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "walletId": outer.wallet_id,
                                "label": "Agent EVM Wallet",
                                "unlocked": True,
                                "unlockExpiresAt": None,
                            },
                        },
                    )
                    return

                if self.path == "/v1/evm/wallets/lock":
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

                if self.path == "/v1/evm/address/resolve":
                    if wallet_id != outer.wallet_id:
                        self._send(400, {"ok": False, "error": "Wallet is locked."})
                        return
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "address": outer.address,
                                "network": requested_network,
                                "chainId": requested_chain_id,
                            },
                        },
                    )
                    return

                if self.path == "/v1/evm/balance/get":
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "address": outer.address,
                                "network": requested_network,
                                "chainId": requested_chain_id,
                                "nativeSymbol": "ETH",
                                "balance": "1230000000000000000",
                                "balanceFormatted": "1.23",
                            },
                        },
                    )
                    return

                if self.path == "/v1/evm/token-balance/get":
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "address": outer.address,
                                "network": requested_network,
                                "chainId": requested_chain_id,
                                "tokenAddress": str(body.get("tokenAddress") or outer.token),
                                "balance": "42000000",
                            },
                        },
                    )
                    return

                if self.path == "/v1/evm/fee-rates/get":
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "network": requested_network,
                                "chainId": requested_chain_id,
                                "gasPrice": "1200000000",
                                "feeRates": {
                                    "slow": "1200000000",
                                    "normal": "2000000000",
                                    "fast": "3000000000",
                                    "baseFeePerGas": "1000000000",
                                    "maxPriorityFeePerGas": "1000000000",
                                },
                            },
                        },
                    )
                    return

                if self.path == "/v1/evm/transaction/receipt/get":
                    tx_hash = str(body.get("txHash") or "").strip() or "0x" + "a" * 64
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "network": requested_network,
                                "chainId": requested_chain_id,
                                "txHash": tx_hash,
                                "found": True,
                                "receipt": {
                                    "transactionHash": tx_hash,
                                    "status": "0x1",
                                    "blockNumber": "0x10",
                                },
                            },
                        },
                    )
                    return

                if self.path == "/v1/evm/transfer/quote":
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "network": requested_network,
                                "chainId": requested_chain_id,
                                "quote": {
                                    "fee": "21000000000000",
                                    "gasLimit": "21000",
                                },
                            },
                        },
                    )
                    return

                if self.path == "/v1/evm/transfer/send":
                    outer.sent_payloads.append(body)
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "network": requested_network,
                                "chainId": requested_chain_id,
                                "result": {
                                    "hash": "0x" + "b" * 64,
                                    "fee": "21000000000000",
                                },
                            },
                        },
                    )
                    return

                if self.path == "/v1/evm/token-transfer/quote":
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "network": requested_network,
                                "chainId": requested_chain_id,
                                "quote": {
                                    "fee": "45000000000000",
                                    "gasLimit": "65000",
                                },
                            },
                        },
                    )
                    return

                if self.path == "/v1/evm/token-transfer/send":
                    outer.sent_payloads.append(body)
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "network": requested_network,
                                "chainId": requested_chain_id,
                                "result": {
                                    "hash": "0x" + "c" * 64,
                                    "fee": "45000000000000",
                                },
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
