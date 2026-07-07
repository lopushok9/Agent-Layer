"""Smoke test for Kamino response normalization in the Solana backend."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.providers import kamino  # noqa: E402
from agent_wallet.wallet_layer.solana import SolanaWalletBackend  # noqa: E402


async def main() -> None:
    backend = SolanaWalletBackend(
        rpc_url="https://api.mainnet-beta.solana.com",
        network="mainnet",
        address="So11111111111111111111111111111111111111112",
        sign_only=True,
    )

    original_fetch_markets = kamino.fetch_lend_markets
    original_fetch_portfolio = kamino.fetch_portfolio
    original_fetch_vaults = kamino.fetch_earn_vaults
    original_fetch_earn_positions = kamino.fetch_earn_user_positions
    original_fetch_reserves = kamino.fetch_lend_market_reserves
    original_fetch_obligations = kamino.fetch_lend_user_obligations
    original_fetch_rewards = kamino.fetch_lend_user_rewards
    original_fetch_loan_info = kamino.fetch_lend_loan_info
    try:
        async def fake_fetch_markets() -> dict:
            return {
                "markets": [
                    {
                        "lendingMarket": "7u3HeHxYDLhnCoErrtycNokbQYbWGzLs6JSDqGAv5PfF",
                        "name": "Main Market",
                    }
                ]
            }

        async def fake_fetch_portfolio(*, user: str) -> dict:
            return {
                "timestamp": "2026-07-04T00:00:00.000Z",
                "sections": {
                    "lending": {"indexed": True, "errors": []},
                    "liquidity": {"indexed": True, "errors": []},
                    "earn": {"indexed": True, "errors": []},
                },
                "lending": [{"market": "7u3HeHxYDLhnCoErrtycNokbQYbWGzLs6JSDqGAv5PfF"}],
                "multiply": [],
                "leverage": [],
                "liquidity": [{"strategy": "FakeLiquidityStrategy1111111111111111111111111"}],
                "earn": [{"vaultAddress": "HDsayqAsDWy3QvANGqh2yNraqcD8Fnjgh73Mhb3WRS5E"}],
                "privateCredit": [],
                "staking": [],
            }

        async def fake_fetch_vaults() -> dict:
            return {
                "vaults": [
                    {
                        "address": "HDsayqAsDWy3QvANGqh2yNraqcD8Fnjgh73Mhb3WRS5E",
                        "state": {
                            "name": "Fake SOL Earn",
                            "tokenMint": "So11111111111111111111111111111111111111112",
                            # Production vaults report prevAum as a decimal
                            # string; ranking must not choke on the fraction.
                            "prevAum": "21724442402923.2067",
                        },
                        "programId": "KvauGMspG5k6rtzrqqn7WNn3oZdyKqLKwK2XWQ8FLjd",
                    },
                    {
                        "address": "FWcZUkWPCSWjBH16nAYMQtJjHZuDmmtkd4KHnDTUc7su",
                        "state": {
                            "name": "Dust Test Vault",
                            "tokenMint": "So11111111111111111111111111111111111111112",
                            "prevAum": "1000",
                        },
                        "programId": "KvauGMspG5k6rtzrqqn7WNn3oZdyKqLKwK2XWQ8FLjd",
                    },
                ]
            }

        async def fake_fetch_earn_positions(*, user: str, network: str) -> dict:
            return {
                "positions": [
                    {
                        "vaultAddress": "HDsayqAsDWy3QvANGqh2yNraqcD8Fnjgh73Mhb3WRS5E",
                        "stakedShares": "1.23",
                        "unstakedShares": "4.56",
                        "totalShares": "5.79",
                    }
                ]
            }

        async def fake_fetch_reserves(*, market: str, network: str) -> dict:
            return {
                "reserves": [
                    {
                        "reserve": "D6q6wuQSrifJKZYpR1M8R4YawnLDtDsMmWM1NbBmgJ59",
                        "liquidityToken": "USDC",
                        "liquidityTokenMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                        "supplyApy": "0.05",
                    }
                ]
            }

        async def fake_fetch_obligations(*, market: str, user: str, network: str) -> dict:
            return {
                "obligations": [
                    {
                        "obligationAddress": "HcrU9nyaBFmhNPrxnwXRjreVxdQTZdq2dpvktjsWiS4J",
                        "state": {"owner": user},
                    }
                ]
            }

        async def fake_fetch_rewards(*, user: str) -> dict:
            return {
                "rewards": [{"symbol": "KMNO", "amount": "1.23"}],
                "avgBaseApy": "0.04",
            }

        async def fake_fetch_loan_info(*, obligation: str, network: str) -> dict:
            return {
                "loanId": obligation,
                "marketId": "7u3HeHxYDLhnCoErrtycNokbQYbWGzLs6JSDqGAv5PfF",
                "user": "So11111111111111111111111111111111111111112",
                "leverage": "1",
                "loanInfo": {
                    "collateral": {
                        "deposits": [
                            {
                                "tokenMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                                "tokenName": "USDC",
                                "tokenAmount": "10",
                                "tokenValue": "10",
                            }
                        ]
                    },
                    "debt": {"borrows": []},
                    "currentLtv": 0,
                    "maxLtv": 0.8,
                    "liquidationLtv": 0.85,
                    "closeFactor": 0.1,
                },
            }

        kamino.fetch_lend_markets = fake_fetch_markets
        kamino.fetch_portfolio = fake_fetch_portfolio
        kamino.fetch_earn_vaults = fake_fetch_vaults
        kamino.fetch_earn_user_positions = fake_fetch_earn_positions
        kamino.fetch_lend_market_reserves = fake_fetch_reserves
        kamino.fetch_lend_user_obligations = fake_fetch_obligations
        kamino.fetch_lend_user_rewards = fake_fetch_rewards
        kamino.fetch_lend_loan_info = fake_fetch_loan_info

        markets = await backend.get_kamino_lend_markets()
        assert markets["market_count"] == 1
        assert markets["markets"][0]["name"] == "Main Market"

        reserves = await backend.get_kamino_lend_market_reserves(
            market="7u3HeHxYDLhnCoErrtycNokbQYbWGzLs6JSDqGAv5PfF"
        )
        assert reserves["reserve_count"] == 1
        assert reserves["reserves"][0]["liquidityToken"] == "USDC"

        portfolio = await backend.get_kamino_portfolio(
            user="So11111111111111111111111111111111111111112"
        )
        assert portfolio["position_count"] == 3
        assert portfolio["earn_count"] == 1

        vaults = await backend.get_kamino_vaults()
        assert vaults["vault_count"] == 2
        assert vaults["vaults"][0]["name"] == "Fake SOL Earn", "decimal prevAum must outrank integer dust"
        assert vaults["vaults"][0]["token_mint"] == "So11111111111111111111111111111111111111112"

        sol_vaults = await backend.get_kamino_vaults(
            token_mint="So11111111111111111111111111111111111111112"
        )
        assert sol_vaults["vault_count"] == 2
        usdc_vaults = await backend.get_kamino_vaults(
            token_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        )
        assert usdc_vaults["vault_count"] == 0

        async def fake_fetch_vault_metrics(*, vault: str, network: str) -> dict:
            return {
                "apy": "0.0712",
                "apy7d": "0.0699",
                "apy30d": "0.0688",
                "tokensInvestedUsd": "1234567.89",
                "numberOfHolders": 42,
                "sharePrice": "1.05",
            }

        original_fetch_vault_metrics = kamino.fetch_earn_vault_metrics
        kamino.fetch_earn_vault_metrics = fake_fetch_vault_metrics
        try:
            with_metrics = await backend.get_kamino_vaults(include_metrics=True)
            assert with_metrics["vault_count"] == 2
            assert with_metrics["vaults"][0]["metrics"]["apy"] == "0.0712"
            assert with_metrics["vaults"][0]["metrics"]["tokens_invested_usd"] == "1234567.89"

            detail = await backend.get_kamino_vaults(
                vault_address="HDsayqAsDWy3QvANGqh2yNraqcD8Fnjgh73Mhb3WRS5E"
            )
            assert detail["vault_count"] == 1
            assert detail["vaults"][0]["metrics"]["number_of_holders"] == 42
        finally:
            kamino.fetch_earn_vault_metrics = original_fetch_vault_metrics

        earn_positions = await backend.get_kamino_earn_positions(
            user="So11111111111111111111111111111111111111112"
        )
        assert earn_positions["position_count"] == 1
        assert earn_positions["positions"][0]["totalShares"] == "5.79"

        liquidity_positions = await backend.get_kamino_liquidity_positions(
            user="So11111111111111111111111111111111111111112"
        )
        assert liquidity_positions["position_count"] == 1
        assert liquidity_positions["positions"][0]["strategy"] == "FakeLiquidityStrategy1111111111111111111111111"

        obligations = await backend.get_kamino_lend_user_obligations(
            market="7u3HeHxYDLhnCoErrtycNokbQYbWGzLs6JSDqGAv5PfF",
            user="So11111111111111111111111111111111111111112",
        )
        assert obligations["obligation_count"] == 1
        assert obligations["obligations"][0]["state"]["owner"] == "So11111111111111111111111111111111111111112"

        rewards = await backend.get_kamino_lend_user_rewards(
            user="So11111111111111111111111111111111111111112"
        )
        assert rewards["reward_count"] == 1
        assert rewards["avg_base_apy"] == "0.04"

        positions = await backend.get_kamino_open_positions(
            user="So11111111111111111111111111111111111111112"
        )
        assert positions["position_count"] == 1
        assert positions["markets_with_positions_count"] == 1
        assert positions["positions"][0]["loan_info"]["collateral"]["deposits"][0]["token_name"] == "USDC"
        assert positions["positions"][0]["loan_info"]["collateral"]["deposits"][0]["reserve_supply_apy"] == "0.05"
    finally:
        kamino.fetch_lend_markets = original_fetch_markets
        kamino.fetch_portfolio = original_fetch_portfolio
        kamino.fetch_earn_vaults = original_fetch_vaults
        kamino.fetch_earn_user_positions = original_fetch_earn_positions
        kamino.fetch_lend_market_reserves = original_fetch_reserves
        kamino.fetch_lend_user_obligations = original_fetch_obligations
        kamino.fetch_lend_user_rewards = original_fetch_rewards
        kamino.fetch_lend_loan_info = original_fetch_loan_info

    print("smoke_kamino_responses: ok")


if __name__ == "__main__":
    asyncio.run(main())
