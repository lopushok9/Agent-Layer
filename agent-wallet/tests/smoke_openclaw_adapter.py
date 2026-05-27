"""Basic smoke test for the OpenClaw wallet adapter without external RPC."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _secret_test_utils import install_test_sealed_secrets
from agent_wallet.approval import issue_approval_token
from agent_wallet.exceptions import ProviderError
from agent_wallet.openclaw_adapter import OpenClawWalletAdapter, preview_payload_digest
from agent_wallet.plugin_bundle import build_openclaw_plugin_bundle
from agent_wallet.providers import jupiter, x402
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletCapabilities
from agent_wallet.wallet_layer.solana import SolanaWalletBackend


class FakeBackend(AgentWalletBackend):
    name = "fake_wallet"
    network = "devnet"

    async def get_address(self) -> str | None:
        return "Fake11111111111111111111111111111111111111111"

    async def get_balance(self, address: str | None = None) -> dict:
        return {
            "address": address or "Fake11111111111111111111111111111111111111111",
            "chain": "solana",
            "balance_native": 1.25,
            "balance_usd": "25.50",
            "native_value_usd": "25.00",
            "tokens": [
                {
                    "mint": "FakeMint111111111111111111111111111111111111",
                    "amount_ui": 0.5,
                    "price_usd": "1",
                    "value_usd": "0.50",
                }
            ],
            "token_count": 1,
            "assets": [
                {"asset_type": "native", "symbol": "SOL", "amount_ui": 1.25, "value_usd": "25.00"},
                {"asset_type": "spl-token", "mint": "FakeMint111111111111111111111111111111111111", "amount_ui": 0.5, "value_usd": "0.50"},
            ],
            "asset_count": 2,
            "total_value_usd": "25.50",
            "source": "fake",
        }

    async def get_portfolio(self, address: str | None = None) -> dict:
        return {
            "chain": "solana",
            "network": "devnet",
            "address": address or "Fake11111111111111111111111111111111111111111",
            "native_balance": {
                "address": address or "Fake11111111111111111111111111111111111111111",
                "chain": "solana",
                "balance_native": 1.25,
                "balance_usd": None,
                "source": "fake",
            },
            "tokens": [
                {
                    "mint": "So11111111111111111111111111111111111111112",
                    "token_account": "FakeAta1111111111111111111111111111111111111",
                    "owner": address or "Fake11111111111111111111111111111111111111111",
                    "amount_raw": "5000000",
                    "amount_ui": 0.005,
                    "decimals": 9,
                    "is_native": True,
                    "state": "initialized",
                }
            ],
            "token_count": 1,
            "source": "fake",
        }

    async def get_token_prices(self, mints: list[str]) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "requested_mints": mints,
            "count": len(mints),
            "prices": [
                {
                    "mint": mint,
                    "price": 123.45,
                    "raw": {"usdPrice": 123.45},
                }
                for mint in mints
            ],
            "source": "jupiter",
        }

    async def get_lifi_supported_chains(self) -> dict:
        return {
            "provider": "lifi",
            "chain": "cross-chain",
            "network": "mainnet",
            "chain_count": 3,
            "chains": [
                {"chain_id": "1", "name": "Ethereum"},
                {"chain_id": "8453", "name": "Base"},
                {"chain_id": "1151111081099710", "name": "Solana"},
            ],
            "source": "lifi",
        }

    async def get_lifi_quote(
        self,
        *,
        from_chain: str,
        to_chain: str,
        from_token: str,
        to_token: str,
        amount_in_raw: str,
        from_address: str | None = None,
        to_address: str | None = None,
        slippage: float | int | None = None,
        allow_bridges: list[str] | None = None,
        deny_bridges: list[str] | None = None,
        prefer_bridges: list[str] | None = None,
    ) -> dict:
        return {
            "provider": "lifi",
            "chain": "cross-chain",
            "network": "mainnet",
            "from_chain": from_chain,
            "to_chain": to_chain,
            "from_token": from_token,
            "to_token": to_token,
            "amount_in_raw": amount_in_raw,
            "from_address": from_address or "FakeSolanaAddress111111111111111111111111111",
            "to_address": to_address,
            "slippage": slippage,
            "allow_bridges": allow_bridges,
            "deny_bridges": deny_bridges,
            "prefer_bridges": prefer_bridges,
            "tool": "relay",
            "estimate": {"toAmount": "995000", "toAmountMin": "985000"},
            "transaction_request": {"to": "0xrouter", "data": "0x"},
            "quote": {"tool": "relay"},
            "source": "lifi",
        }

    async def get_lifi_transfer_status(
        self,
        *,
        tx_hash: str,
        bridge: str | None = None,
        from_chain: str | None = None,
        to_chain: str | None = None,
    ) -> dict:
        return {
            "provider": "lifi",
            "chain": "cross-chain",
            "network": "mainnet",
            "tx_hash": tx_hash,
            "bridge": bridge,
            "from_chain": from_chain,
            "to_chain": to_chain,
            "status": "DONE",
            "source": "lifi",
        }

    async def preview_solana_lifi_cross_chain_swap(
        self,
        *,
        input_token: str,
        destination_chain: str,
        output_token: str,
        destination_address: str,
        amount_in_raw: str,
        slippage: float | int | None = None,
        allow_bridges: list[str] | None = None,
        deny_bridges: list[str] | None = None,
        prefer_bridges: list[str] | None = None,
    ) -> dict:
        destination_chain_ids = {"ethereum": "1", "1": "1", "base": "8453", "8453": "8453"}
        destination_chain_id = destination_chain_ids.get(destination_chain, destination_chain)
        normalized_input_token = (
            "11111111111111111111111111111111"
            if input_token.lower() in {"native", "sol", "solana"}
            else input_token
        )
        normalized_output_token = (
            "0x0000000000000000000000000000000000000000"
            if output_token.lower() in {"native", "eth", "ethereum"}
            else output_token
        )
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "preview",
            "asset_type": "solana-lifi-cross-chain-swap",
            "owner": "Fake11111111111111111111111111111111111111111",
            "source_chain": "solana",
            "source_chain_id": "1151111081099710",
            "destination_chain": "base" if destination_chain_id == "8453" else "ethereum",
            "destination_chain_id": destination_chain_id,
            "input_token": normalized_input_token,
            "input_mint": normalized_input_token,
            "output_token": normalized_output_token,
            "destination_address": destination_address,
            "input_amount_raw": amount_in_raw,
            "input_amount_ui": 1,
            "estimated_output_amount_raw": "994898",
            "estimated_output_amount_ui": 0.994898,
            "minimum_output_amount_raw": "984949",
            "minimum_output_amount_ui": 0.984949,
            "slippage": slippage,
            "allow_bridges": allow_bridges,
            "deny_bridges": deny_bridges,
            "prefer_bridges": prefer_bridges,
            "quote_type": "lifi",
            "quote_id": "lifi-sol-quote-1",
            "transaction_id": "0xlifitx",
            "tool": "near",
            "transaction_data_hash": "lifi-solana-data-hash-1",
            "fee_summary": {
                "swap_provider": "lifi",
                "tool": "near",
                "quoted_output_includes_route_fees": True,
            },
            "swap_provider": "lifi",
            "can_send": True,
            "sign_only": False,
            "source": "lifi",
        }

    async def execute_solana_lifi_cross_chain_swap(
        self,
        *,
        input_token: str,
        destination_chain: str,
        output_token: str,
        destination_address: str,
        amount_in_raw: str,
        slippage: float | int | None = None,
        allow_bridges: list[str] | None = None,
        deny_bridges: list[str] | None = None,
        prefer_bridges: list[str] | None = None,
        minimum_output_amount_raw: str | None = None,
    ) -> dict:
        if minimum_output_amount_raw and minimum_output_amount_raw != "984949":
            raise AssertionError("minimum_output_amount_raw should be bound from preview")
        preview = await self.preview_solana_lifi_cross_chain_swap(
            input_token=input_token,
            destination_chain=destination_chain,
            output_token=output_token,
            destination_address=destination_address,
            amount_in_raw=amount_in_raw,
            slippage=slippage,
            allow_bridges=allow_bridges,
            deny_bridges=deny_bridges,
            prefer_bridges=prefer_bridges,
        )
        return {
            **preview,
            "mode": "execute",
            "signature": "LifiSolSig111111111111111111111111111111111111",
            "source_tx_hash": "LifiSolSig111111111111111111111111111111111111",
            "broadcasted": True,
            "confirmed": True,
            "confirmation_status": "confirmed",
            "slot": 12345,
            "simulation": {"err": None},
            "verification": {"verified": True},
            "execute_response": {"signature": "LifiSolSig111111111111111111111111111111111111"},
            "source": "lifi",
        }

    async def get_bags_claimable_positions(self, wallet: str | None = None) -> dict:
        owner = wallet or "Fake11111111111111111111111111111111111111111"
        return {
            "chain": "solana",
            "network": "mainnet",
            "wallet": owner,
            "position_count": 1,
            "positions": [
                {
                    "tokenMint": "FakeMint1111111111111111111111111111111111111",
                    "wallet": owner,
                    "claimableAmount": "12345",
                }
            ],
            "raw": {"positions": [{"tokenMint": "FakeMint1111111111111111111111111111111111111"}]},
            "source": "bags",
        }

    async def get_bags_fee_analytics(
        self,
        token_mint: str,
        *,
        include_claim_events: bool = False,
        mode: str = "offset",
        limit: int | None = None,
        offset: int | None = None,
        from_ts: int | None = None,
        to_ts: int | None = None,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "token_mint": token_mint,
            "lifetime_fees": {"totalFees": "42"},
            "claim_stats": [{"wallet": "Fake11111111111111111111111111111111111111111"}],
            "claim_events": (
                {
                    "events": [
                        {
                            "wallet": "Fake11111111111111111111111111111111111111111",
                            "mode": mode,
                            "limit": limit,
                            "offset": offset,
                            "from": from_ts,
                            "to": to_ts,
                        }
                    ]
                }
                if include_claim_events
                else None
            ),
            "include_claim_events": include_claim_events,
            "source": "bags",
        }

    async def get_staking_validators(
        self,
        limit: int = 20,
        include_delinquent: bool = False,
    ) -> dict:
        validators = [
            {
                "votePubkey": "FakeVote11111111111111111111111111111111111111",
                "nodePubkey": "FakeNode11111111111111111111111111111111111111",
                "commission": 7,
                "activatedStake": 1234567890,
                "status": "current",
            }
        ]
        return {
            "chain": "solana",
            "network": "devnet",
            "limit": limit,
            "include_delinquent": include_delinquent,
            "validator_count": min(limit, len(validators)),
            "validators": validators[:limit],
            "source": "solana-rpc",
        }

    async def get_stake_account(self, stake_account: str) -> dict:
        return {
            "chain": "solana",
            "network": "devnet",
            "stake_account": stake_account,
            "lamports": 1100000000,
            "balance_native": 1.1,
            "rent_exempt_reserve_lamports": 2282880,
            "rent_exempt_reserve_native": 0.00228288,
            "estimated_withdrawable_lamports": 1000000000,
            "estimated_withdrawable_native": 1.0,
            "account_type": "delegated",
            "authorized_staker": "Fake11111111111111111111111111111111111111111",
            "authorized_withdrawer": "Fake11111111111111111111111111111111111111111",
            "lockup": {},
            "delegation": {
                "voter": "FakeVote11111111111111111111111111111111111111",
                "stake": "1000000000",
            },
            "activation": {
                "state": "active",
                "active": 1000000000,
                "inactive": 0,
            },
            "raw_account": {"owner": "Stake11111111111111111111111111111111111111"},
            "source": "solana-rpc",
        }

    async def get_jupiter_portfolio_platforms(self) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "platform_count": 2,
            "platforms": [
                {"id": "jupiter", "name": "Jupiter"},
                {"id": "sanctum", "name": "Sanctum"},
            ],
            "raw": {"platforms": [{"id": "jupiter"}, {"id": "sanctum"}]},
            "source": "jupiter-portfolio",
        }

    async def get_jupiter_portfolio(
        self,
        address: str | None = None,
        platforms: list[str] | None = None,
    ) -> dict:
        owner = address or "Fake11111111111111111111111111111111111111111"
        return {
            "chain": "solana",
            "network": "mainnet",
            "address": owner,
            "platforms": platforms or [],
            "position_count": 1,
            "positions": [
                {
                    "owner": owner,
                    "platform": "sanctum",
                    "positionType": "staking",
                }
            ],
            "raw": {"positions": [{"owner": owner, "platform": "sanctum"}]},
            "source": "jupiter-portfolio",
        }

    async def get_jupiter_staked_jup(self, address: str | None = None) -> dict:
        owner = address or "Fake11111111111111111111111111111111111111111"
        return {
            "chain": "solana",
            "network": "mainnet",
            "address": owner,
            "raw": {"address": owner, "stakedAmount": "123456"},
            "source": "jupiter-portfolio",
        }

    async def get_jupiter_earn_tokens(self) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "token_count": 1,
            "tokens": [
                {
                    "asset": "So11111111111111111111111111111111111111112",
                    "symbol": "SOL",
                    "decimals": 9,
                }
            ],
            "raw": {"tokens": [{"asset": "So11111111111111111111111111111111111111112"}]},
            "source": "jupiter-lend",
        }

    async def get_jupiter_earn_positions(self, users: list[str] | None = None) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "users": users or ["Fake11111111111111111111111111111111111111111"],
            "position_count": 1,
            "positions": [
                {
                    "address": "FakeEarnPosition1111111111111111111111111111111",
                    "asset": "So11111111111111111111111111111111111111112",
                    "valueUsd": 100.0,
                }
            ],
            "raw": {"positions": [{"address": "FakeEarnPosition1111111111111111111111111111111"}]},
            "source": "jupiter-lend",
        }

    async def get_jupiter_earn_earnings(
        self,
        user: str | None = None,
        positions: list[str] | None = None,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "user": user or "Fake11111111111111111111111111111111111111111",
            "positions": positions or [],
            "raw": {"totalEarningsUsd": 1.23},
            "source": "jupiter-lend",
        }

    async def get_flash_trade_markets(self, pool_name: str | None = None) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "pool_name": pool_name,
            "market_count": 2,
            "markets": [
                {
                    "pool_name": pool_name or "Crypto.1",
                    "symbol": "SOL",
                    "market_symbol": "SOL",
                    "collateral_symbol": "SOL",
                    "side": "long",
                    "maxLeverage": 100,
                },
                {
                    "pool_name": pool_name or "Crypto.1",
                    "symbol": "SOL",
                    "market_symbol": "SOL",
                    "collateral_symbol": "USDC",
                    "side": "short",
                    "maxLeverage": 100,
                },
            ],
            "raw": {"markets": [{"symbol": "SOL"}]},
            "source": "flash-trade",
        }

    async def get_flash_trade_positions(
        self,
        owner: str | None = None,
        pool_name: str | None = None,
    ) -> dict:
        wallet = owner or "Fake11111111111111111111111111111111111111111"
        return {
            "chain": "solana",
            "network": "mainnet",
            "owner": wallet,
            "pool_name": pool_name,
            "position_count": 1,
            "positions": [
                {
                    "owner": wallet,
                    "poolName": pool_name or "Crypto.1",
                    "symbol": "SOL-PERP",
                    "side": "long",
                    "sizeUsd": "250.00",
                }
            ],
            "raw": {"positions": [{"owner": wallet, "symbol": "SOL-PERP"}]},
            "source": "flash-trade",
        }

    async def preview_flash_trade_open_position(
        self,
        *,
        pool_name: str,
        market_symbol: str,
        collateral_symbol: str,
        collateral_amount_raw: str,
        leverage: str,
        side: str,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "preview",
            "asset_type": "flash-trade-open-position",
            "owner": "Fake11111111111111111111111111111111111111111",
            "pool_name": pool_name,
            "market_symbol": market_symbol,
            "collateral_symbol": collateral_symbol,
            "collateral_amount_raw": collateral_amount_raw,
            "leverage": leverage,
            "side": side,
            "estimated_size_usd": "1250.00",
            "estimated_entry_price": "177.50",
            "estimated_liquidation_price": "161.20",
            "sign_only": False,
            "can_send": True,
            "source": "flash-sdk-bridge",
        }

    async def preview_flash_trade_close_position(
        self,
        *,
        pool_name: str,
        market_symbol: str,
        side: str,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "preview",
            "asset_type": "flash-trade-close-position",
            "owner": "Fake11111111111111111111111111111111111111111",
            "pool_name": pool_name,
            "market_symbol": market_symbol,
            "side": side,
            "position_size_usd": "1250.00",
            "close_amount_raw": "700000000",
            "sign_only": False,
            "can_send": True,
            "source": "flash-sdk-bridge",
        }

    async def prepare_flash_trade_open_position(
        self,
        *,
        pool_name: str,
        market_symbol: str,
        collateral_symbol: str,
        collateral_amount_raw: str,
        leverage: str,
        side: str,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "prepare",
            "asset_type": "flash-trade-open-position",
            "owner": "Fake11111111111111111111111111111111111111111",
            "pool_name": pool_name,
            "market_symbol": market_symbol,
            "collateral_symbol": collateral_symbol,
            "collateral_amount_raw": collateral_amount_raw,
            "leverage": leverage,
            "side": side,
            "estimated_size_usd": "1250.00",
            "transaction_base64": "AQID",
            "transaction_encoding": "base64",
            "transaction_format": "versioned",
            "signed": True,
            "verification": {"verified": True, "wallet_signer_index": 0},
            "source": "flash-sdk-bridge",
        }

    async def prepare_flash_trade_close_position(
        self,
        *,
        pool_name: str,
        market_symbol: str,
        side: str,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "prepare",
            "asset_type": "flash-trade-close-position",
            "owner": "Fake11111111111111111111111111111111111111111",
            "pool_name": pool_name,
            "market_symbol": market_symbol,
            "side": side,
            "position_size_usd": "1250.00",
            "transaction_base64": "AQID",
            "transaction_encoding": "base64",
            "transaction_format": "versioned",
            "signed": True,
            "verification": {"verified": True, "wallet_signer_index": 0},
            "source": "flash-sdk-bridge",
        }

    async def execute_flash_trade_open_position(
        self,
        *,
        pool_name: str,
        market_symbol: str,
        collateral_symbol: str,
        collateral_amount_raw: str,
        leverage: str,
        side: str,
        approved_preview: dict | None = None,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "execute",
            "asset_type": "flash-trade-open-position",
            "owner": "Fake11111111111111111111111111111111111111111",
            "pool_name": pool_name,
            "market_symbol": market_symbol,
            "collateral_symbol": collateral_symbol,
            "collateral_amount_raw": collateral_amount_raw,
            "leverage": leverage,
            "side": side,
            "signature": "FakeFlashOpenSignature1111111111111111111111111111",
            "broadcasted": True,
            "confirmed": True,
            "confirmation_status": "confirmed",
            "source": "flash-sdk-bridge",
        }

    async def execute_flash_trade_close_position(
        self,
        *,
        pool_name: str,
        market_symbol: str,
        side: str,
        approved_preview: dict | None = None,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "execute",
            "asset_type": "flash-trade-close-position",
            "owner": "Fake11111111111111111111111111111111111111111",
            "pool_name": pool_name,
            "market_symbol": market_symbol,
            "side": side,
            "signature": "FakeFlashCloseSignature111111111111111111111111111",
            "broadcasted": True,
            "confirmed": True,
            "confirmation_status": "confirmed",
            "source": "flash-sdk-bridge",
        }

    async def get_kamino_lend_markets(self) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "market_count": 1,
            "markets": [
                {
                    "lendingMarket": "FakeKaminoMarket111111111111111111111111111111",
                    "name": "Main Market",
                    "isPrimary": True,
                }
            ],
            "raw": {
                "markets": [
                    {
                        "lendingMarket": "FakeKaminoMarket111111111111111111111111111111",
                        "name": "Main Market",
                    }
                ]
            },
            "source": "kamino",
        }

    async def get_kamino_lend_market_reserves(self, market: str) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "market": market,
            "reserve_count": 1,
            "reserves": [
                {
                    "reserve": "FakeKaminoReserve1111111111111111111111111111",
                    "liquidityToken": "USDC",
                    "supplyApy": "0.05",
                }
            ],
            "raw": {"reserves": [{"reserve": "FakeKaminoReserve1111111111111111111111111111"}]},
            "source": "kamino",
        }

    async def get_kamino_lend_user_obligations(
        self,
        market: str,
        user: str | None = None,
    ) -> dict:
        owner = user or "Fake11111111111111111111111111111111111111111"
        return {
            "chain": "solana",
            "network": "mainnet",
            "market": market,
            "user": owner,
            "obligation_count": 1,
            "obligations": [
                {
                    "obligationAddress": "FakeKaminoObligation11111111111111111111111",
                    "state": {
                        "owner": owner,
                        "deposits": [
                            {
                                "depositReserve": "FakeKaminoReserve1111111111111111111111111111",
                                "depositedAmount": "1000",
                            }
                        ],
                        "borrows": [
                            {
                                "borrowReserve": "FakeKaminoReserve1111111111111111111111111111",
                                "borrowedAmountSf": "500",
                            }
                        ],
                    },
                }
            ],
            "raw": {"obligations": [{"obligationAddress": "FakeKaminoObligation11111111111111111111111"}]},
            "source": "kamino",
        }

    async def get_kamino_lend_user_rewards(self, user: str | None = None) -> dict:
        owner = user or "Fake11111111111111111111111111111111111111111"
        return {
            "chain": "solana",
            "network": "mainnet",
            "user": owner,
            "reward_count": 1,
            "rewards": [{"symbol": "KMNO", "amount": "1.23"}],
            "avg_base_apy": "0.04",
            "avg_boosted_apy": "0.05",
            "avg_max_apy": "0.06",
            "raw": {"rewards": [{"symbol": "KMNO"}]},
            "source": "kamino",
        }

    def get_capabilities(self) -> WalletCapabilities:
        return WalletCapabilities(
            backend=self.name,
            chain="solana",
            custody_model="local",
            sign_only=False,
            has_signer=True,
            can_sign_message=True,
            can_sign_transaction=True,
            can_send_transaction=True,
        )

    async def sign_message(self, message: bytes | str) -> str:
        if isinstance(message, bytes):
            return message.hex()
        return message.encode("utf-8").hex()

    async def preview_native_transfer(
        self,
        recipient: str,
        amount_native: float,
    ) -> dict:
        return {
            "chain": "solana",
            "mode": "preview",
            "from_address": "Fake11111111111111111111111111111111111111111",
            "to_address": recipient,
            "amount_native": amount_native,
            "estimated_fee_native": 0.000005,
            "estimated_balance_native_after": 1.0,
            "sign_only": False,
            "can_send": True,
            "source": "fake",
        }

    async def send_native_transfer(
        self,
        recipient: str,
        amount_native: float,
    ) -> dict:
        return {
            "chain": "solana",
            "mode": "execute",
            "from_address": "Fake11111111111111111111111111111111111111111",
            "to_address": recipient,
            "amount_native": amount_native,
            "signature": "fake-signature",
            "broadcasted": True,
            "confirmed": True,
            "confirmation_status": "confirmed",
            "slot": 123,
            "sign_only": False,
            "source": "fake",
        }

    async def prepare_native_transfer(
        self,
        recipient: str,
        amount_native: float,
    ) -> dict:
        return {
            "chain": "solana",
            "mode": "prepare",
            "from_address": "Fake11111111111111111111111111111111111111111",
            "to_address": recipient,
            "amount_native": amount_native,
            "amount_lamports": 250000000,
            "estimated_fee_native": 0.000005,
            "transaction_base64": "ZmFrZS10eA==",
            "transaction_encoding": "base64",
            "transaction_format": "legacy",
            "signed": True,
            "broadcasted": False,
            "confirmed": False,
            "sign_only": False,
            "source": "fake",
        }

    async def preview_native_stake(
        self,
        vote_account: str,
        amount_native: float,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "devnet",
            "mode": "preview",
            "asset_type": "native-stake",
            "owner": "Fake11111111111111111111111111111111111111111",
            "stake_account_address": None,
            "vote_account": vote_account,
            "validator": {"votePubkey": vote_account, "commission": 7},
            "amount_native": amount_native,
            "stake_lamports": 1000000000,
            "rent_exempt_lamports": 2282880,
            "total_lamports": 1002282880,
            "estimated_fee_lamports": 10000,
            "estimated_fee_native": 0.00001,
            "balance_native_before": 5.0,
            "estimated_balance_native_after": 3.99,
            "latest_blockhash": "FakeBlockhash11111111111111111111111111111111",
            "last_valid_block_height": 12345,
            "sign_only": False,
            "can_send": True,
            "source": "solana-rpc",
        }

    async def prepare_native_stake(
        self,
        vote_account: str,
        amount_native: float,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "devnet",
            "mode": "prepare",
            "asset_type": "native-stake",
            "owner": "Fake11111111111111111111111111111111111111111",
            "stake_account_address": "FakeStake1111111111111111111111111111111111111",
            "vote_account": vote_account,
            "amount_native": amount_native,
            "stake_lamports": 1000000000,
            "rent_exempt_lamports": 2282880,
            "total_lamports": 1002282880,
            "estimated_fee_lamports": 10000,
            "validator": {"votePubkey": vote_account, "commission": 7},
            "transaction_base64": "ZmFrZS1zdGFrZS10eA==",
            "transaction_encoding": "base64",
            "transaction_format": "legacy",
            "signed": True,
            "broadcasted": False,
            "confirmed": False,
            "latest_blockhash": "FakeBlockhash11111111111111111111111111111111",
            "last_valid_block_height": 12345,
            "sign_only": False,
            "source": "solana-rpc",
        }

    async def execute_native_stake(
        self,
        vote_account: str,
        amount_native: float,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "devnet",
            "mode": "execute",
            "asset_type": "native-stake",
            "owner": "Fake11111111111111111111111111111111111111111",
            "stake_account_address": "FakeStake1111111111111111111111111111111111111",
            "vote_account": vote_account,
            "amount_native": amount_native,
            "stake_lamports": 1000000000,
            "rent_exempt_lamports": 2282880,
            "total_lamports": 1002282880,
            "signature": "fake-stake-signature",
            "broadcasted": True,
            "confirmed": True,
            "confirmation_status": "confirmed",
            "slot": 1100,
            "sign_only": False,
            "source": "solana-rpc",
        }

    async def preview_spl_transfer(
        self,
        recipient: str,
        mint: str,
        amount_ui: float,
        decimals: int | None = None,
    ) -> dict:
        return {
            "chain": "solana",
            "mode": "preview",
            "asset_type": "spl",
            "from_address": "Fake11111111111111111111111111111111111111111",
            "to_address": recipient,
            "mint": mint,
            "amount_ui": amount_ui,
            "amount_raw": 250000,
            "decimals": 6 if decimals is None else decimals,
            "sender_token_account": "FakeSenderAta111111111111111111111111111111",
            "recipient_token_account": "FakeRecipientAta1111111111111111111111111111",
            "recipient_token_account_exists": False,
            "sign_only": False,
            "can_send": True,
            "source": "fake",
        }

    async def send_spl_transfer(
        self,
        recipient: str,
        mint: str,
        amount_ui: float,
        decimals: int | None = None,
    ) -> dict:
        return {
            "chain": "solana",
            "mode": "execute",
            "asset_type": "spl",
            "from_address": "Fake11111111111111111111111111111111111111111",
            "to_address": recipient,
            "mint": mint,
            "amount_ui": amount_ui,
            "amount_raw": 250000,
            "decimals": 6 if decimals is None else decimals,
            "sender_token_account": "FakeSenderAta111111111111111111111111111111",
            "recipient_token_account": "FakeRecipientAta1111111111111111111111111111",
            "signature": "fake-spl-signature",
            "broadcasted": True,
            "confirmed": True,
            "confirmation_status": "confirmed",
            "slot": 789,
            "sign_only": False,
            "source": "fake",
        }

    async def prepare_spl_transfer(
        self,
        recipient: str,
        mint: str,
        amount_ui: float,
        decimals: int | None = None,
    ) -> dict:
        return {
            "chain": "solana",
            "mode": "prepare",
            "asset_type": "spl",
            "from_address": "Fake11111111111111111111111111111111111111111",
            "to_address": recipient,
            "mint": mint,
            "token_program_id": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
            "sender_token_account": "FakeSenderAta111111111111111111111111111111",
            "recipient_token_account": "FakeRecipientAta1111111111111111111111111111",
            "recipient_token_account_exists_before": False,
            "recipient_token_account_created": True,
            "amount_ui": amount_ui,
            "amount_raw": 250000,
            "decimals": 6 if decimals is None else decimals,
            "transaction_base64": "ZmFrZS1zcGwtdHg=",
            "transaction_encoding": "base64",
            "transaction_format": "legacy",
            "signed": True,
            "broadcasted": False,
            "confirmed": False,
            "sign_only": False,
            "source": "fake",
        }

    async def preview_swap(
        self,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = 50,
    ) -> dict:
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "preview",
            "asset_type": "swap",
            "owner": "Fake11111111111111111111111111111111111111111",
            "input_mint": input_mint,
            "output_mint": output_mint,
            "input_amount_ui": amount_ui,
            "input_amount_raw": 100000000,
            "estimated_output_amount_ui": 12.34,
            "estimated_output_amount_raw": 12340000,
            "minimum_output_amount_ui": 12.0,
            "minimum_output_amount_raw": 12000000,
            "slippage_bps": slippage_bps,
            "price_impact_pct": "0.01",
            "fee_summary": {
                "swap_provider": "jupiter-ultra",
                "network_fee_lamports": 9000,
                "network_fee_sol": 0.000009,
                "signature_fee_lamports": 5000,
                "prioritization_fee_lamports": 4000,
                "rent_fee_lamports": 0,
                "route_fee_bps": 10,
                "compute_unit_limit": 250000,
                "quoted_output_includes_route_fees": True,
            },
            "estimated_total_fee_label": "network fee ~0.000009 SOL; route fee 10 bps (already reflected in quoted output)",
            "route_plan": [{"swapInfo": {"label": "fake-route"}}],
            "sign_only": False,
            "can_send": True,
            "quote_response": {"routePlan": [{"swapInfo": {"label": "fake-route"}}]},
            "source": "fake",
        }

    async def preview_solana_private_swap(
        self,
        *,
        input_token: str,
        output_token: str,
        destination_address: str,
        amount_ui: float,
        use_xmr: bool = False,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "preview",
            "asset_type": "solana-private-swap",
            "owner": "Fake11111111111111111111111111111111111111111",
            "destination_address": destination_address,
            "input_token_id": "houdini-sol-token",
            "output_token_id": "houdini-sol-token",
            "input_token_symbol": "SOL",
            "output_token_symbol": "SOL",
            "input_token_name": "Solana",
            "output_token_name": "Solana",
            "input_token_address": "11111111111111111111111111111111",
            "output_token_address": "11111111111111111111111111111111",
            "input_token_chain": "solana",
            "output_token_chain": "solana",
            "input_token_decimals": 9,
            "output_token_decimals": 9,
            "input_is_native": True,
            "output_is_native": True,
            "input_amount_ui": amount_ui,
            "estimated_output_amount_ui": amount_ui * 0.985,
            "estimated_output_amount_usd": "19.70",
            "input_private_min_ui": 0.01,
            "input_private_max_ui": 100.0,
            "private_duration_minutes": 28,
            "quote_id": "houdini-private-quote-1",
            "quote_type": "private",
            "rewards_available": False,
            "anonymous": True,
            "use_xmr": use_xmr,
            "can_send": True,
            "sign_only": False,
            "source": "houdini",
        }

    async def execute_solana_private_swap(
        self,
        *,
        input_token: str,
        output_token: str,
        destination_address: str,
        amount_ui: float,
        use_xmr: bool = False,
        approved_preview: dict | None = None,
        existing_order: dict | None = None,
    ) -> dict:
        preview = approved_preview or await self.preview_solana_private_swap(
            input_token=input_token,
            output_token=output_token,
            destination_address=destination_address,
            amount_ui=amount_ui,
            use_xmr=use_xmr,
        )
        return {
            **preview,
            "mode": "execute",
            "multi_id": "multi_fake_private_1",
            "houdini_id": "houdini_private_1",
            "deposit_address": "HoudiniDeposit1111111111111111111111111111111",
            "order_status": "CONFIRMING",
            "order": {
                "multiId": "multi_fake_private_1",
                "houdiniId": "houdini_private_1",
                "statusLabel": "CONFIRMING",
                "receiverAddress": destination_address,
                "anonymous": True,
                "depositAddress": "HoudiniDeposit1111111111111111111111111111111",
            },
            "funding_batch_houdini_ids": ["houdini_private_1"],
            "signature": "HoudiniSolSig1111111111111111111111111111111111",
            "broadcasted": True,
            "confirmed": True,
            "confirmation_status": "confirmed",
            "slot": 4567,
            "verification": {"verified": True},
            "simulation": {"verified": True},
            "execute_response": {"signature": "HoudiniSolSig1111111111111111111111111111111111"},
            "status_tracking": {
                "multi_id": "multi_fake_private_1",
                "houdini_id": "houdini_private_1",
                "poll_status_tool": "get_solana_private_swap_status",
            },
            "source": "houdini",
        }

    async def get_solana_private_swap_status(
        self,
        *,
        multi_id: str | None = None,
        houdini_id: str | None = None,
    ) -> dict:
        selected_order = {
            "multiId": multi_id,
            "houdiniId": houdini_id or "houdini_private_1",
            "statusLabel": "ANONYMIZING",
            "receiverAddress": "FakeRecipient1111111111111111111111111111111111",
        }
        return {
            "chain": "solana",
            "network": "mainnet",
            "asset_type": "solana-private-swap",
            "multi_id": multi_id,
            "order_count": 1,
            "orders": [selected_order],
            "selected_order": selected_order,
            "selected_houdini_id": selected_order["houdiniId"],
            "selected_status": selected_order["statusLabel"],
            "all_terminal": False,
            "source": "houdini",
        }

    async def preview_bags_fee_claim(self, token_mint: str) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "preview",
            "asset_type": "bags-fee-claim",
            "owner": "Fake11111111111111111111111111111111111111111",
            "fee_claimer": "Fake11111111111111111111111111111111111111111",
            "token_mint": token_mint,
            "claimable_position_count": 1,
            "claimable_positions": [
                {
                    "tokenMint": token_mint,
                    "claimableAmount": "12345",
                }
            ],
            "sign_only": False,
            "can_send": True,
            "source": "bags",
        }

    async def execute_bags_fee_claim(self, token_mint: str) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "execute",
            "asset_type": "bags-fee-claim",
            "owner": "Fake11111111111111111111111111111111111111111",
            "fee_claimer": "Fake11111111111111111111111111111111111111111",
            "token_mint": token_mint,
            "claimable_position_count": 1,
            "signatures": ["fake-bags-claim-signature"],
            "signature": "fake-bags-claim-signature",
            "broadcasted": True,
            "confirmed": True,
            "confirmation_statuses": ["confirmed"],
            "slots": [1400],
            "source": "bags",
        }

    async def preview_bags_token_launch(
        self,
        *,
        name: str,
        symbol: str,
        description: str,
        base_mint: str,
        claimers: list[str],
        basis_points: list[int],
        initial_buy_sol: float,
        image_url: str | None = None,
        website: str | None = None,
        twitter: str | None = None,
        telegram: str | None = None,
        discord: str | None = None,
        bags_config_type: int | None = None,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "preview",
            "asset_type": "bags-token-launch",
            "owner": "Fake11111111111111111111111111111111111111111",
            "wallet": "Fake11111111111111111111111111111111111111111",
            "token_name": name,
            "token_symbol": symbol,
            "description": description,
            "image_url": image_url,
            "website": website,
            "twitter": twitter,
            "telegram": telegram,
            "discord": discord,
            "base_mint": base_mint,
            "claimers": claimers,
            "basis_points": basis_points,
            "claimers_count": len(claimers),
            "total_basis_points": sum(basis_points),
            "initial_buy_sol": initial_buy_sol,
            "initial_buy_lamports": 10000000,
            "bags_config_type": bags_config_type,
            "sign_only": False,
            "can_send": True,
            "source": "bags",
        }

    async def execute_bags_token_launch(
        self,
        *,
        name: str,
        symbol: str,
        description: str,
        base_mint: str,
        claimers: list[str],
        basis_points: list[int],
        initial_buy_sol: float,
        image_url: str | None = None,
        website: str | None = None,
        twitter: str | None = None,
        telegram: str | None = None,
        discord: str | None = None,
        bags_config_type: int | None = None,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "execute",
            "asset_type": "bags-token-launch",
            "owner": "Fake11111111111111111111111111111111111111111",
            "wallet": "Fake11111111111111111111111111111111111111111",
            "token_mint": "FakeMint1111111111111111111111111111111111111",
            "token_name": name,
            "token_symbol": symbol,
            "base_mint": base_mint,
            "claimers": claimers,
            "basis_points": basis_points,
            "claimers_count": len(claimers),
            "total_basis_points": sum(basis_points),
            "initial_buy_sol": initial_buy_sol,
            "initial_buy_lamports": 10000000,
            "config_key": "fake-config-key",
            "ipfs": "ipfs://fake-launch",
            "signatures": ["fake-bags-launch-signature"],
            "signature": "fake-bags-launch-signature",
            "broadcasted": True,
            "confirmed": True,
            "confirmation_statuses": ["confirmed"],
            "slots": [1401],
            "source": "bags",
        }

    async def preview_close_empty_token_accounts(self, limit: int = 8) -> dict:
        return {
            "chain": "solana",
            "mode": "preview",
            "asset_type": "close_empty_token_accounts",
            "address": "Fake11111111111111111111111111111111111111111",
            "candidate_count": 1,
            "selected_count": 1,
            "accounts": [
                {
                    "mint": "So11111111111111111111111111111111111111112",
                    "token_account": "FakeEmptyAta11111111111111111111111111111111",
                    "token_program_id": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                    "owner": "Fake11111111111111111111111111111111111111111",
                    "close_authority": None,
                    "amount_raw": "0",
                    "amount_ui": 0.0,
                    "decimals": 9,
                    "is_native": False,
                    "state": "initialized",
                }
            ],
            "limit": limit,
            "sign_only": False,
            "can_send": True,
            "source": "fake",
        }

    async def preview_deactivate_stake(self, stake_account: str) -> dict:
        return {
            "chain": "solana",
            "network": "devnet",
            "mode": "preview",
            "asset_type": "deactivate-stake",
            "authority": "Fake11111111111111111111111111111111111111111",
            "stake_account": stake_account,
            "activation": {"state": "active", "active": 1000000000, "inactive": 0},
            "delegation": {"voter": "FakeVote11111111111111111111111111111111111111"},
            "latest_blockhash": "FakeBlockhash11111111111111111111111111111111",
            "last_valid_block_height": 12345,
            "sign_only": False,
            "can_send": True,
            "source": "solana-rpc",
        }

    async def prepare_deactivate_stake(self, stake_account: str) -> dict:
        return {
            "chain": "solana",
            "network": "devnet",
            "mode": "prepare",
            "asset_type": "deactivate-stake",
            "authority": "Fake11111111111111111111111111111111111111111",
            "stake_account": stake_account,
            "transaction_base64": "ZmFrZS1kZWFjdGl2YXRlLXN0YWtlLXR4",
            "transaction_encoding": "base64",
            "transaction_format": "legacy",
            "signed": True,
            "broadcasted": False,
            "confirmed": False,
            "latest_blockhash": "FakeBlockhash11111111111111111111111111111111",
            "last_valid_block_height": 12345,
            "sign_only": False,
            "source": "solana-rpc",
        }

    async def execute_deactivate_stake(self, stake_account: str) -> dict:
        return {
            "chain": "solana",
            "network": "devnet",
            "mode": "execute",
            "asset_type": "deactivate-stake",
            "authority": "Fake11111111111111111111111111111111111111111",
            "stake_account": stake_account,
            "signature": "fake-deactivate-stake-signature",
            "broadcasted": True,
            "confirmed": True,
            "confirmation_status": "confirmed",
            "slot": 1101,
            "sign_only": False,
            "source": "solana-rpc",
        }

    async def preview_withdraw_stake(
        self,
        stake_account: str,
        amount_native: float,
        recipient: str | None = None,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "devnet",
            "mode": "preview",
            "asset_type": "withdraw-stake",
            "authority": "Fake11111111111111111111111111111111111111111",
            "stake_account": stake_account,
            "recipient": recipient or "Fake11111111111111111111111111111111111111111",
            "amount_native": amount_native,
            "amount_lamports": 500000000,
            "activation": {"state": "inactive", "active": 0, "inactive": 1000000000},
            "estimated_withdrawable_lamports": 1000000000,
            "latest_blockhash": "FakeBlockhash11111111111111111111111111111111",
            "last_valid_block_height": 12345,
            "sign_only": False,
            "can_send": True,
            "source": "solana-rpc",
        }

    async def prepare_withdraw_stake(
        self,
        stake_account: str,
        amount_native: float,
        recipient: str | None = None,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "devnet",
            "mode": "prepare",
            "asset_type": "withdraw-stake",
            "authority": "Fake11111111111111111111111111111111111111111",
            "stake_account": stake_account,
            "recipient": recipient or "Fake11111111111111111111111111111111111111111",
            "amount_native": amount_native,
            "amount_lamports": 500000000,
            "transaction_base64": "ZmFrZS13aXRoZHJhdy1zdGFrZS10eA==",
            "transaction_encoding": "base64",
            "transaction_format": "legacy",
            "signed": True,
            "broadcasted": False,
            "confirmed": False,
            "latest_blockhash": "FakeBlockhash11111111111111111111111111111111",
            "last_valid_block_height": 12345,
            "sign_only": False,
            "source": "solana-rpc",
        }

    async def execute_withdraw_stake(
        self,
        stake_account: str,
        amount_native: float,
        recipient: str | None = None,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "devnet",
            "mode": "execute",
            "asset_type": "withdraw-stake",
            "authority": "Fake11111111111111111111111111111111111111111",
            "stake_account": stake_account,
            "recipient": recipient or "Fake11111111111111111111111111111111111111111",
            "amount_native": amount_native,
            "amount_lamports": 500000000,
            "signature": "fake-withdraw-stake-signature",
            "broadcasted": True,
            "confirmed": True,
            "confirmation_status": "confirmed",
            "slot": 1102,
            "sign_only": False,
            "source": "solana-rpc",
        }

    async def close_empty_token_accounts(self, limit: int = 8) -> dict:
        return {
            "chain": "solana",
            "mode": "execute",
            "asset_type": "close_empty_token_accounts",
            "address": "Fake11111111111111111111111111111111111111111",
            "candidate_count": 1,
            "closed_accounts": [
                {
                    "mint": "So11111111111111111111111111111111111111112",
                    "token_account": "FakeEmptyAta11111111111111111111111111111111",
                    "token_program_id": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                    "owner": "Fake11111111111111111111111111111111111111111",
                    "close_authority": None,
                    "amount_raw": "0",
                    "amount_ui": 0.0,
                    "decimals": 9,
                    "is_native": False,
                    "state": "initialized",
                }
            ],
            "signature": "fake-close-signature",
            "broadcasted": True,
            "confirmed": True,
            "confirmation_status": "confirmed",
            "slot": 1001,
            "source": "fake",
        }

    async def execute_swap(
        self,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = 50,
    ) -> dict:
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "execute",
            "asset_type": "swap",
            "owner": "Fake11111111111111111111111111111111111111111",
            "input_mint": input_mint,
            "output_mint": output_mint,
            "input_amount_ui": amount_ui,
            "estimated_output_amount_ui": 12.34,
            "estimated_output_amount_raw": 12340000,
            "minimum_output_amount_ui": 12.0,
            "minimum_output_amount_raw": 12000000,
            "slippage_bps": slippage_bps,
            "price_impact_pct": "0.01",
            "signature": "fake-swap-signature",
            "broadcasted": True,
            "confirmed": True,
            "confirmation_status": "confirmed",
            "slot": 999,
            "fee_summary": {
                "swap_provider": "jupiter-ultra",
                "network_fee_lamports": 9000,
                "network_fee_sol": 0.000009,
                "signature_fee_lamports": 5000,
                "prioritization_fee_lamports": 4000,
                "rent_fee_lamports": 0,
                "route_fee_bps": 10,
                "compute_unit_limit": 250000,
                "quoted_output_includes_route_fees": True,
            },
            "estimated_total_fee_label": "network fee ~0.000009 SOL; route fee 10 bps (already reflected in quoted output)",
            "verification": {
                "wallet_address": "Fake11111111111111111111111111111111111111111",
                "program_ids": ["ComputeBudget111111111111111111111111111111"],
                "non_core_program_ids": [],
                "account_key_count": 3,
                "instruction_count": 1,
                "input_mint": input_mint,
                "output_mint": output_mint,
            },
            "source": "fake",
        }

    async def prepare_swap(
        self,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = 50,
    ) -> dict:
        return {
            "chain": "solana",
            "network": self.network,
            "mode": "prepare",
            "asset_type": "swap",
            "owner": "Fake11111111111111111111111111111111111111111",
            "input_mint": input_mint,
            "output_mint": output_mint,
            "input_amount_ui": amount_ui,
            "input_amount_raw": 100000000,
            "estimated_output_amount_ui": 12.34,
            "minimum_output_amount_ui": 12.0,
            "slippage_bps": slippage_bps,
            "price_impact_pct": "0.01",
            "transaction_base64": "ZmFrZS1zd2FwLXR4",
            "transaction_encoding": "base64",
            "transaction_format": "versioned",
            "signed": True,
            "broadcasted": False,
            "confirmed": False,
            "fee_summary": {
                "swap_provider": "jupiter-ultra",
                "network_fee_lamports": 9000,
                "network_fee_sol": 0.000009,
                "signature_fee_lamports": 5000,
                "prioritization_fee_lamports": 4000,
                "rent_fee_lamports": 0,
                "route_fee_bps": 10,
                "compute_unit_limit": 250000,
                "quoted_output_includes_route_fees": True,
            },
            "estimated_total_fee_label": "network fee ~0.000009 SOL; route fee 10 bps (already reflected in quoted output)",
            "verification": {
                "wallet_address": "Fake11111111111111111111111111111111111111111",
                "program_ids": ["ComputeBudget111111111111111111111111111111"],
                "non_core_program_ids": [],
                "account_key_count": 3,
                "instruction_count": 1,
                "input_mint": input_mint,
                "output_mint": output_mint,
            },
            "source": "fake",
        }

    async def preview_jupiter_earn_deposit(self, asset: str, amount_raw: str) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "preview",
            "asset_type": "jupiter-earn-deposit",
            "owner": "Fake11111111111111111111111111111111111111111",
            "asset": asset,
            "amount_raw": amount_raw,
            "token": {"asset": asset, "symbol": "SOL"},
            "sign_only": False,
            "can_send": True,
            "source": "jupiter-lend",
        }

    async def prepare_jupiter_earn_deposit(self, asset: str, amount_raw: str) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "prepare",
            "asset_type": "jupiter-earn-deposit",
            "owner": "Fake11111111111111111111111111111111111111111",
            "asset": asset,
            "amount_raw": amount_raw,
            "transaction_base64": "ZmFrZS1lYXJuLWRlcG9zaXQtdHg=",
            "transaction_encoding": "base64",
            "transaction_format": "versioned",
            "signed": True,
            "broadcasted": False,
            "confirmed": False,
            "sign_only": False,
            "source": "jupiter-lend",
        }

    async def execute_jupiter_earn_deposit(self, asset: str, amount_raw: str) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "execute",
            "asset_type": "jupiter-earn-deposit",
            "owner": "Fake11111111111111111111111111111111111111111",
            "asset": asset,
            "amount_raw": amount_raw,
            "signature": "fake-earn-deposit-signature",
            "broadcasted": True,
            "confirmed": True,
            "confirmation_status": "confirmed",
            "slot": 1200,
            "sign_only": False,
            "source": "jupiter-lend",
        }

    async def preview_jupiter_earn_withdraw(self, asset: str, amount_raw: str) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "preview",
            "asset_type": "jupiter-earn-withdraw",
            "owner": "Fake11111111111111111111111111111111111111111",
            "asset": asset,
            "amount_raw": amount_raw,
            "positions": [{"address": "FakeEarnPosition1111111111111111111111111111111"}],
            "sign_only": False,
            "can_send": True,
            "source": "jupiter-lend",
        }

    async def prepare_jupiter_earn_withdraw(self, asset: str, amount_raw: str) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "prepare",
            "asset_type": "jupiter-earn-withdraw",
            "owner": "Fake11111111111111111111111111111111111111111",
            "asset": asset,
            "amount_raw": amount_raw,
            "transaction_base64": "ZmFrZS1lYXJuLXdpdGhkcmF3LXR4",
            "transaction_encoding": "base64",
            "transaction_format": "versioned",
            "signed": True,
            "broadcasted": False,
            "confirmed": False,
            "sign_only": False,
            "source": "jupiter-lend",
        }

    async def execute_jupiter_earn_withdraw(self, asset: str, amount_raw: str) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "execute",
            "asset_type": "jupiter-earn-withdraw",
            "owner": "Fake11111111111111111111111111111111111111111",
            "asset": asset,
            "amount_raw": amount_raw,
            "signature": "fake-earn-withdraw-signature",
            "broadcasted": True,
            "confirmed": True,
            "confirmation_status": "confirmed",
            "slot": 1300,
            "sign_only": False,
            "source": "jupiter-lend",
        }

    async def preview_kamino_lend_deposit(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "preview",
            "asset_type": "kamino-lend-deposit",
            "owner": "Fake11111111111111111111111111111111111111111",
            "market": market,
            "reserve": reserve,
            "amount_ui": amount_ui,
            "reserve_info": {"reserve": reserve, "liquidityToken": "USDC"},
            "sign_only": False,
            "can_send": True,
            "source": "kamino",
        }

    async def execute_kamino_lend_deposit(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "execute",
            "asset_type": "kamino-lend-deposit",
            "owner": "Fake11111111111111111111111111111111111111111",
            "market": market,
            "reserve": reserve,
            "amount_ui": amount_ui,
            "signature": "fake-kamino-deposit-signature",
            "broadcasted": True,
            "confirmed": True,
            "confirmation_status": "confirmed",
            "slot": 1310,
            "sign_only": False,
            "source": "kamino",
        }

    async def preview_kamino_lend_withdraw(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "preview",
            "asset_type": "kamino-lend-withdraw",
            "owner": "Fake11111111111111111111111111111111111111111",
            "market": market,
            "reserve": reserve,
            "amount_ui": amount_ui,
            "reserve_info": {"reserve": reserve, "liquidityToken": "USDC"},
            "obligations": [{"obligationAddress": "FakeKaminoObligation11111111111111111111111"}],
            "sign_only": False,
            "can_send": True,
            "source": "kamino",
        }

    async def execute_kamino_lend_withdraw(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "execute",
            "asset_type": "kamino-lend-withdraw",
            "owner": "Fake11111111111111111111111111111111111111111",
            "market": market,
            "reserve": reserve,
            "amount_ui": amount_ui,
            "signature": "fake-kamino-withdraw-signature",
            "broadcasted": True,
            "confirmed": True,
            "confirmation_status": "confirmed",
            "slot": 1311,
            "sign_only": False,
            "source": "kamino",
        }

    async def preview_kamino_lend_borrow(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "preview",
            "asset_type": "kamino-lend-borrow",
            "owner": "Fake11111111111111111111111111111111111111111",
            "market": market,
            "reserve": reserve,
            "amount_ui": amount_ui,
            "reserve_info": {"reserve": reserve, "liquidityToken": "USDC"},
            "obligations": [{"obligationAddress": "FakeKaminoObligation11111111111111111111111"}],
            "sign_only": False,
            "can_send": True,
            "source": "kamino",
        }

    async def execute_kamino_lend_borrow(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "execute",
            "asset_type": "kamino-lend-borrow",
            "owner": "Fake11111111111111111111111111111111111111111",
            "market": market,
            "reserve": reserve,
            "amount_ui": amount_ui,
            "signature": "fake-kamino-borrow-signature",
            "broadcasted": True,
            "confirmed": True,
            "confirmation_status": "confirmed",
            "slot": 1312,
            "sign_only": False,
            "source": "kamino",
        }

    async def preview_kamino_lend_repay(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "preview",
            "asset_type": "kamino-lend-repay",
            "owner": "Fake11111111111111111111111111111111111111111",
            "market": market,
            "reserve": reserve,
            "amount_ui": amount_ui,
            "reserve_info": {"reserve": reserve, "liquidityToken": "USDC"},
            "obligations": [{"obligationAddress": "FakeKaminoObligation11111111111111111111111"}],
            "sign_only": False,
            "can_send": True,
            "source": "kamino",
        }

    async def execute_kamino_lend_repay(
        self,
        market: str,
        reserve: str,
        amount_ui: str,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "execute",
            "asset_type": "kamino-lend-repay",
            "owner": "Fake11111111111111111111111111111111111111111",
            "market": market,
            "reserve": reserve,
            "amount_ui": amount_ui,
            "signature": "fake-kamino-repay-signature",
            "broadcasted": True,
            "confirmed": True,
            "confirmation_status": "confirmed",
            "slot": 1313,
            "sign_only": False,
            "source": "kamino",
        }

    async def request_testnet_airdrop(self, amount_native: float) -> dict:
        return {
            "chain": "solana",
            "network": "devnet",
            "mode": "airdrop",
            "address": "Fake11111111111111111111111111111111111111111",
            "amount_native": amount_native,
            "signature": "fake-airdrop-signature",
            "confirmed": True,
            "confirmation_status": "confirmed",
            "slot": 456,
            "source": "fake",
        }


class DriftingSwapBackend(FakeBackend):
    def __init__(self) -> None:
        self._swap_preview_calls = 0

    async def preview_swap(
        self,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = 50,
    ) -> dict:
        self._swap_preview_calls += 1
        preview = await super().preview_swap(
            input_mint=input_mint,
            output_mint=output_mint,
            amount_ui=amount_ui,
            slippage_bps=slippage_bps,
        )
        if self._swap_preview_calls > 1:
            preview["estimated_output_amount_ui"] = 11.91
            preview["minimum_output_amount_ui"] = 11.58
            preview["route_plan"] = [{"swapInfo": {"label": "drifted-route"}}]
            preview["quote_response"] = {"routePlan": [{"swapInfo": {"label": "drifted-route"}}]}
            preview["estimated_total_fee_label"] = (
                "network fee ~0.000011 SOL; route fee 12 bps (already reflected in quoted output)"
            )
        return preview


class RouteOnlyDriftingSwapBackend(DriftingSwapBackend):
    async def preview_swap(
        self,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = 50,
    ) -> dict:
        self._swap_preview_calls += 1
        preview = await FakeBackend.preview_swap(
            self,
            input_mint=input_mint,
            output_mint=output_mint,
            amount_ui=amount_ui,
            slippage_bps=slippage_bps,
        )
        if self._swap_preview_calls > 1:
            preview["route_plan"] = [{"swapInfo": {"label": "fresh-route-same-minimum"}}]
            preview["quote_response"] = {
                "routePlan": [{"swapInfo": {"label": "fresh-route-same-minimum"}}]
            }
        return preview


class NoRepreviewSwapBackend(FakeBackend):
    def __init__(self) -> None:
        self._swap_preview_calls = 0

    async def preview_swap(
        self,
        input_mint: str,
        output_mint: str,
        amount_ui: float,
        slippage_bps: int = 50,
    ) -> dict:
        self._swap_preview_calls += 1
        if self._swap_preview_calls > 1:
            raise WalletBackendError("execute should use the approved preview payload")
        return await super().preview_swap(
            input_mint=input_mint,
            output_mint=output_mint,
            amount_ui=amount_ui,
            slippage_bps=slippage_bps,
        )


class NoRepreviewFlashBackend(FakeBackend):
    def __init__(self) -> None:
        self._flash_open_preview_calls = 0

    async def preview_flash_trade_open_position(
        self,
        *,
        pool_name: str,
        market_symbol: str,
        collateral_symbol: str,
        collateral_amount_raw: str,
        leverage: str,
        side: str,
    ) -> dict:
        self._flash_open_preview_calls += 1
        if self._flash_open_preview_calls > 1:
            raise WalletBackendError("execute should use the approved Flash preview payload")
        return await super().preview_flash_trade_open_position(
            pool_name=pool_name,
            market_symbol=market_symbol,
            collateral_symbol=collateral_symbol,
            collateral_amount_raw=collateral_amount_raw,
            leverage=leverage,
            side=side,
        )


class MainnetFakeBackend(FakeBackend):
    network = "mainnet"


def _issue_execute_approval(
    *,
    tool_name: str,
    preview: dict,
    network: str,
    mainnet_confirmed: bool = False,
    bind_preview_digest: bool = False,
) -> str:
    summary = dict(preview["confirmation_summary"])
    if bind_preview_digest:
        summary["_preview_digest"] = preview_payload_digest(preview)
    return issue_approval_token(
        tool_name=tool_name,
        network=network,
        summary=summary,
        mainnet_confirmed=mainnet_confirmed,
        ttl_seconds=300,
        issued_by="smoke-test",
    )


async def main() -> None:
    install_test_sealed_secrets(
        Path("/tmp/openclaw-adapter-smoke"),
        boot_key="test-boot-key-for-openclaw-adapter-smoke",
        approval_secret="smoke-approval-secret",
    )
    original_prepare_request = x402.prepare_request
    original_execute_request = x402.execute_request
    async def fake_x402_prepare_request(*, backend, url, method="GET", headers=None, query=None, json_body=None, text_body=None):
        is_evm = str(getattr(backend, "chain", "")).strip().lower() == "evm"
        backend_network = str(getattr(backend, "network", "")).strip().lower()
        is_mainnet = backend_network in {"mainnet", "base"}
        return {
            "asset_type": "x402-request",
            "network": backend_network or "devnet",
            "x402_network": (
                "eip155:8453"
                if is_evm and is_mainnet
                else "eip155:84532"
                if is_evm
                else "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
                if is_mainnet
                else "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"
            ),
            "x402_scheme": "exact",
            "x402_asset": (
                "0x833589fCD6EDb6E08f4c7C32D4f71b54bdA02913"
                if is_evm and is_mainnet
                else "0x036CbD53842c5426634e7929541ec2318f3dCf7e"
                if is_evm
                else "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            ),
            "x402_amount": "250000" if is_mainnet else "100000",
            "x402_amount_display": "0.25" if is_mainnet else "0.1",
            "x402_pay_to": (
                "0x9999999999999999999999999999999999999999"
                if is_evm
                else "Merchant11111111111111111111111111111111111"
            ),
            "request_url": url,
            "method": method,
            "request_fingerprint": "x402-request-fingerprint",
            "body_hash": None,
            "content_type": None,
            "wallet": {
                "chain": "evm" if is_evm else "solana",
                "network": backend_network or "devnet",
                "wallet_type_supported": True,
                "execution_available": True,
                "address": (
                    "0x1111111111111111111111111111111111111111"
                    if is_evm
                    else "Fake11111111111111111111111111111111111111111"
                ),
            },
            "selected_payment": {
                "scheme": "exact",
                "network": (
                    "eip155:8453"
                    if is_evm and is_mainnet
                    else "eip155:84532"
                    if is_evm
                    else "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
                    if is_mainnet
                    else "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"
                ),
                "asset": (
                    "0x833589fCD6EDb6E08f4c7C32D4f71b54bdA02913"
                    if is_evm and is_mainnet
                    else "0x036CbD53842c5426634e7929541ec2318f3dCf7e"
                    if is_evm
                    else "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
                ),
                "amount": "250000" if is_mainnet else "100000",
                "amount_display": "0.25" if is_mainnet else "0.1",
                "pay_to": (
                    "0x9999999999999999999999999999999999999999"
                    if is_evm
                    else "Merchant11111111111111111111111111111111111"
                ),
            },
            "payment_required": True,
            "execute_available": True,
            "prepared": True,
        }

    async def fake_x402_execute_request(*, backend, url, method="GET", headers=None, query=None, json_body=None, text_body=None):
        prepared = await fake_x402_prepare_request(
            backend=backend,
            url=url,
            method=method,
            headers=headers,
            query=query,
            json_body=json_body,
            text_body=text_body,
        )
        prepared.update(
            {
                "mode": "execute",
                "paid": True,
                "broadcasted": True,
                "confirmed": True,
                "payment_settlement": {
                    "success": True,
                    "transaction": (
                        "evm-payment-tx"
                        if str(getattr(backend, "chain", "")).strip().lower() == "evm"
                        else "solana-payment-tx"
                    ),
                    "network": prepared["x402_network"],
                    "payer": prepared["wallet"]["address"],
                    "amount": prepared["x402_amount"],
                },
                "status_code": 200,
                "response_preview": {"ok": True, "result": "paid"},
            }
        )
        return prepared

    x402.prepare_request = fake_x402_prepare_request
    x402.execute_request = fake_x402_execute_request
    adapter = OpenClawWalletAdapter(FakeBackend())
    mainnet_adapter = OpenClawWalletAdapter(MainnetFakeBackend())
    bundle = build_openclaw_plugin_bundle(FakeBackend())
    tool_names = {tool.name for tool in adapter.list_tools()}
    bundle_tool_names = {tool["name"] for tool in bundle["tools"]}

    assert len(tool_names) == 48
    assert bundle["manifest"]["id"] == "agent-wallet"
    assert len(bundle_tool_names) == 48
    assert "Wallet Operator" in bundle["instructions"]
    assert "get_lifi_supported_chains" in tool_names
    assert "get_lifi_quote" in tool_names
    assert "get_lifi_transfer_status" in tool_names
    assert "x402_search_services" in tool_names
    assert "x402_get_service_details" in tool_names
    assert "x402_preview_request" in tool_names
    assert "x402_pay_request" in tool_names
    assert "swap_solana_lifi_cross_chain_tokens" in tool_names
    assert "swap_solana_privately" in tool_names
    assert "continue_solana_private_swap" in tool_names
    assert "get_solana_private_swap_status" in tool_names
    assert "get_jupiter_portfolio" not in tool_names
    assert "get_jupiter_earn_tokens" in tool_names
    assert "jupiter_earn_deposit" in tool_names
    assert "jupiter_earn_withdraw" in tool_names
    assert "get_flash_trade_markets" in tool_names
    assert "get_flash_trade_positions" in tool_names
    assert "flash_trade_open_position" in tool_names
    assert "flash_trade_close_position" in tool_names
    assert "get_kamino_lend_markets" in tool_names
    assert "kamino_lend_deposit" in tool_names
    assert "kamino_lend_borrow" in tool_names
    assert "get_bags_claimable_positions" in tool_names
    assert "get_bags_fee_analytics" in tool_names
    assert "claim_bags_fees" in tool_names
    assert "launch_bags_token" in tool_names
    assert "get_jupiter_portfolio" not in bundle_tool_names
    assert "jupiter_earn_deposit" in bundle_tool_names
    assert "kamino_lend_deposit" in bundle_tool_names
    assert "claim_bags_fees" in bundle_tool_names
    assert "launch_bags_token" in bundle_tool_names
    assert "swap_solana_privately" in bundle_tool_names
    assert "continue_solana_private_swap" in bundle_tool_names
    assert "get_flash_trade_markets" in bundle_tool_names
    assert "get_flash_trade_positions" in bundle_tool_names
    assert "flash_trade_open_position" in bundle_tool_names
    assert "flash_trade_close_position" in bundle_tool_names

    capabilities = await adapter.invoke("get_wallet_capabilities")
    assert capabilities.ok and capabilities.data["backend"] == "fake_wallet"
    assert capabilities.data["network"] == "devnet"
    assert capabilities.data["is_mainnet"] is False

    address = await adapter.invoke("get_wallet_address")
    assert address.ok and address.data["configured"] is True
    assert address.data["network"] == "devnet"

    balance = await adapter.invoke("get_wallet_balance")
    assert balance.ok and balance.data["balance_native"] == 1.25
    assert balance.data["token_count"] == 1
    assert balance.data["asset_count"] == 2
    assert balance.data["total_value_usd"] == "25.50"

    portfolio = await adapter.invoke("get_wallet_portfolio")
    assert portfolio.ok and portfolio.data["token_count"] == 1

    prices = await adapter.invoke(
        "get_solana_token_prices",
        {"mints": ["So11111111111111111111111111111111111111112"]},
    )
    assert prices.ok and prices.data["count"] == 1

    lifi_chains = await adapter.invoke("get_lifi_supported_chains")
    assert lifi_chains.ok and lifi_chains.data["chain_count"] == 3

    lifi_quote = await adapter.invoke(
        "get_lifi_quote",
        {
            "from_chain": "solana",
            "to_chain": "base",
            "from_token": "native",
            "to_token": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
            "amount_in_raw": "1000000",
            "to_address": "0xDF7eD8B45ae91a0881c83A876747AF1FfB48C36E",
            "slippage": 0.01,
        },
    )
    assert lifi_quote.ok and lifi_quote.data["tool"] == "relay"

    lifi_status = await adapter.invoke(
        "get_lifi_transfer_status",
        {"tx_hash": "0xsourcehash", "from_chain": "base", "to_chain": "solana"},
    )
    assert lifi_status.ok and lifi_status.data["status"] == "DONE"

    bags_positions = await mainnet_adapter.invoke("get_bags_claimable_positions")
    assert bags_positions.ok and bags_positions.data["position_count"] == 1

    bags_analytics = await mainnet_adapter.invoke(
        "get_bags_fee_analytics",
        {
            "token_mint": "FakeMint1111111111111111111111111111111111111",
            "include_claim_events": True,
            "mode": "time",
            "from_ts": 10,
            "to_ts": 20,
        },
    )
    assert bags_analytics.ok and bags_analytics.data["lifetime_fees"]["totalFees"] == "42"
    assert bags_analytics.data["claim_events"]["events"][0]["mode"] == "time"

    flash_markets = await adapter.invoke("get_flash_trade_markets")
    assert flash_markets.ok and flash_markets.data["market_count"] == 2
    assert flash_markets.data["markets"][1]["collateral_symbol"] == "USDC"

    flash_positions = await adapter.invoke(
        "get_flash_trade_positions",
        {"pool_name": "Crypto.1"},
    )
    assert flash_positions.ok and flash_positions.data["position_count"] == 1
    assert flash_positions.data["positions"][0]["poolName"] == "Crypto.1"

    flash_open_preview = await adapter.invoke(
        "flash_trade_open_position",
        {
            "pool_name": "Crypto.1",
            "market_symbol": "SOL",
            "collateral_symbol": "SOL",
            "collateral_amount_raw": "100000000",
            "leverage": "5",
            "side": "long",
            "mode": "preview",
            "purpose": "Open a directional SOL perp position",
        },
    )
    assert flash_open_preview.ok and flash_open_preview.data["estimated_size_usd"] == "1250.00"

    flash_open_short_preview = await adapter.invoke(
        "flash_trade_open_position",
        {
            "pool_name": "Crypto.1",
            "market_symbol": "SOL",
            "collateral_symbol": "USDC",
            "collateral_amount_raw": "5000000",
            "leverage": "2",
            "side": "short",
            "mode": "preview",
            "purpose": "Open a SOL short using USDC collateral",
        },
    )
    assert flash_open_short_preview.ok and flash_open_short_preview.data["collateral_symbol"] == "USDC"

    flash_open_prepare = await adapter.invoke(
        "flash_trade_open_position",
        {
            "pool_name": "Crypto.1",
            "market_symbol": "SOL",
            "collateral_symbol": "SOL",
            "collateral_amount_raw": "100000000",
            "leverage": "5",
            "side": "long",
            "mode": "prepare",
            "purpose": "Open a directional SOL perp position",
            "user_intent": True,
        },
    )
    assert flash_open_prepare.ok and flash_open_prepare.data["execution_plan_only"] is True

    flash_open_execute = await adapter.invoke(
        "flash_trade_open_position",
        {
            "pool_name": "Crypto.1",
            "market_symbol": "SOL",
            "collateral_symbol": "SOL",
            "collateral_amount_raw": "100000000",
            "leverage": "5",
            "side": "long",
            "mode": "execute",
            "purpose": "Open a directional SOL perp position",
            "approval_token": _issue_execute_approval(
                tool_name="flash_trade_open_position",
                preview=flash_open_preview.data,
                network="devnet",
                mainnet_confirmed=True,
            ),
        },
    )
    assert flash_open_execute.ok and flash_open_execute.data["broadcasted"] is True

    flash_close_preview = await adapter.invoke(
        "flash_trade_close_position",
        {
            "pool_name": "Crypto.1",
            "market_symbol": "SOL",
            "side": "long",
            "mode": "preview",
            "purpose": "Close the SOL perp position",
        },
    )
    assert flash_close_preview.ok and flash_close_preview.data["position_size_usd"] == "1250.00"

    flash_close_execute = await adapter.invoke(
        "flash_trade_close_position",
        {
            "pool_name": "Crypto.1",
            "market_symbol": "SOL",
            "side": "long",
            "mode": "execute",
            "purpose": "Close the SOL perp position",
            "approval_token": _issue_execute_approval(
                tool_name="flash_trade_close_position",
                preview=flash_close_preview.data,
                network="devnet",
                mainnet_confirmed=True,
            ),
        },
    )
    assert flash_close_execute.ok and flash_close_execute.data["broadcasted"] is True

    kamino_markets = await adapter.invoke("get_kamino_lend_markets")
    assert kamino_markets.ok and kamino_markets.data["market_count"] == 1

    kamino_reserves = await adapter.invoke(
        "get_kamino_lend_market_reserves",
        {"market": "FakeKaminoMarket111111111111111111111111111111"},
    )
    assert kamino_reserves.ok and kamino_reserves.data["reserve_count"] == 1

    kamino_obligations = await adapter.invoke(
        "get_kamino_lend_user_obligations",
        {"market": "FakeKaminoMarket111111111111111111111111111111"},
    )
    assert kamino_obligations.ok and kamino_obligations.data["obligation_count"] == 1

    kamino_rewards = await adapter.invoke("get_kamino_lend_user_rewards")
    assert kamino_rewards.ok and kamino_rewards.data["reward_count"] == 1

    validators = await adapter.invoke("get_solana_staking_validators")
    assert validators.ok and validators.data["validator_count"] == 1

    stake_account = await adapter.invoke(
        "get_solana_stake_account",
        {"stake_account": "FakeStake1111111111111111111111111111111111111"},
    )
    assert stake_account.ok and stake_account.data["account_type"] == "delegated"

    denied = await adapter.invoke(
        "sign_wallet_message",
        {"message": "hello", "purpose": "test", "user_confirmed": False},
    )
    assert denied.ok is False

    signed = await adapter.invoke(
        "sign_wallet_message",
        {"message": "hello", "purpose": "test", "user_confirmed": True},
    )
    assert signed.ok and signed.data["signature"] == "68656c6c6f"

    preview = await adapter.invoke(
        "transfer_sol",
        {
            "recipient": "FakeRecipient1111111111111111111111111111111111",
            "amount": 0.25,
            "mode": "preview",
            "purpose": "test transfer preview",
        },
    )
    assert preview.ok and preview.data["mode"] == "preview"
    assert preview.data["confirmation_summary"]["operation"] == "SOL transfer"
    assert preview.data["confirmation_requirements"]["execute_requires_approval_token"] is True

    denied_transfer = await adapter.invoke(
        "transfer_sol",
        {
            "recipient": "FakeRecipient1111111111111111111111111111111111",
            "amount": 0.25,
            "mode": "execute",
            "purpose": "test transfer execute",
        },
    )
    assert denied_transfer.ok is False

    denied_prepared_transfer = await adapter.invoke(
        "transfer_sol",
        {
            "recipient": "FakeRecipient1111111111111111111111111111111111",
            "amount": 0.25,
            "mode": "prepare",
            "purpose": "test transfer prepare",
            "user_intent": False,
        },
    )
    assert denied_prepared_transfer.ok is False

    prepared_transfer = await adapter.invoke(
        "transfer_sol",
        {
            "recipient": "FakeRecipient1111111111111111111111111111111111",
            "amount": 0.25,
            "mode": "prepare",
            "purpose": "test transfer prepare",
            "user_intent": True,
        },
    )
    assert prepared_transfer.ok and prepared_transfer.data["execution_plan_only"] is True
    assert prepared_transfer.data["signed"] is False
    assert "transaction_base64" not in prepared_transfer.data

    executed_transfer = await adapter.invoke(
        "transfer_sol",
        {
            "recipient": "FakeRecipient1111111111111111111111111111111111",
            "amount": 0.25,
            "mode": "execute",
            "purpose": "test transfer execute",
            "approval_token": _issue_execute_approval(
                tool_name="transfer_sol",
                preview=preview.data,
                network="devnet",
            ),
        },
    )
    assert executed_transfer.ok and executed_transfer.data["confirmed"] is True

    kamino_preview = await adapter.invoke(
        "kamino_lend_deposit",
        {
            "market": "FakeKaminoMarket111111111111111111111111111111",
            "reserve": "FakeKaminoReserve1111111111111111111111111111",
            "amount_ui": "1.25",
            "mode": "preview",
            "purpose": "test kamino deposit preview",
        },
    )
    assert kamino_preview.ok and kamino_preview.data["mode"] == "preview"
    assert kamino_preview.data["confirmation_summary"]["operation"] == "Kamino deposit"
    assert kamino_preview.data["confirmation_summary"]["market"] == "FakeKaminoMarket111111111111111111111111111111"

    kamino_prepare = await adapter.invoke(
        "kamino_lend_deposit",
        {
            "market": "FakeKaminoMarket111111111111111111111111111111",
            "reserve": "FakeKaminoReserve1111111111111111111111111111",
            "amount_ui": "1.25",
            "mode": "prepare",
            "purpose": "test kamino deposit prepare",
            "user_intent": True,
        },
    )
    assert kamino_prepare.ok and kamino_prepare.data["execution_plan_only"] is True
    assert "transaction_base64" not in kamino_prepare.data

    kamino_execute = await adapter.invoke(
        "kamino_lend_deposit",
        {
            "market": "FakeKaminoMarket111111111111111111111111111111",
            "reserve": "FakeKaminoReserve1111111111111111111111111111",
            "amount_ui": "1.25",
            "mode": "execute",
            "purpose": "test kamino deposit execute",
            "approval_token": _issue_execute_approval(
                tool_name="kamino_lend_deposit",
                preview=kamino_preview.data,
                network="devnet",
            ),
        },
    )
    assert kamino_execute.ok and kamino_execute.data["confirmed"] is True

    stake_preview = await adapter.invoke(
        "stake_sol_native",
        {
            "vote_account": "FakeVote11111111111111111111111111111111111111",
            "amount": 1.0,
            "mode": "preview",
            "purpose": "test native stake preview",
        },
    )
    assert stake_preview.ok and stake_preview.data["asset_type"] == "native-stake"

    stake_prepare = await adapter.invoke(
        "stake_sol_native",
        {
            "vote_account": "FakeVote11111111111111111111111111111111111111",
            "amount": 1.0,
            "mode": "prepare",
            "purpose": "test native stake prepare",
            "user_intent": True,
        },
    )
    assert stake_prepare.ok and stake_prepare.data["execution_plan_only"] is True
    assert stake_prepare.data["signed"] is False
    assert "transaction_base64" not in stake_prepare.data

    stake_execute = await adapter.invoke(
        "stake_sol_native",
        {
            "vote_account": "FakeVote11111111111111111111111111111111111111",
            "amount": 1.0,
            "mode": "execute",
            "purpose": "test native stake execute",
            "approval_token": _issue_execute_approval(
                tool_name="stake_sol_native",
                preview=stake_preview.data,
                network="devnet",
            ),
        },
    )
    assert stake_execute.ok and stake_execute.data["confirmed"] is True

    spl_preview = await adapter.invoke(
        "transfer_spl_token",
        {
            "recipient": "FakeRecipient1111111111111111111111111111111111",
            "mint": "So11111111111111111111111111111111111111112",
            "amount": 0.25,
            "mode": "preview",
            "purpose": "test SPL transfer preview",
        },
    )
    assert spl_preview.ok and spl_preview.data["asset_type"] == "spl"

    denied_spl_transfer = await adapter.invoke(
        "transfer_spl_token",
        {
            "recipient": "FakeRecipient1111111111111111111111111111111111",
            "mint": "So11111111111111111111111111111111111111112",
            "amount": 0.25,
            "mode": "execute",
            "purpose": "test SPL transfer execute",
        },
    )
    assert denied_spl_transfer.ok is False

    prepared_spl_transfer = await adapter.invoke(
        "transfer_spl_token",
        {
            "recipient": "FakeRecipient1111111111111111111111111111111111",
            "mint": "So11111111111111111111111111111111111111112",
            "amount": 0.25,
            "mode": "prepare",
            "purpose": "test SPL transfer prepare",
            "user_intent": True,
        },
    )
    assert prepared_spl_transfer.ok and prepared_spl_transfer.data["execution_plan_only"] is True
    assert prepared_spl_transfer.data["signed"] is False
    assert "transaction_base64" not in prepared_spl_transfer.data

    executed_spl_transfer = await adapter.invoke(
        "transfer_spl_token",
        {
            "recipient": "FakeRecipient1111111111111111111111111111111111",
            "mint": "So11111111111111111111111111111111111111112",
            "amount": 0.25,
            "mode": "execute",
            "purpose": "test SPL transfer execute",
            "approval_token": _issue_execute_approval(
                tool_name="transfer_spl_token",
                preview=spl_preview.data,
                network="devnet",
            ),
        },
    )
    assert executed_spl_transfer.ok and executed_spl_transfer.data["confirmed"] is True

    swap_preview = await adapter.invoke(
        "swap_solana_tokens",
        {
            "input_mint": "So11111111111111111111111111111111111111112",
            "output_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount": 0.1,
            "slippage_bps": 50,
            "mode": "preview",
            "purpose": "test swap preview",
        },
    )
    assert swap_preview.ok and swap_preview.data["asset_type"] == "swap"
    assert swap_preview.data["fee_summary"]["network_fee_lamports"] == 9000
    assert swap_preview.data["fee_summary"]["route_fee_bps"] == 10
    assert "network fee" in swap_preview.data["estimated_total_fee_label"]

    denied_swap = await adapter.invoke(
        "swap_solana_tokens",
        {
            "input_mint": "So11111111111111111111111111111111111111112",
            "output_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount": 0.1,
            "slippage_bps": 50,
            "mode": "execute",
            "purpose": "test swap execute",
        },
    )
    assert denied_swap.ok is False

    prepared_swap = await adapter.invoke(
        "swap_solana_tokens",
        {
            "input_mint": "So11111111111111111111111111111111111111112",
            "output_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount": 0.1,
            "slippage_bps": 50,
            "mode": "prepare",
            "purpose": "test swap prepare",
            "user_intent": True,
        },
    )
    assert prepared_swap.ok and prepared_swap.data["execution_plan_only"] is True
    assert prepared_swap.data["signed"] is False
    assert "transaction_base64" not in prepared_swap.data
    assert prepared_swap.data["fee_summary"]["signature_fee_lamports"] == 5000
    assert "route fee 10 bps" in prepared_swap.data["estimated_total_fee_label"]
    assert "verification" not in prepared_swap.data

    executed_swap = await adapter.invoke(
        "swap_solana_tokens",
        {
            "input_mint": "So11111111111111111111111111111111111111112",
            "output_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount": 0.1,
            "slippage_bps": 50,
            "mode": "execute",
            "purpose": "test swap execute",
            "approval_token": _issue_execute_approval(
                tool_name="swap_solana_tokens",
                preview=swap_preview.data,
                network="devnet",
            ),
        },
    )
    assert executed_swap.ok and executed_swap.data["confirmed"] is True

    intent_swap_preview = await adapter.invoke(
        "swap_solana_tokens",
        {
            "input_mint": "So11111111111111111111111111111111111111112",
            "output_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount": 0.1,
            "slippage_bps": 50,
            "mode": "intent_preview",
            "purpose": "test swap intent preview",
            "valid_for_seconds": 30,
            "max_attempts": 2,
        },
    )
    assert intent_swap_preview.ok
    assert intent_swap_preview.data["asset_type"] == "solana-swap-intent"
    assert intent_swap_preview.data["confirmation_summary"]["operation"] == "Swap intent"
    assert "_preview_digest" not in intent_swap_preview.data["confirmation_summary"]
    assert intent_swap_preview.data["minimum_output_amount_raw"] == 12000000
    assert intent_swap_preview.data["slippage_bps"] == 300
    assert intent_swap_preview.data["valid_for_seconds"] == 120
    assert intent_swap_preview.data["max_attempts"] == 3

    intent_swap_execute = await adapter.invoke(
        "swap_solana_tokens",
        {
            "input_mint": "So11111111111111111111111111111111111111112",
            "output_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount": 0.1,
            "slippage_bps": 50,
            "mode": "intent_execute",
            "purpose": "test swap intent execute",
            "approval_token": _issue_execute_approval(
                tool_name="swap_solana_tokens",
                preview=intent_swap_preview.data,
                network="devnet",
            ),
        },
    )
    assert intent_swap_execute.ok and intent_swap_execute.data["confirmed"] is True
    assert intent_swap_execute.data["intent_execution"]["fresh_quote_used"] is True

    private_swap_preview = await mainnet_adapter.invoke(
        "swap_solana_privately",
        {
            "input_token": "SOL",
            "output_token": "SOL",
            "destination_address": "FakeRecipient1111111111111111111111111111111111",
            "amount": 0.1,
            "use_xmr": True,
            "mode": "preview",
            "purpose": "test private swap preview",
        },
    )
    assert private_swap_preview.ok
    assert private_swap_preview.data["asset_type"] == "solana-private-swap"
    assert private_swap_preview.data["confirmation_summary"]["use_xmr"] is True

    private_swap_prepare = await mainnet_adapter.invoke(
        "swap_solana_privately",
        {
            "input_token": "SOL",
            "output_token": "SOL",
            "destination_address": "FakeRecipient1111111111111111111111111111111111",
            "amount": 0.1,
            "use_xmr": True,
            "mode": "prepare",
            "purpose": "test private swap prepare",
            "user_intent": True,
        },
    )
    assert private_swap_prepare.ok and private_swap_prepare.data["execution_plan_only"] is True

    private_swap_execute = await mainnet_adapter.invoke(
        "swap_solana_privately",
        {
            "input_token": "SOL",
            "output_token": "SOL",
            "destination_address": "FakeRecipient1111111111111111111111111111111111",
            "amount": 0.1,
            "use_xmr": True,
            "mode": "execute",
            "purpose": "test private swap execute",
            "approval_token": _issue_execute_approval(
                tool_name="swap_solana_privately",
                preview=private_swap_preview.data,
                network="mainnet",
                mainnet_confirmed=True,
                bind_preview_digest=True,
            ),
            "_approved_preview": private_swap_preview.data,
        },
    )
    assert private_swap_execute.ok and private_swap_execute.data["confirmed"] is True
    assert private_swap_execute.data["status_tracking"]["poll_status_tool"] == (
        "get_solana_private_swap_status"
    )

    private_swap_status = await mainnet_adapter.invoke(
        "get_solana_private_swap_status",
        {"multi_id": "multi_fake_private_1", "houdini_id": "houdini_private_1"},
    )
    assert private_swap_status.ok
    assert private_swap_status.data["selected_status"] == "ANONYMIZING"

    private_swap_status_by_houdini_id = await mainnet_adapter.invoke(
        "get_solana_private_swap_status",
        {"houdini_id": "houdini_private_1"},
    )
    assert private_swap_status_by_houdini_id.ok
    assert private_swap_status_by_houdini_id.data["selected_houdini_id"] == "houdini_private_1"

    lifi_cross_chain_preview = await mainnet_adapter.invoke(
        "swap_solana_lifi_cross_chain_tokens",
        {
            "input_token": "sol",
            "destination_chain": "base",
            "output_token": "native",
            "destination_address": "0x1111111111111111111111111111111111111111",
            "amount_in_raw": "1000000",
            "slippage": 0.01,
            "mode": "preview",
            "purpose": "test LI.FI Solana cross-chain preview",
        },
    )
    assert lifi_cross_chain_preview.ok
    assert lifi_cross_chain_preview.data["asset_type"] == "solana-lifi-cross-chain-swap"
    assert lifi_cross_chain_preview.data["confirmation_summary"]["input_token"] == (
        "11111111111111111111111111111111"
    )
    assert lifi_cross_chain_preview.data["confirmation_summary"]["output_token"] == (
        "0x0000000000000000000000000000000000000000"
    )

    lifi_cross_chain_prepare = await mainnet_adapter.invoke(
        "swap_solana_lifi_cross_chain_tokens",
        {
            "input_token": "sol",
            "destination_chain": "base",
            "output_token": "native",
            "destination_address": "0x1111111111111111111111111111111111111111",
            "amount_in_raw": "1000000",
            "slippage": 0.01,
            "mode": "prepare",
            "purpose": "test LI.FI Solana cross-chain prepare",
            "user_intent": True,
        },
    )
    assert lifi_cross_chain_prepare.ok and lifi_cross_chain_prepare.data["execution_plan_only"] is True
    assert lifi_cross_chain_prepare.data["signed"] is False

    lifi_cross_chain_execute = await mainnet_adapter.invoke(
        "swap_solana_lifi_cross_chain_tokens",
        {
            "input_token": "sol",
            "destination_chain": "8453",
            "output_token": "native",
            "destination_address": "0x1111111111111111111111111111111111111111",
            "amount_in_raw": "1000000",
            "slippage": 0.01,
            "mode": "execute",
            "purpose": "test LI.FI Solana cross-chain execute",
            "approval_token": _issue_execute_approval(
                tool_name="swap_solana_lifi_cross_chain_tokens",
                preview=lifi_cross_chain_preview.data,
                network="mainnet",
                mainnet_confirmed=True,
            ),
        },
    )
    assert lifi_cross_chain_execute.ok and lifi_cross_chain_execute.data["confirmed"] is True
    assert lifi_cross_chain_execute.data["swap_provider"] == "lifi"

    bags_claim_preview = await mainnet_adapter.invoke(
        "claim_bags_fees",
        {
            "token_mint": "FakeMint1111111111111111111111111111111111111",
            "mode": "preview",
            "purpose": "test Bags fee claim preview",
        },
    )
    assert bags_claim_preview.ok and bags_claim_preview.data["asset_type"] == "bags-fee-claim"

    bags_claim_prepare = await mainnet_adapter.invoke(
        "claim_bags_fees",
        {
            "token_mint": "FakeMint1111111111111111111111111111111111111",
            "mode": "prepare",
            "purpose": "test Bags fee claim prepare",
            "user_intent": True,
        },
    )
    assert bags_claim_prepare.ok and bags_claim_prepare.data["execution_plan_only"] is True
    assert "signatures" not in bags_claim_prepare.data

    bags_claim_execute = await mainnet_adapter.invoke(
        "claim_bags_fees",
        {
            "token_mint": "FakeMint1111111111111111111111111111111111111",
            "mode": "execute",
            "purpose": "test Bags fee claim execute",
            "approval_token": _issue_execute_approval(
                tool_name="claim_bags_fees",
                preview=bags_claim_preview.data,
                network="mainnet",
                mainnet_confirmed=True,
            ),
        },
    )
    assert bags_claim_execute.ok and bags_claim_execute.data["confirmed"] is True

    bags_launch_preview = await mainnet_adapter.invoke(
        "launch_bags_token",
        {
            "name": "OpenClaw",
            "symbol": "CLAW",
            "description": "Launch test token",
            "image_url": "https://example.com/claw.png",
            "website": "https://openclaw.ai",
            "base_mint": "So11111111111111111111111111111111111111112",
            "claimers": ["Fake11111111111111111111111111111111111111111"],
            "basis_points": [10000],
            "initial_buy_sol": 0.01,
            "mode": "preview",
            "purpose": "test Bags launch preview",
        },
    )
    assert bags_launch_preview.ok and bags_launch_preview.data["asset_type"] == "bags-token-launch"
    assert bags_launch_preview.data["claimers_count"] == 1

    bags_launch_prepare = await mainnet_adapter.invoke(
        "launch_bags_token",
        {
            "name": "OpenClaw",
            "symbol": "CLAW",
            "description": "Launch test token",
            "image_url": "https://example.com/claw.png",
            "website": "https://openclaw.ai",
            "base_mint": "So11111111111111111111111111111111111111112",
            "claimers": ["Fake11111111111111111111111111111111111111111"],
            "basis_points": [10000],
            "initial_buy_sol": 0.01,
            "mode": "prepare",
            "purpose": "test Bags launch prepare",
            "user_intent": True,
        },
    )
    assert bags_launch_prepare.ok and bags_launch_prepare.data["execution_plan_only"] is True
    assert "token_mint" not in bags_launch_prepare.data

    bags_launch_execute = await mainnet_adapter.invoke(
        "launch_bags_token",
        {
            "name": "OpenClaw",
            "symbol": "CLAW",
            "description": "Launch test token",
            "image_url": "https://example.com/claw.png",
            "website": "https://openclaw.ai",
            "base_mint": "So11111111111111111111111111111111111111112",
            "claimers": ["Fake11111111111111111111111111111111111111111"],
            "basis_points": [10000],
            "initial_buy_sol": 0.01,
            "mode": "execute",
            "purpose": "test Bags launch execute",
            "approval_token": _issue_execute_approval(
                tool_name="launch_bags_token",
                preview=bags_launch_preview.data,
                network="mainnet",
                mainnet_confirmed=True,
            ),
        },
    )
    assert bags_launch_execute.ok and bags_launch_execute.data["confirmed"] is True
    assert bags_launch_execute.data["token_symbol"] == "CLAW"

    route_only_drifting_backend = RouteOnlyDriftingSwapBackend()
    route_only_drifting_adapter = OpenClawWalletAdapter(route_only_drifting_backend)
    route_only_drifting_preview = await route_only_drifting_adapter.invoke(
        "swap_solana_tokens",
        {
            "input_mint": "So11111111111111111111111111111111111111112",
            "output_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount": 0.1,
            "slippage_bps": 50,
            "mode": "preview",
            "purpose": "test route-only drifting swap preview",
        },
    )
    assert route_only_drifting_preview.ok is True
    route_only_drifting_execute = await route_only_drifting_adapter.invoke(
        "swap_solana_tokens",
        {
            "input_mint": "So11111111111111111111111111111111111111112",
            "output_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount": 0.1,
            "slippage_bps": 50,
            "mode": "execute",
            "purpose": "test route-only drifting swap execute",
            "approval_token": _issue_execute_approval(
                tool_name="swap_solana_tokens",
                preview=route_only_drifting_preview.data,
                network="devnet",
            ),
        },
    )
    assert route_only_drifting_execute.ok is True
    assert route_only_drifting_backend._swap_preview_calls == 2

    no_repreview_backend = NoRepreviewSwapBackend()
    no_repreview_adapter = OpenClawWalletAdapter(no_repreview_backend)
    no_repreview_preview = await no_repreview_adapter.invoke(
        "swap_solana_tokens",
        {
            "input_mint": "So11111111111111111111111111111111111111112",
            "output_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount": 0.1,
            "slippage_bps": 50,
            "mode": "preview",
            "purpose": "test no-repreview swap preview",
        },
    )
    assert no_repreview_preview.ok is True
    no_repreview_execute = await no_repreview_adapter.invoke(
        "swap_solana_tokens",
        {
            "input_mint": "So11111111111111111111111111111111111111112",
            "output_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount": 0.1,
            "slippage_bps": 50,
            "mode": "execute",
            "purpose": "test no-repreview swap execute",
            "approval_token": _issue_execute_approval(
                tool_name="swap_solana_tokens",
                preview=no_repreview_preview.data,
                network="devnet",
                bind_preview_digest=True,
            ),
            "_approved_preview": no_repreview_preview.data,
        },
    )
    assert no_repreview_execute.ok is True
    assert no_repreview_backend._swap_preview_calls == 1

    no_repreview_legacy_summary_preview = dict(no_repreview_preview.data)
    no_repreview_legacy_summary_preview["confirmation_summary"] = {
        **no_repreview_preview.data["confirmation_summary"],
        "quote_fingerprint": "legacy-bridge-fingerprint",
    }
    no_repreview_legacy_summary_execute = await no_repreview_adapter.invoke(
        "swap_solana_tokens",
        {
            "input_mint": "So11111111111111111111111111111111111111112",
            "output_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount": 0.1,
            "slippage_bps": 50,
            "mode": "execute",
            "purpose": "test digest-bound swap execute with legacy summary",
            "approval_token": _issue_execute_approval(
                tool_name="swap_solana_tokens",
                preview=no_repreview_legacy_summary_preview,
                network="devnet",
                bind_preview_digest=True,
            ),
            "_approved_preview": no_repreview_legacy_summary_preview,
        },
    )
    assert no_repreview_legacy_summary_execute.ok is True
    assert no_repreview_backend._swap_preview_calls == 1

    no_repreview_flash_backend = NoRepreviewFlashBackend()
    no_repreview_flash_adapter = OpenClawWalletAdapter(no_repreview_flash_backend)
    no_repreview_flash_preview = await no_repreview_flash_adapter.invoke(
        "flash_trade_open_position",
        {
            "pool_name": "Crypto.1",
            "market_symbol": "SOL",
            "collateral_symbol": "SOL",
            "collateral_amount_raw": "100000000",
            "leverage": "1",
            "side": "long",
            "mode": "preview",
            "purpose": "test no-repreview flash execute",
        },
    )
    assert no_repreview_flash_preview.ok is True
    no_repreview_flash_execute = await no_repreview_flash_adapter.invoke(
        "flash_trade_open_position",
        {
            "pool_name": "Crypto.1",
            "market_symbol": "SOL",
            "collateral_symbol": "SOL",
            "collateral_amount_raw": "100000000",
            "leverage": "1",
            "side": "long",
            "mode": "execute",
            "purpose": "test no-repreview flash execute",
            "approval_token": _issue_execute_approval(
                tool_name="flash_trade_open_position",
                preview=no_repreview_flash_preview.data,
                network="devnet",
                bind_preview_digest=True,
            ),
            "_approved_preview": no_repreview_flash_preview.data,
        },
    )
    assert no_repreview_flash_execute.ok is True
    assert no_repreview_flash_backend._flash_open_preview_calls == 1

    drifting_swap_adapter = OpenClawWalletAdapter(DriftingSwapBackend())
    drifting_swap_preview = await drifting_swap_adapter.invoke(
        "swap_solana_tokens",
        {
            "input_mint": "So11111111111111111111111111111111111111112",
            "output_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount": 0.1,
            "slippage_bps": 50,
            "mode": "preview",
            "purpose": "test drifting swap preview",
        },
    )
    assert drifting_swap_preview.ok is True

    drifting_swap_execute = await drifting_swap_adapter.invoke(
        "swap_solana_tokens",
        {
            "input_mint": "So11111111111111111111111111111111111111112",
            "output_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount": 0.1,
            "slippage_bps": 50,
            "mode": "execute",
            "purpose": "test drifting swap execute",
            "approval_token": _issue_execute_approval(
                tool_name="swap_solana_tokens",
                preview=drifting_swap_preview.data,
                network="devnet",
            ),
        },
    )
    assert drifting_swap_execute.ok is True

    close_preview = await adapter.invoke(
        "close_empty_token_accounts",
        {
            "limit": 4,
            "mode": "preview",
            "purpose": "test close preview",
        },
    )
    assert close_preview.ok and close_preview.data["selected_count"] == 1

    denied_close = await adapter.invoke(
        "close_empty_token_accounts",
        {
            "limit": 4,
            "mode": "execute",
            "purpose": "test close execute",
        },
    )
    assert denied_close.ok is False

    executed_close = await adapter.invoke(
        "close_empty_token_accounts",
        {
            "limit": 4,
            "mode": "execute",
            "purpose": "test close execute",
            "approval_token": _issue_execute_approval(
                tool_name="close_empty_token_accounts",
                preview=close_preview.data,
                network="devnet",
            ),
        },
    )
    assert executed_close.ok and executed_close.data["confirmed"] is True

    deactivate_preview = await adapter.invoke(
        "deactivate_solana_stake",
        {
            "stake_account": "FakeStake1111111111111111111111111111111111111",
            "mode": "preview",
            "purpose": "test deactivate stake preview",
        },
    )
    assert deactivate_preview.ok and deactivate_preview.data["asset_type"] == "deactivate-stake"

    deactivate_prepare = await adapter.invoke(
        "deactivate_solana_stake",
        {
            "stake_account": "FakeStake1111111111111111111111111111111111111",
            "mode": "prepare",
            "purpose": "test deactivate stake prepare",
            "user_intent": True,
        },
    )
    assert deactivate_prepare.ok and deactivate_prepare.data["execution_plan_only"] is True
    assert deactivate_prepare.data["signed"] is False
    assert "transaction_base64" not in deactivate_prepare.data

    deactivate_execute = await adapter.invoke(
        "deactivate_solana_stake",
        {
            "stake_account": "FakeStake1111111111111111111111111111111111111",
            "mode": "execute",
            "purpose": "test deactivate stake execute",
            "approval_token": _issue_execute_approval(
                tool_name="deactivate_solana_stake",
                preview=deactivate_preview.data,
                network="devnet",
            ),
        },
    )
    assert deactivate_execute.ok and deactivate_execute.data["confirmed"] is True

    withdraw_preview = await adapter.invoke(
        "withdraw_solana_stake",
        {
            "stake_account": "FakeStake1111111111111111111111111111111111111",
            "amount": 0.5,
            "mode": "preview",
            "purpose": "test withdraw stake preview",
        },
    )
    assert withdraw_preview.ok and withdraw_preview.data["asset_type"] == "withdraw-stake"

    withdraw_prepare = await adapter.invoke(
        "withdraw_solana_stake",
        {
            "stake_account": "FakeStake1111111111111111111111111111111111111",
            "amount": 0.5,
            "mode": "prepare",
            "purpose": "test withdraw stake prepare",
            "user_intent": True,
        },
    )
    assert withdraw_prepare.ok and withdraw_prepare.data["execution_plan_only"] is True
    assert withdraw_prepare.data["signed"] is False
    assert "transaction_base64" not in withdraw_prepare.data

    withdraw_execute = await adapter.invoke(
        "withdraw_solana_stake",
        {
            "stake_account": "FakeStake1111111111111111111111111111111111111",
            "amount": 0.5,
            "mode": "execute",
            "purpose": "test withdraw stake execute",
            "approval_token": _issue_execute_approval(
                tool_name="withdraw_solana_stake",
                preview=withdraw_preview.data,
                network="devnet",
            ),
        },
    )
    assert withdraw_execute.ok and withdraw_execute.data["confirmed"] is True

    airdrop = await adapter.invoke("request_devnet_airdrop", {"amount": 1.0})
    assert airdrop.ok and airdrop.data["mode"] == "airdrop"

    print("smoke_openclaw_adapter: ok")

    mainnet_backend = FakeBackend()
    mainnet_backend.network = "mainnet"
    mainnet_adapter = OpenClawWalletAdapter(mainnet_backend)

    mainnet_preview = await mainnet_adapter.invoke(
        "transfer_sol",
        {
            "recipient": "FakeRecipient1111111111111111111111111111111111",
            "amount": 0.25,
            "mode": "preview",
            "purpose": "mainnet transfer preview",
        },
    )
    assert mainnet_preview.ok is True

    denied_mainnet_execute = await mainnet_adapter.invoke(
        "transfer_sol",
        {
            "recipient": "FakeRecipient1111111111111111111111111111111111",
            "amount": 0.25,
            "mode": "execute",
            "purpose": "mainnet execute without extra confirm",
            "approval_token": _issue_execute_approval(
                tool_name="transfer_sol",
                preview=mainnet_preview.data,
                network="mainnet",
                mainnet_confirmed=False,
            ),
        },
    )
    assert denied_mainnet_execute.ok is False

    allowed_mainnet_prepare = await mainnet_adapter.invoke(
        "transfer_sol",
        {
            "recipient": "FakeRecipient1111111111111111111111111111111111",
            "amount": 0.25,
            "mode": "prepare",
            "purpose": "mainnet prepare with explicit intent",
            "user_intent": True,
        },
    )
    assert allowed_mainnet_prepare.ok is True
    assert "mainnet_warning" in allowed_mainnet_prepare.data
    assert allowed_mainnet_prepare.data["confirmation_summary"]["network"] == "mainnet"

    allowed_mainnet_execute = await mainnet_adapter.invoke(
        "transfer_sol",
        {
            "recipient": "FakeRecipient1111111111111111111111111111111111",
            "amount": 0.25,
            "mode": "execute",
            "purpose": "mainnet execute with extra confirm",
            "approval_token": _issue_execute_approval(
                tool_name="transfer_sol",
                preview=mainnet_preview.data,
                network="mainnet",
                mainnet_confirmed=True,
            ),
        },
    )
    assert allowed_mainnet_execute.ok is True
    assert (
        allowed_mainnet_execute.data["confirmation_requirements"]["execute_requires_mainnet_confirmed_in_token"]
        is True
    )

    mainnet_swap_preview = await mainnet_adapter.invoke(
        "swap_solana_tokens",
        {
            "input_mint": "So11111111111111111111111111111111111111112",
            "output_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount": 0.1,
            "slippage_bps": 50,
            "mode": "preview",
            "purpose": "mainnet swap preview",
        },
    )
    assert mainnet_swap_preview.ok is True

    denied_mainnet_swap = await mainnet_adapter.invoke(
        "swap_solana_tokens",
        {
            "input_mint": "So11111111111111111111111111111111111111112",
            "output_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount": 0.1,
            "slippage_bps": 50,
            "mode": "execute",
            "purpose": "mainnet swap execute without extra confirm",
            "approval_token": _issue_execute_approval(
                tool_name="swap_solana_tokens",
                preview=mainnet_swap_preview.data,
                network="mainnet",
                mainnet_confirmed=False,
            ),
        },
    )
    assert denied_mainnet_swap.ok is False

    denied_mainnet_earn_deposit = await mainnet_adapter.invoke(
        "jupiter_earn_deposit",
        {
            "asset": "So11111111111111111111111111111111111111112",
            "amount_raw": "1000000",
            "mode": "execute",
            "purpose": "mainnet earn deposit execute without extra confirm",
            "user_confirmed": True,
            "mainnet_confirmed": False,
        },
    )
    assert denied_mainnet_earn_deposit.ok is False

    mainnet_native_stake_preview = await mainnet_adapter.invoke(
        "stake_sol_native",
        {
            "vote_account": "FakeVote11111111111111111111111111111111111111",
            "amount": 1.0,
            "mode": "preview",
            "purpose": "mainnet native stake preview",
        },
    )
    assert mainnet_native_stake_preview.ok is True

    denied_mainnet_native_stake = await mainnet_adapter.invoke(
        "stake_sol_native",
        {
            "vote_account": "FakeVote11111111111111111111111111111111111111",
            "amount": 1.0,
            "mode": "execute",
            "purpose": "mainnet native stake execute without extra confirm",
            "approval_token": _issue_execute_approval(
                tool_name="stake_sol_native",
                preview=mainnet_native_stake_preview.data,
                network="mainnet",
                mainnet_confirmed=False,
            ),
        },
    )
    assert denied_mainnet_native_stake.ok is False

    allowed_mainnet_balance = await mainnet_adapter.invoke("get_wallet_balance")
    assert allowed_mainnet_balance.ok is True

    x402_prepared = await adapter.invoke(
        "x402_pay_request",
        {
            "url": "https://paid.example.com/report",
            "mode": "prepare",
            "purpose": "buy paid report",
            "user_intent": True,
        },
    )
    assert x402_prepared.ok is True
    assert x402_prepared.data["prepared"] is True

    async def failing_x402_prepare_request(*, backend, url, method="GET", headers=None, query=None, json_body=None, text_body=None):
        raise ProviderError(
            "x402-solana",
            "Failed to build the Solana x402 payment payload.",
            details={"sdk_rpc_url": "https://api.mainnet-beta.solana.com", "error_type": "SolanaRpcException"},
        )

    x402.prepare_request = failing_x402_prepare_request
    provider_failure = await adapter.invoke(
        "x402_pay_request",
        {
            "url": "https://paid.example.com/report",
            "mode": "prepare",
            "purpose": "buy paid report",
            "user_intent": True,
        },
    )
    assert provider_failure.ok is False
    assert provider_failure.error_code == "x402-solana"
    assert provider_failure.error_details["error_type"] == "SolanaRpcException"
    x402.prepare_request = fake_x402_prepare_request

    x402_executed = await adapter.invoke(
        "x402_pay_request",
        {
            "url": "https://paid.example.com/report",
            "mode": "execute",
            "purpose": "buy paid report",
            "approval_token": _issue_execute_approval(
                tool_name="x402_pay_request",
                preview=x402_prepared.data,
                network="devnet",
                mainnet_confirmed=False,
            ),
        },
    )
    assert x402_executed.ok is True
    assert x402_executed.data["paid"] is True
    assert x402_executed.data["payment_settlement"]["transaction"] == "solana-payment-tx"

    mainnet_x402_prepared = await mainnet_adapter.invoke(
        "x402_pay_request",
        {
            "url": "https://paid.example.com/report",
            "mode": "prepare",
            "purpose": "buy paid report on mainnet",
            "user_intent": True,
        },
    )
    assert mainnet_x402_prepared.ok is True
    assert "mainnet_warning" in mainnet_x402_prepared.data
    assert mainnet_x402_prepared.data["confirmation_summary"]["x402_amount"] == "250000"
    assert mainnet_x402_prepared.data["confirmation_summary"]["network"] == "mainnet"

    denied_mainnet_x402 = await mainnet_adapter.invoke(
        "x402_pay_request",
        {
            "url": "https://paid.example.com/report",
            "mode": "execute",
            "purpose": "buy paid report on mainnet",
            "approval_token": _issue_execute_approval(
                tool_name="x402_pay_request",
                preview=mainnet_x402_prepared.data,
                network="mainnet",
                mainnet_confirmed=False,
            ),
        },
    )
    assert denied_mainnet_x402.ok is False

    allowed_mainnet_x402 = await mainnet_adapter.invoke(
        "x402_pay_request",
        {
            "url": "https://paid.example.com/report",
            "mode": "execute",
            "purpose": "buy paid report on mainnet",
            "approval_token": _issue_execute_approval(
                tool_name="x402_pay_request",
                preview=mainnet_x402_prepared.data,
                network="mainnet",
                mainnet_confirmed=True,
            ),
        },
    )
    assert allowed_mainnet_x402.ok is True
    assert allowed_mainnet_x402.data["paid"] is True
    assert (
        allowed_mainnet_x402.data["confirmation_requirements"]["execute_requires_mainnet_confirmed_in_token"]
        is True
    )

    original_fetch_swap_v2_order = jupiter.fetch_swap_v2_order
    async def fake_strict_swap_v2_order(**kwargs):
        return {
            "outAmount": "100000000",
            "otherAmountThreshold": "100000000",
            "transaction": "unused",
            "requestId": "strict-rfq-order",
            "router": "jupiterz",
            "mode": "ultra",
        }
    jupiter.fetch_swap_v2_order = fake_strict_swap_v2_order
    strict_threshold_backend = SolanaWalletBackend(
        rpc_url="http://127.0.0.1:8899",
        network="mainnet",
        address="11111111111111111111111111111111",
        sign_only=True,
    )
    strict_threshold_backend._resolve_mint_decimals = lambda mint: asyncio.sleep(0, result=6)
    strict_threshold_preview = await strict_threshold_backend.preview_swap(
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        amount_ui=5,
        slippage_bps=300,
    )
    assert strict_threshold_preview["swap_provider"] == "jupiter-v2-order"
    assert strict_threshold_preview["minimum_output_amount_raw"] == 97000000
    strict_threshold_intent = await strict_threshold_backend.preview_swap_intent(
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        amount_ui=5,
        slippage_bps=50,
        minimum_output_amount_raw=100000000,
        valid_for_seconds=120,
        max_attempts=1,
    )
    assert strict_threshold_intent["minimum_output_amount_raw"] == 97000000
    assert strict_threshold_intent["requested_minimum_output_amount_raw"] == 100000000
    assert strict_threshold_intent["minimum_output_policy"] == "explicit_clamped_to_slippage_floor"
    assert strict_threshold_intent["slippage_bps"] == 300
    assert strict_threshold_intent["max_attempts"] == 3
    jupiter.fetch_swap_v2_order = original_fetch_swap_v2_order

    class FakeJupiterBuildResponse:
        status_code = 200

        @staticmethod
        def json() -> dict:
            return {"swapTransaction": "built-tx", "lastValidBlockHeight": 123456}

    class FakeJupiterExecuteResponse:
        status_code = 200

        @staticmethod
        def json() -> dict:
            return {"status": "Success", "signature": "SwapV2Sig1111111111111111111111111111111111"}

    class FakeJupiterClient:
        def __init__(self) -> None:
            self.posts = []

        async def post(self, url, json=None, headers=None):
            self.posts.append({"url": url, "body": json, "headers": headers})
            if str(url).endswith("/execute"):
                return FakeJupiterExecuteResponse()
            return FakeJupiterBuildResponse()

    fake_jupiter_client = FakeJupiterClient()
    original_jupiter_get_client = jupiter.get_client
    original_gateway_post = jupiter._gateway_post
    jupiter.get_client = lambda: fake_jupiter_client
    try:
        await jupiter._build_swap_direct(
            user_public_key="Wallet111111111111111111111111111111111111111",
            quote_response={"outAmount": "100000000"},
            wrap_and_unwrap_sol=True,
        )
        direct_build_body = fake_jupiter_client.posts[-1]["body"]
        assert direct_build_body["dynamicComputeUnitLimit"] is True
        assert direct_build_body["dynamicSlippage"] is True
        assert direct_build_body["prioritizationFeeLamports"] == {
            "priorityLevelWithMaxLamports": {
                "priorityLevel": "veryHigh",
                "maxLamports": 2_000_000,
                "global": False,
            }
        }

        gateway_build_body = {}
        async def fake_gateway_post(path_suffix, *, body):
            gateway_build_body.update(body)
            return 200, {"swapTransaction": "gateway-built-tx", "lastValidBlockHeight": 123456}
        jupiter._gateway_post = fake_gateway_post
        await jupiter._build_swap_via_gateway(
            user_public_key="Wallet111111111111111111111111111111111111111",
            quote_response={"outAmount": "100000000"},
            wrap_and_unwrap_sol=True,
        )
        assert gateway_build_body["dynamicComputeUnitLimit"] is True
        assert gateway_build_body["dynamicSlippage"] is True
        assert gateway_build_body["prioritizationFeeLamports"] == {
            "priorityLevelWithMaxLamports": {
                "priorityLevel": "veryHigh",
                "maxLamports": 2_000_000,
                "global": False,
            }
        }

        await jupiter.execute_swap_v2_order(
            signed_transaction_base64="signed-tx",
            request_id="request-id",
            last_valid_block_height=123456,
        )
        assert fake_jupiter_client.posts[-1]["body"]["lastValidBlockHeight"] == "123456"
    finally:
        jupiter.get_client = original_jupiter_get_client
        jupiter._gateway_post = original_gateway_post

    x402.prepare_request = original_prepare_request
    x402.execute_request = original_execute_request


if __name__ == "__main__":
    asyncio.run(main())
