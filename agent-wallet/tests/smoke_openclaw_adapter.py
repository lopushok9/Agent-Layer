"""Basic smoke test for the OpenClaw wallet adapter without external RPC."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
            "mode": "preview",
            "asset_type": "swap",
            "input_mint": input_mint,
            "output_mint": output_mint,
            "input_amount_ui": amount_ui,
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
            "mode": "execute",
            "asset_type": "swap",
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
            "mode": "prepare",
            "asset_type": "swap",
            "input_mint": input_mint,
            "output_mint": output_mint,
            "input_amount_ui": amount_ui,
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
    os.environ["AGENT_WALLET_APPROVAL_SECRET"] = "smoke-approval-secret"
    adapter = OpenClawWalletAdapter(FakeBackend())
    bundle = build_openclaw_plugin_bundle(FakeBackend())
    tool_names = {tool.name for tool in adapter.list_tools()}
    bundle_tool_names = {tool["name"] for tool in bundle["tools"]}

    assert len(tool_names) == 16
    assert bundle["manifest"]["id"] == "agent-wallet"
    assert len(bundle_tool_names) == 16
    assert "Wallet Operator" in bundle["instructions"]
    assert "get_jupiter_portfolio" not in tool_names
    assert "get_jupiter_earn_tokens" not in tool_names
    assert "jupiter_earn_deposit" not in tool_names
    assert "jupiter_earn_withdraw" not in tool_names
    assert "get_jupiter_portfolio" not in bundle_tool_names
    assert "jupiter_earn_deposit" not in bundle_tool_names

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
