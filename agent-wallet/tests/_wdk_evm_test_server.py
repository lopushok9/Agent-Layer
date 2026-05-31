"""Small fake local HTTP server for wdk-evm-wallet integration tests."""

from __future__ import annotations

import json
import threading
import time
from contextlib import AbstractContextManager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class FakeWdkEvmWalletServer(AbstractContextManager["FakeWdkEvmWalletServer"]):
    wallet_id = "evm-wallet-123"

    def __init__(
        self,
        network: str = "ethereum",
        host: str = "127.0.0.1",
        port: int = 0,
        auth_token: str = "test-local-evm-token",
        error_responses: dict[str, dict[str, Any]] | None = None,
        response_delays: dict[str, float] | None = None,
        start_empty: bool = False,
    ):
        self.network = network
        self.host = host
        self.port = int(port)
        self.auth_token = str(auth_token).strip()
        self.error_responses = dict(error_responses or {})
        self.response_delays = {
            str(key): float(value) for key, value in (response_delays or {}).items()
        }
        self.address = "0x1111111111111111111111111111111111111111"
        self.token = "0x2222222222222222222222222222222222222222"
        self.sent_payloads: list[dict[str, Any]] = []
        self.unlocked_wallet_ids: set[str] = set()
        # When start_empty is True the vault reports no wallets until one is created,
        # so the auto-provision (create + auto-generate password) path is exercised.
        self.wallet_exists = not bool(start_empty)
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
            "base": 8453,
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
                delay = outer.response_delays.get(f"GET {self.path}")
                if delay and delay > 0:
                    time.sleep(delay)
                error_config = outer.error_responses.get(f"GET {self.path}")
                if error_config is not None:
                    self._send(
                        int(error_config.get("status", 400)),
                        dict(error_config.get("payload") or {}),
                    )
                    return
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
                            "data": (
                                [
                                    {
                                        "walletId": outer.wallet_id,
                                        "label": "Agent EVM Wallet",
                                        "network": outer.network,
                                        "source": "created",
                                        "unlocked": outer.wallet_id in outer.unlocked_wallet_ids,
                                        "unlockExpiresAt": None,
                                    }
                                ]
                                if outer.wallet_exists
                                else []
                            ),
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
                delay = outer.response_delays.get(f"POST {self.path}")
                if delay and delay > 0:
                    time.sleep(delay)
                error_config = outer.error_responses.get(f"POST {self.path}")
                if error_config is not None:
                    self._send(
                        int(error_config.get("status", 400)),
                        dict(error_config.get("payload") or {}),
                    )
                    return
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
                                "unlocked": outer.wallet_id in outer.unlocked_wallet_ids,
                                "unlockExpiresAt": None if outer.wallet_id in outer.unlocked_wallet_ids else None,
                            },
                        },
                    )
                    return

                if self.path == "/v1/evm/x402/exact/sign":
                    if wallet_id != outer.wallet_id:
                        self._send(400, {"ok": False, "error": "Unknown walletId."})
                        return
                    outer.sent_payloads.append({"path": self.path, "body": body})
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "network": requested_network,
                                "chainId": requested_chain_id,
                                "accountIndex": int(body.get("accountIndex") or 0),
                                "address": outer.address,
                                "primaryType": body.get("primaryType"),
                                "signature": "0x" + ("11" * 65),
                                "source": "wdk-wallet-evm",
                            },
                        },
                    )
                    return

                if self.path == "/v1/evm/wallets/create":
                    outer.wallet_exists = True
                    outer.unlocked_wallet_ids.add(outer.wallet_id)
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
                    outer.unlocked_wallet_ids.add(outer.wallet_id)
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
                    if wallet_id != outer.wallet_id:
                        self._send(400, {"ok": False, "error": "Unknown walletId."})
                        return
                    outer.unlocked_wallet_ids.add(wallet_id)
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
                    if wallet_id != outer.wallet_id:
                        self._send(400, {"ok": False, "error": "Unknown walletId."})
                        return
                    outer.unlocked_wallet_ids.discard(wallet_id)
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
                    if wallet_id != outer.wallet_id or wallet_id not in outer.unlocked_wallet_ids:
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
                    if wallet_id != outer.wallet_id or wallet_id not in outer.unlocked_wallet_ids:
                        self._send(
                            400,
                            {
                                "ok": False,
                                "error": "Wallet is locked.",
                                "error_code": "wallet_locked",
                            },
                        )
                        return
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
                    if wallet_id != outer.wallet_id or wallet_id not in outer.unlocked_wallet_ids:
                        self._send(
                            400,
                            {
                                "ok": False,
                                "error": "Wallet is locked.",
                                "error_code": "wallet_locked",
                            },
                        )
                        return
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
                                "balanceFormatted": "42",
                                "tokenMetadata": {
                                    "address": str(body.get("tokenAddress") or outer.token),
                                    "name": "USD Coin",
                                    "symbol": "USDC",
                                    "decimals": 6,
                                    "verified": False,
                                    "source": "erc20-rpc",
                                },
                            },
                        },
                    )
                    return

                if self.path == "/v1/evm/token-metadata/get":
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "network": requested_network,
                                "chainId": requested_chain_id,
                                "tokenAddress": str(body.get("tokenAddress") or outer.token),
                                "tokenMetadata": {
                                    "address": str(body.get("tokenAddress") or outer.token),
                                    "name": "USD Coin",
                                    "symbol": "USDC",
                                    "decimals": 6,
                                    "verified": False,
                                    "source": "erc20-rpc",
                                },
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

                if self.path == "/v1/evm/swap/quote":
                    if wallet_id != outer.wallet_id or wallet_id not in outer.unlocked_wallet_ids:
                        self._send(
                            400,
                            {
                                "ok": False,
                                "error": "Wallet is locked.",
                                "error_code": "wallet_locked",
                            },
                        )
                        return
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "network": requested_network,
                                "chainId": requested_chain_id,
                                "address": outer.address,
                                "protocol": "velora",
                                "executionSupported": True,
                                "quoteFingerprint": "evm-swap-fingerprint-1",
                                "estimatedFeeWei": "67000000000000",
                                "estimatedSwapFeeWei": "39000000000000",
                                "estimatedApprovalFeeWei": "28000000000000",
                                "router": "0x4444444444444444444444444444444444444444",
                                "allowance": {
                                    "spender": "0x5555555555555555555555555555555555555555",
                                    "currentAllowance": "0",
                                    "requiredAllowance": str(body.get("tokenInAmount") or "1000000"),
                                    "approvalRequired": True,
                                    "approvalSequence": [
                                        {
                                            "type": "approve",
                                            "amount": str(body.get("tokenInAmount") or "1000000"),
                                            "estimatedFeeWei": "28000000000000",
                                        }
                                    ],
                                },
                                "simulation": {
                                    "ok": None,
                                    "skipped": True,
                                    "reason": "allowance_required",
                                },
                                "swapTransaction": {
                                    "to": "0x4444444444444444444444444444444444444444",
                                    "value": "0",
                                    "dataHash": "swap-data-hash-1",
                                },
                                "swapRequest": {
                                    "tokenIn": str(body.get("tokenIn") or outer.token),
                                    "tokenOut": "0x3333333333333333333333333333333333333333",
                                    "tokenInAmount": str(body.get("tokenInAmount") or "1000000"),
                                },
                                "tokenInMetadata": {
                                    "address": str(body.get("tokenIn") or outer.token),
                                    "name": "USD Coin",
                                    "symbol": "USDC",
                                    "decimals": 6,
                                    "verified": False,
                                    "source": "erc20-rpc",
                                },
                                "tokenOutMetadata": {
                                    "address": "0x3333333333333333333333333333333333333333",
                                    "name": "Tether USD",
                                    "symbol": "USDT",
                                    "decimals": 6,
                                    "verified": False,
                                    "source": "erc20-rpc",
                                },
                                "inputAmountFormatted": "1",
                                "outputAmountFormatted": "0.995",
                                "quote": {
                                    "tokenInAmount": str(body.get("tokenInAmount") or "1000000"),
                                    "tokenOutAmount": "995000",
                                    "route": "fake-velora-route",
                                },
                            },
                        },
                    )
                    return

                if self.path == "/v1/evm/swap/send":
                    if wallet_id != outer.wallet_id or wallet_id not in outer.unlocked_wallet_ids:
                        self._send(
                            400,
                            {
                                "ok": False,
                                "error": "Wallet is locked.",
                                "error_code": "wallet_locked",
                            },
                        )
                        return
                    outer.sent_payloads.append(body)
                    self._send(
                        200,
                        {
                            "ok": True,
                            "data": {
                                "network": requested_network,
                                "chainId": requested_chain_id,
                                "address": outer.address,
                                "protocol": "velora",
                                "executionSupported": True,
                                "quoteFingerprint": str(
                                    body.get("expectedQuoteFingerprint") or "evm-swap-fingerprint-1"
                                ),
                                "estimatedFeeWei": "39000000000000",
                                "estimatedSwapFeeWei": "39000000000000",
                                "estimatedApprovalFeeWei": "0",
                                "router": "0x4444444444444444444444444444444444444444",
                                "allowance": {
                                    "spender": "0x5555555555555555555555555555555555555555",
                                    "currentAllowance": str(body.get("tokenInAmount") or "1000000"),
                                    "requiredAllowance": str(body.get("tokenInAmount") or "1000000"),
                                    "approvalRequired": False,
                                    "approvalSequence": [],
                                },
                                "simulation": {
                                    "ok": True,
                                    "skipped": False,
                                    "reason": None,
                                },
                                "swapTransaction": {
                                    "to": "0x4444444444444444444444444444444444444444",
                                    "value": "0",
                                    "dataHash": "swap-data-hash-1",
                                },
                                "swapRequest": {
                                    "tokenIn": str(body.get("tokenIn") or outer.token),
                                    "tokenOut": "0x3333333333333333333333333333333333333333",
                                    "tokenInAmount": str(body.get("tokenInAmount") or "1000000"),
                                },
                                "tokenInMetadata": {
                                    "address": str(body.get("tokenIn") or outer.token),
                                    "name": "USD Coin",
                                    "symbol": "USDC",
                                    "decimals": 6,
                                    "verified": False,
                                    "source": "erc20-rpc",
                                },
                                "tokenOutMetadata": {
                                    "address": "0x3333333333333333333333333333333333333333",
                                    "name": "Tether USD",
                                    "symbol": "USDT",
                                    "decimals": 6,
                                    "verified": False,
                                    "source": "erc20-rpc",
                                },
                                "inputAmountFormatted": "1",
                                "outputAmountFormatted": "0.995",
                                "result": {
                                    "hash": "0x" + "d" * 64,
                                    "fee": "39000000000000",
                                    "swapFee": "39000000000000",
                                    "approvalFee": "0",
                                    "tokenInAmount": str(body.get("tokenInAmount") or "1000000"),
                                    "tokenOutAmount": "995000",
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
                                "tokenMetadata": {
                                    "address": str(body.get("tokenAddress") or outer.token),
                                    "name": "USD Coin",
                                    "symbol": "USDC",
                                    "decimals": 6,
                                    "verified": False,
                                    "source": "erc20-rpc",
                                },
                                "amountFormatted": "5",
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
                                "tokenMetadata": {
                                    "address": str(body.get("tokenAddress") or outer.token),
                                    "name": "USD Coin",
                                    "symbol": "USDC",
                                    "decimals": 6,
                                    "verified": False,
                                    "source": "erc20-rpc",
                                },
                                "amountFormatted": "5",
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
