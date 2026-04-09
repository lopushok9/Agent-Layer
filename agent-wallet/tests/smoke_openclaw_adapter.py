"""Basic smoke test for the OpenClaw wallet adapter without external RPC."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _secret_test_utils import install_test_sealed_secrets
from agent_wallet.approval import issue_approval_token
from agent_wallet.openclaw_adapter import OpenClawWalletAdapter
from agent_wallet.plugin_bundle import build_openclaw_plugin_bundle
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletCapabilities


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
            "balance_usd": None,
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

    async def get_mayan_supported_chains(self) -> dict:
        return {
            "provider": "mayan",
            "chain": "cross-chain",
            "network": "mainnet",
            "chain_count": 2,
            "chains": [
                {"name": "solana", "display_name": "Solana", "mode": "SOLANA"},
                {"name": "base", "display_name": "Base", "mode": "EVM"},
            ],
            "source": "mayan",
        }

    async def get_mayan_tokens(
        self,
        *,
        chain: str,
        query: str | None = None,
        limit: int = 20,
    ) -> dict:
        return {
            "provider": "mayan",
            "chain": chain,
            "query": query,
            "count": min(limit, 1),
            "total_matches": 1,
            "tokens": [
                {
                    "symbol": "USDC",
                    "name": "USD Coin",
                    "contract": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                    "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                    "decimals": 6,
                    "verified": True,
                }
            ],
            "source": "mayan",
        }

    async def get_mayan_quote(
        self,
        *,
        from_chain: str,
        to_chain: str,
        from_token: str,
        to_token: str,
        amount_in_raw: str,
        slippage_bps: int | str = "auto",
        gas_drop: int | float | None = None,
        destination_address: str | None = None,
    ) -> dict:
        return {
            "provider": "mayan",
            "chain": "cross-chain",
            "network": "mainnet",
            "from_chain": from_chain,
            "to_chain": to_chain,
            "from_token": from_token,
            "to_token": to_token,
            "amount_in_raw": amount_in_raw,
            "slippage_bps": slippage_bps,
            "gas_drop": gas_drop,
            "destination_address": destination_address,
            "quote_count": 1,
            "best_quote": {
                "type": "FAST_MCTP",
                "expectedAmountOutBaseUnits": "995530",
                "minAmountOutBaseUnits": "995122",
                "etaSeconds": 35,
            },
            "quotes": [
                {
                    "type": "FAST_MCTP",
                    "expectedAmountOutBaseUnits": "995530",
                    "minAmountOutBaseUnits": "995122",
                    "etaSeconds": 35,
                }
            ],
            "minimum_sdk_version": [7, 0, 0],
            "source": "mayan",
        }

    async def get_mayan_swap_status(self, *, source_tx_hash: str) -> dict:
        return {
            "provider": "mayan",
            "chain": "cross-chain",
            "network": "mainnet",
            "source_tx_hash": source_tx_hash,
            "client_status": "COMPLETED",
            "swap": {
                "sourceTxHash": source_tx_hash,
                "status": "COMPLETED",
                "fulfillTxHash": "0xfulfilled",
            },
            "source": "mayan",
        }

    async def preview_solana_cross_chain_swap(
        self,
        *,
        input_mint: str,
        destination_chain: str,
        output_token: str,
        destination_address: str,
        amount_ui: float,
        slippage_bps: int | str = "auto",
        gas_drop: int | float | None = None,
    ) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "preview",
            "asset_type": "cross-chain-swap",
            "owner": "Fake11111111111111111111111111111111111111111",
            "source_chain": "solana",
            "destination_chain": destination_chain,
            "input_mint": input_mint,
            "output_token": output_token,
            "destination_address": destination_address,
            "input_amount_ui": amount_ui,
            "input_amount_raw": "1000000",
            "estimated_output_amount_raw": "995530",
            "minimum_output_amount_raw": "995122",
            "slippage_bps": slippage_bps,
            "quote_type": "FAST_MCTP",
            "quote_id": "quote-123",
            "quote_response": {
                "type": "FAST_MCTP",
                "quoteId": "quote-123",
                "expectedAmountOutBaseUnits": "995530",
                "minAmountOutBaseUnits": "995122",
            },
            "swap_provider": "mayan",
            "source": "mayan",
        }

    async def execute_solana_cross_chain_swap_from_preview(self, preview: dict[str, object]) -> dict:
        return {
            "chain": "solana",
            "network": "mainnet",
            "mode": "execute",
            "asset_type": "cross-chain-swap",
            "owner": preview.get("owner"),
            "source_chain": preview.get("source_chain"),
            "destination_chain": preview.get("destination_chain"),
            "input_mint": preview.get("input_mint"),
            "output_token": preview.get("output_token"),
            "destination_address": preview.get("destination_address"),
            "input_amount_ui": preview.get("input_amount_ui"),
            "input_amount_raw": preview.get("input_amount_raw"),
            "estimated_output_amount_raw": preview.get("estimated_output_amount_raw"),
            "minimum_output_amount_raw": preview.get("minimum_output_amount_raw"),
            "slippage_bps": preview.get("slippage_bps"),
            "quote_type": preview.get("quote_type"),
            "quote_id": preview.get("quote_id"),
            "signature": "MayanSig111111111111111111111111111111111111111",
            "source_tx_hash": "MayanSig111111111111111111111111111111111111111",
            "broadcasted": True,
            "confirmed": True,
            "swap_provider": "mayan",
            "execute_response": {"signature": "MayanSig111111111111111111111111111111111111111"},
            "source": "mayan",
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
            "minimum_output_amount_ui": 12.0,
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
            "minimum_output_amount_ui": 12.0,
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


class MainnetFakeBackend(FakeBackend):
    network = "mainnet"


def _issue_execute_approval(
    *,
    tool_name: str,
    preview: dict,
    network: str,
    mainnet_confirmed: bool = False,
) -> str:
    return issue_approval_token(
        tool_name=tool_name,
        network=network,
        summary=preview["confirmation_summary"],
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
    adapter = OpenClawWalletAdapter(FakeBackend())
    mainnet_adapter = OpenClawWalletAdapter(MainnetFakeBackend())
    bundle = build_openclaw_plugin_bundle(FakeBackend())
    tool_names = {tool.name for tool in adapter.list_tools()}
    bundle_tool_names = {tool["name"] for tool in bundle["tools"]}

    assert len(tool_names) == 38
    assert bundle["manifest"]["id"] == "agent-wallet"
    assert len(bundle_tool_names) == 38
    assert "Wallet Operator" in bundle["instructions"]
    assert "get_mayan_supported_chains" in tool_names
    assert "get_mayan_tokens" in tool_names
    assert "get_mayan_quote" in tool_names
    assert "get_mayan_swap_status" in tool_names
    assert "swap_solana_cross_chain_tokens" in tool_names
    assert "get_jupiter_portfolio" not in tool_names
    assert "get_jupiter_earn_tokens" in tool_names
    assert "jupiter_earn_deposit" in tool_names
    assert "jupiter_earn_withdraw" in tool_names
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

    capabilities = await adapter.invoke("get_wallet_capabilities")
    assert capabilities.ok and capabilities.data["backend"] == "fake_wallet"
    assert capabilities.data["network"] == "devnet"
    assert capabilities.data["is_mainnet"] is False

    address = await adapter.invoke("get_wallet_address")
    assert address.ok and address.data["configured"] is True
    assert address.data["network"] == "devnet"

    balance = await adapter.invoke("get_wallet_balance")
    assert balance.ok and balance.data["balance_native"] == 1.25

    portfolio = await adapter.invoke("get_wallet_portfolio")
    assert portfolio.ok and portfolio.data["token_count"] == 1

    prices = await adapter.invoke(
        "get_solana_token_prices",
        {"mints": ["So11111111111111111111111111111111111111112"]},
    )
    assert prices.ok and prices.data["count"] == 1

    mayan_chains = await adapter.invoke("get_mayan_supported_chains")
    assert mayan_chains.ok and mayan_chains.data["chain_count"] == 2

    mayan_tokens = await adapter.invoke(
        "get_mayan_tokens",
        {"chain": "solana", "query": "usdc", "limit": 5},
    )
    assert mayan_tokens.ok and mayan_tokens.data["tokens"][0]["symbol"] == "USDC"

    mayan_quote = await adapter.invoke(
        "get_mayan_quote",
        {
            "from_chain": "solana",
            "to_chain": "base",
            "from_token": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "to_token": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
            "amount_in_raw": "1000000",
            "slippage_bps": "auto",
        },
    )
    assert mayan_quote.ok and mayan_quote.data["best_quote"]["type"] == "FAST_MCTP"

    mayan_status = await adapter.invoke(
        "get_mayan_swap_status",
        {"source_tx_hash": "0xsourcehash"},
    )
    assert mayan_status.ok and mayan_status.data["client_status"] == "COMPLETED"

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
    assert preview.data["confirmation_requirements"]["execute_requires_approval_token"] is False

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

    cross_chain_preview = await mainnet_adapter.invoke(
        "swap_solana_cross_chain_tokens",
        {
            "input_mint": "So11111111111111111111111111111111111111112",
            "destination_chain": "base",
            "output_token": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
            "destination_address": "0x1111111111111111111111111111111111111111",
            "amount": 0.1,
            "mode": "preview",
            "purpose": "test Mayan cross-chain preview",
        },
    )
    assert cross_chain_preview.ok and cross_chain_preview.data["asset_type"] == "cross-chain-swap"
    assert cross_chain_preview.data["swap_provider"] == "mayan"

    cross_chain_prepare = await mainnet_adapter.invoke(
        "swap_solana_cross_chain_tokens",
        {
            "input_mint": "So11111111111111111111111111111111111111112",
            "destination_chain": "base",
            "output_token": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
            "destination_address": "0x1111111111111111111111111111111111111111",
            "amount": 0.1,
            "mode": "prepare",
            "purpose": "test Mayan cross-chain prepare",
            "user_intent": True,
        },
    )
    assert cross_chain_prepare.ok and cross_chain_prepare.data["execution_plan_only"] is True
    assert cross_chain_prepare.data["signed"] is False

    cross_chain_execute = await mainnet_adapter.invoke(
        "swap_solana_cross_chain_tokens",
        {
            "input_mint": "So11111111111111111111111111111111111111112",
            "destination_chain": "base",
            "output_token": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
            "destination_address": "0x1111111111111111111111111111111111111111",
            "amount": 0.1,
            "mode": "execute",
            "purpose": "test Mayan cross-chain execute",
            "approval_token": _issue_execute_approval(
                tool_name="swap_solana_cross_chain_tokens",
                preview=cross_chain_preview.data,
                network="mainnet",
                mainnet_confirmed=True,
            ),
        },
    )
    assert cross_chain_execute.ok and cross_chain_execute.data["confirmed"] is True
    assert cross_chain_execute.data["swap_provider"] == "mayan"

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
    assert drifting_swap_execute.ok is False
    assert "approval_token does not match the requested operation" in str(drifting_swap_execute.error)

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


if __name__ == "__main__":
    asyncio.run(main())
