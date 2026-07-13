"""Smoke test for the OpenClaw EVM adapter surface."""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _secret_test_utils import install_test_sealed_secrets  # noqa: E402
from agent_wallet.approval import issue_approval_token  # noqa: E402
from agent_wallet.openclaw_adapter import OpenClawWalletAdapter  # noqa: E402
from agent_wallet.providers import lifi  # noqa: E402
from agent_wallet.wallet_layer.base import AgentWalletBackend, WalletBackendError, WalletCapabilities  # noqa: E402


class FakeEvmBackend(AgentWalletBackend):
    name = "wdk_evm_local"
    chain = "evm"
    network = "ethereum"
    sign_only = False

    def with_network(self, network: str) -> "FakeEvmBackend":
        clone = self.__class__()
        clone.network = str(network).strip().lower()
        return clone

    async def get_address(self) -> str | None:
        return "0x1111111111111111111111111111111111111111"

    async def get_balance(self, address: str | None = None) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "address": address or await self.get_address(),
            "balance_wei": "1230000000000000000",
            "balance_native": "1.23",
            "asset": "ETH",
            "native_price_usd": "3200",
            "native_value_usd": "3936",
            "tokens": [
                {
                    "token_address": "0x2222222222222222222222222222222222222222",
                    "balance_raw": "42000000",
                    "balance_ui": "42",
                    "token_metadata": {
                        "address": "0x2222222222222222222222222222222222222222",
                        "name": "USD Coin",
                        "symbol": "USDC",
                        "decimals": 6,
                        "verified": False,
                        "source": "fake",
                    },
                    "price_usd": "1",
                    "value_usd": "42",
                }
            ],
            "token_count": 1,
            "assets": [
                {
                    "asset_type": "native",
                    "symbol": "ETH",
                    "amount_raw": "1230000000000000000",
                    "amount_ui": "1.23",
                    "price_usd": "3200",
                    "value_usd": "3936",
                },
                {
                    "asset_type": "erc20",
                    "token_address": "0x2222222222222222222222222222222222222222",
                    "symbol": "USDC",
                    "amount_raw": "42000000",
                    "amount_ui": "42",
                    "price_usd": "1",
                    "value_usd": "42",
                },
            ],
            "asset_count": 2,
            "priced_asset_count": 2,
            "balance_usd": "3978",
            "total_value_usd": "3978",
            "source": "fake",
        }

    async def get_evm_network_info(self) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "configured_network": self.network,
            "service_active_network": self.network,
            "available_networks": ["base", "ethereum", "robinhood"],
            "agent_selectable_networks": ["ethereum", "base", "robinhood"],
            "swap_supported_networks": ["ethereum", "base", "robinhood"],
            "network_profiles": {
                "ethereum": {"chainId": 1, "providerUrl": "https://gateway.example/v1/evm/rpc/ethereum?provider=alchemy"},
                "base": {"chainId": 8453, "providerUrl": "https://gateway.example/v1/evm/rpc/base?provider=alchemy"},
                "robinhood": {"chainId": 4663, "providerUrl": "https://gateway.example/v1/evm/rpc/robinhood?provider=alchemy"},
            },
            "selected_profile": {
                "chainId": {"ethereum": 1, "base": 8453, "robinhood": 4663}[self.network],
                "providerUrl": f"https://gateway.example/v1/evm/rpc/{self.network}?provider=alchemy",
            },
            "source": "fake",
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
            "from_address": from_address or await self.get_address(),
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

    async def get_evm_token_balance(self, token_address: str) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "address": await self.get_address(),
            "token_address": token_address,
            "balance_raw": "42000000",
            "balance_ui": "42",
            "token_metadata": {
                "address": token_address,
                "name": "USD Coin",
                "symbol": "USDC",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
            "source": "fake",
        }

    async def get_evm_token_metadata(self, token_address: str) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "token_address": token_address,
            "token_metadata": {
                "address": token_address,
                "name": "USD Coin",
                "symbol": "USDC",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
            "source": "fake",
        }

    async def get_evm_fee_rates(self) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "fee_rates": {
                "slow": "1200000000",
                "normal": "2000000000",
                "fast": "3000000000",
            },
            "source": "fake",
        }

    async def get_evm_transaction_receipt(self, tx_hash: str) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "tx_hash": tx_hash,
            "found": True,
            "receipt": {"transactionHash": tx_hash, "status": "0x1"},
            "source": "fake",
        }

    async def get_evm_aave_account(self) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "address": await self.get_address(),
            "protocol": "aave-v3",
            "account_data": {
                "totalCollateralBase": "100000000",
                "totalDebtBase": "0",
                "availableBorrowsBase": "80000000",
                "currentLiquidationThreshold": "8000",
                "ltv": "7500",
                "healthFactor": "115792089237316195423570985008687907853269984665640564039457584007913129639935",
            },
            "source": "fake",
        }

    async def get_evm_aave_reserves(self) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "protocol": "aave-v3",
            "chain_id": 1 if self.network == "ethereum" else 8453,
            "pool": "0x3333333333333333333333333333333333333333",
            "pool_addresses_provider": "0x4444444444444444444444444444444444444444",
            "ui_pool_data_provider": "0x5555555555555555555555555555555555555555",
            "price_oracle": "0x6666666666666666666666666666666666666666",
            "base_currency_info": {
                "marketReferenceCurrencyUnit": "100000000",
                "marketReferenceCurrencyPriceInUsd": "100000000",
                "marketReferenceCurrencyPriceInUsdFormatted": "1.00000000",
                "networkBaseTokenPriceInUsd": "350000000000",
                "networkBaseTokenPriceInUsdFormatted": "3500.00000000",
                "networkBaseTokenPriceDecimals": 8,
                "usdDecimals": 8,
            },
            "reserve_count": 1,
            "reserves": [
                {
                    "underlyingAsset": "0x2222222222222222222222222222222222222222",
                    "name": "USD Coin",
                    "symbol": "USDC",
                    "decimals": 6,
                    "baseLtvAsCollateral": "7500",
                    "baseLtvAsCollateralPercent": "75.00",
                    "reserveLiquidationThreshold": "8000",
                    "reserveLiquidationThresholdPercent": "80.00",
                    "usageAsCollateralEnabled": True,
                    "borrowingEnabled": True,
                    "isActive": True,
                    "isFrozen": False,
                    "isPaused": False,
                    "flashLoanEnabled": True,
                    "aTokenAddress": "0x7777777777777777777777777777777777777777",
                    "variableDebtTokenAddress": "0x8888888888888888888888888888888888888888",
                    "availableLiquidityRaw": "5000000",
                    "availableLiquidityFormatted": "5.000000",
                    "priceInUsdRaw": "100000000",
                    "priceInUsdFormatted": "1.00000000",
                    "liquidityAprPercent": "5.00",
                    "variableBorrowAprPercent": "7.00",
                }
            ],
            "source": "fake",
        }

    async def get_evm_aave_positions(self) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "address": await self.get_address(),
            "protocol": "aave-v3",
            "chain_id": 1 if self.network == "ethereum" else 8453,
            "emode_category_id": "0",
            "account_data": {
                "totalCollateralBase": "100000000",
                "totalDebtBase": "25000000",
                "availableBorrowsBase": "55000000",
                "currentLiquidationThreshold": "8000",
                "ltv": "7500",
                "healthFactor": "2000000000000000000",
            },
            "base_currency_info": {
                "marketReferenceCurrencyUnit": "100000000",
                "marketReferenceCurrencyPriceInUsd": "100000000",
                "marketReferenceCurrencyPriceInUsdFormatted": "1.00000000",
                "networkBaseTokenPriceInUsd": "350000000000",
                "networkBaseTokenPriceInUsdFormatted": "3500.00000000",
                "networkBaseTokenPriceDecimals": 8,
                "usdDecimals": 8,
            },
            "position_count": 1,
            "positions": [
                {
                    "underlyingAsset": "0x2222222222222222222222222222222222222222",
                    "name": "USD Coin",
                    "symbol": "USDC",
                    "decimals": 6,
                    "collateralEnabled": True,
                    "suppliedBalanceRaw": "1000000",
                    "suppliedBalanceFormatted": "1.000000",
                    "suppliedValueUsdRaw": "100000000",
                    "suppliedValueUsdFormatted": "1.00000000",
                    "variableDebtRaw": "250000",
                    "variableDebtFormatted": "0.250000",
                    "variableDebtValueUsdRaw": "25000000",
                    "variableDebtValueUsdFormatted": "0.25000000",
                    "reserve": {
                        "priceInUsdRaw": "100000000",
                        "priceInUsdFormatted": "1.00000000",
                        "usageAsCollateralEnabled": True,
                        "borrowingEnabled": True,
                        "isActive": True,
                        "isFrozen": False,
                        "isPaused": False,
                        "flashLoanEnabled": True,
                    },
                }
            ],
            "source": "fake",
        }

    async def preview_evm_aave_operation(
        self,
        *,
        operation: str,
        token_address: str,
        amount_raw: str,
    ) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "asset_type": "evm-aave-v3",
            "asset": "ERC20",
            "wallet": "evm-wallet-123",
            "from_address": await self.get_address(),
            "protocol": "aave-v3",
            "operation": operation,
            "token_address": token_address,
            "amount_raw": amount_raw,
            "amount_ui": "1",
            "estimated_fee_wei": "81000000000000",
            "estimated_operation_fee_wei": "53000000000000",
            "estimated_approval_fee_wei": "28000000000000" if operation in {"supply", "repay"} else "0",
            "fee_estimate_available": True,
            "quote_fingerprint": "aave-v3-fingerprint-1",
            "allowance": {
                "spender": "0x3333333333333333333333333333333333333333",
                "current_allowance_raw": "0",
                "required_allowance_raw": amount_raw,
                "approval_required": operation in {"supply", "repay"},
                "approval_sequence": (
                    [{"type": "approve", "amount": amount_raw, "estimatedFeeWei": "28000000000000"}]
                    if operation in {"supply", "repay"}
                    else []
                ),
            },
            "token_metadata": {
                "address": token_address,
                "name": "USD Coin",
                "symbol": "USDC",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
            "source": "fake",
        }

    async def send_evm_aave_operation(
        self,
        *,
        operation: str,
        token_address: str,
        amount_raw: str,
        expected_quote_fingerprint: str | None = None,
    ) -> dict:
        if expected_quote_fingerprint and expected_quote_fingerprint != "aave-v3-fingerprint-1":
            raise WalletBackendError("aave quote changed", code="aave_quote_changed")
        preview = await self.preview_evm_aave_operation(
            operation=operation,
            token_address=token_address,
            amount_raw=amount_raw,
        )
        return {
            **preview,
            "hash": "0x" + "a" * 64,
            "approve_hash": "0x" + "b" * 64 if operation in {"supply", "repay"} else None,
            "broadcasted": True,
            "confirmed": False,
        }

    async def get_evm_lido_overview(self) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "protocol": "lido",
            "preferred_position_token": "wstETH",
            "chain_id": 1,
            "staking_asset": {
                "type": "native",
                "symbol": "ETH",
                "decimals": 18,
            },
            "referral_address": "0x0000000000000000000000000000000000000000",
            "contracts": {
                "stETH": "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84",
                "wstETH": "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0",
                "referralStaker": "0xa88f0329C2c4ce51ba3fc619BBf44efE7120Dd0d",
                "withdrawalQueue": "0x889edC2eDab5f40e902b864aD4d7AdE8E412F9B1",
            },
            "steth_metadata": {
                "address": "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84",
                "name": "Liquid staked Ether 2.0",
                "symbol": "stETH",
                "decimals": 18,
                "verified": True,
                "source": "fake",
            },
            "wsteth_metadata": {
                "address": "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0",
                "name": "Wrapped liquid staked Ether 2.0",
                "symbol": "wstETH",
                "decimals": 18,
                "verified": True,
                "source": "fake",
            },
            "sample_rates": {
                "sampleBaseUnits": "1000000000000000000",
                "wstEthPerStEthRaw": "950000000000000000",
                "wstEthPerStEthFormatted": "0.95",
                "stEthPerWstEthRaw": "1050000000000000000",
                "stEthPerWstEthFormatted": "1.05",
            },
            "staking_apr": {
                "source": "lido-public-api",
                "symbol": "stETH",
                "address": "0xae7ab96520de3a18e5e111b5eaab095312d7fe84",
                "chainId": 1,
                "lastApr": 2.829,
                "lastAprTimeUnix": 1776687767,
                "smaApr": 2.54475,
                "smaWindowDays": 7,
                "aprSeries": [
                    {"timeUnix": 1776687767, "apr": 2.829},
                    {"timeUnix": 1776860531, "apr": 2.586},
                ],
            },
            "staking_apr_error": None,
            "source": "fake",
        }

    async def get_evm_lido_positions(self) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "address": await self.get_address(),
            "protocol": "lido",
            "preferred_position_token": "wstETH",
            "chain_id": 1,
            "contracts": {
                "stETH": "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84",
                "wstETH": "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0",
                "referralStaker": "0xa88f0329C2c4ce51ba3fc619BBf44efE7120Dd0d",
                "withdrawalQueue": "0x889edC2eDab5f40e902b864aD4d7AdE8E412F9B1",
            },
            "native_balance_wei": "1230000000000000000",
            "native_balance_ui": "1.23",
            "steth_equivalent_total_raw": "2100000000000000000",
            "steth_equivalent_total_ui": "2.1",
            "position_count": 2,
            "positions": [
                {
                    "asset": "stETH",
                    "balanceRaw": "1000000000000000000",
                    "balanceFormatted": "1",
                    "stEthEquivalentRaw": "1000000000000000000",
                    "stEthEquivalentFormatted": "1",
                },
                {
                    "asset": "wstETH",
                    "balanceRaw": "1000000000000000000",
                    "balanceFormatted": "1",
                    "stEthEquivalentRaw": "1100000000000000000",
                    "stEthEquivalentFormatted": "1.1",
                },
            ],
            "source": "fake",
        }

    async def preview_evm_lido_operation(
        self,
        *,
        operation: str,
        amount_raw: str,
    ) -> dict:
        input_asset = (
            {
                "address": "0x0000000000000000000000000000000000000000",
                "name": "Ether",
                "symbol": "ETH",
                "decimals": 18,
                "verified": True,
                "source": "native-asset",
            }
            if operation == "stake_eth_for_wsteth"
            else {
                "address": "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84"
                if operation == "wrap_steth"
                else "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0",
                "name": "Liquid staked Ether 2.0"
                if operation == "wrap_steth"
                else "Wrapped liquid staked Ether 2.0",
                "symbol": "stETH" if operation == "wrap_steth" else "wstETH",
                "decimals": 18,
                "verified": True,
                "source": "fake",
            }
        )
        output_asset = {
            "address": "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84"
            if operation == "unwrap_wsteth"
            else "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0",
            "name": "Liquid staked Ether 2.0"
            if operation == "unwrap_wsteth"
            else "Wrapped liquid staked Ether 2.0",
            "symbol": "stETH" if operation == "unwrap_wsteth" else "wstETH",
            "decimals": 18,
            "verified": True,
            "source": "fake",
        }
        requires_approval = operation == "wrap_steth"
        return {
            "chain": "evm",
            "network": self.network,
            "asset_type": "evm-lido-staking",
            "asset": "ETH",
            "wallet": "evm-wallet-123",
            "from_address": await self.get_address(),
            "protocol": "lido",
            "operation": operation,
            "amount_raw": amount_raw,
            "amount_ui": "1",
            "expected_output_amount_raw": "950000000000000000",
            "expected_output_amount_ui": "0.95",
            "estimated_fee_wei": "72000000000000",
            "estimated_operation_fee_wei": "44000000000000",
            "estimated_approval_fee_wei": "28000000000000" if requires_approval else "0",
            "fee_estimate_available": True,
            "quote_fingerprint": "lido-fingerprint-1",
            "allowance": {
                "spender": "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0" if requires_approval else None,
                "current_allowance_raw": "0" if requires_approval else amount_raw,
                "required_allowance_raw": amount_raw,
                "approval_required": requires_approval,
                "approval_sequence": (
                    [{"type": "approve", "amount": amount_raw, "estimatedFeeWei": "28000000000000"}]
                    if requires_approval
                    else []
                ),
            },
            "input_asset": input_asset,
            "output_asset": output_asset,
            "contracts": {
                "stETH": "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84",
                "wstETH": "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0",
                "referralStaker": "0xa88f0329C2c4ce51ba3fc619BBf44efE7120Dd0d",
                "withdrawalQueue": "0x889edC2eDab5f40e902b864aD4d7AdE8E412F9B1",
            },
            "referral_address": "0x0000000000000000000000000000000000000000",
            "simulation": {"ok": True, "skipped": False, "reason": None, "message": None, "details": None},
            "source": "fake",
        }

    async def send_evm_lido_operation(
        self,
        *,
        operation: str,
        amount_raw: str,
        expected_quote_fingerprint: str | None = None,
    ) -> dict:
        if expected_quote_fingerprint and expected_quote_fingerprint != "lido-fingerprint-1":
            raise WalletBackendError("lido quote changed", code="lido_quote_changed")
        preview = await self.preview_evm_lido_operation(
            operation=operation,
            amount_raw=amount_raw,
        )
        return {
            **preview,
            "hash": "0x" + "c" * 64,
            "approve_hash": "0x" + "d" * 64 if operation == "wrap_steth" else None,
            "broadcasted": True,
            "confirmed": False,
        }

    async def get_evm_lido_withdrawal_requests(self) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "address": await self.get_address(),
            "protocol": "lido",
            "chain_id": 1,
            "withdrawal_queue": "0x889edC2eDab5f40e902b864aD4d7AdE8E412F9B1",
            "request_count": 2,
            "claimable_count": 1,
            "requests": [
                {
                    "requestId": "101",
                    "owner": await self.get_address(),
                    "timestamp": "1710000000",
                    "amountOfStETHRaw": "1000000000000000000",
                    "amountOfStETHFormatted": "1",
                    "amountOfSharesRaw": "1000000000000000000",
                    "amountOfSharesFormatted": "1",
                    "amountOfWstETHRaw": "1000000000000000000",
                    "amountOfWstETHFormatted": "1",
                    "isFinalized": False,
                    "isClaimed": False,
                    "claimable": False,
                },
                {
                    "requestId": "102",
                    "owner": await self.get_address(),
                    "timestamp": "1710000100",
                    "amountOfStETHRaw": "2000000000000000000",
                    "amountOfStETHFormatted": "2",
                    "amountOfSharesRaw": "2000000000000000000",
                    "amountOfSharesFormatted": "2",
                    "amountOfWstETHRaw": "2000000000000000000",
                    "amountOfWstETHFormatted": "2",
                    "isFinalized": True,
                    "isClaimed": False,
                    "claimable": True,
                },
            ],
            "source": "fake",
        }

    async def preview_evm_lido_withdrawal(
        self,
        *,
        operation: str,
        amount_raw: str | None = None,
        request_id: str | None = None,
    ) -> dict:
        requires_approval = operation in {"request_withdrawal_steth", "request_withdrawal_wsteth"}
        return {
            "chain": "evm",
            "network": self.network,
            "asset_type": "evm-lido-withdrawal-queue",
            "asset": "ETH",
            "wallet": "evm-wallet-123",
            "from_address": await self.get_address(),
            "protocol": "lido",
            "operation": operation,
            "amount_raw": amount_raw,
            "amount_ui": "1" if amount_raw is not None else None,
            "request_id": request_id,
            "queued_steth_amount_raw": "1000000000000000000" if amount_raw is not None else None,
            "queued_steth_amount_ui": "1" if amount_raw is not None else None,
            "estimated_fee_wei": "68000000000000",
            "estimated_operation_fee_wei": "40000000000000",
            "estimated_approval_fee_wei": "28000000000000" if requires_approval else "0",
            "fee_estimate_available": True,
            "quote_fingerprint": "lido-withdrawal-fingerprint-1",
            "allowance": {
                "spender": "0x889edC2eDab5f40e902b864aD4d7AdE8E412F9B1" if requires_approval else None,
                "current_allowance_raw": "0" if requires_approval else "0",
                "required_allowance_raw": amount_raw or "0",
                "approval_required": requires_approval,
                "approval_sequence": (
                    [{"type": "approve", "amount": amount_raw, "estimatedFeeWei": "28000000000000"}]
                    if requires_approval and amount_raw is not None
                    else []
                ),
            },
            "input_asset": {
                "address": "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84"
                if operation == "request_withdrawal_steth"
                else "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0",
                "name": "Liquid staked Ether 2.0"
                if operation == "request_withdrawal_steth"
                else "Wrapped liquid staked Ether 2.0",
                "symbol": "stETH" if operation == "request_withdrawal_steth" else "wstETH",
                "decimals": 18,
                "verified": True,
                "source": "fake",
            }
            if operation != "claim_withdrawal"
            else None,
            "queue_asset": {
                "address": "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84",
                "name": "Liquid staked Ether 2.0",
                "symbol": "stETH",
                "decimals": 18,
                "verified": True,
                "source": "fake",
            },
            "withdrawal_queue": "0x889edC2eDab5f40e902b864aD4d7AdE8E412F9B1",
            "withdrawal_request": (
                {
                    "requestId": request_id,
                    "owner": await self.get_address(),
                    "timestamp": "1710000100",
                    "amountOfStETHRaw": "2000000000000000000",
                    "amountOfStETHFormatted": "2",
                    "amountOfSharesRaw": "2000000000000000000",
                    "amountOfSharesFormatted": "2",
                    "amountOfWstETHRaw": "2000000000000000000",
                    "amountOfWstETHFormatted": "2",
                    "isFinalized": True,
                    "isClaimed": False,
                    "claimable": True,
                }
                if operation == "claim_withdrawal"
                else {}
            ),
            "simulation": {"ok": True, "skipped": False, "reason": None, "message": None, "details": None},
            "source": "fake",
        }

    async def send_evm_lido_withdrawal(
        self,
        *,
        operation: str,
        amount_raw: str | None = None,
        request_id: str | None = None,
        expected_quote_fingerprint: str | None = None,
    ) -> dict:
        if expected_quote_fingerprint and expected_quote_fingerprint != "lido-withdrawal-fingerprint-1":
            raise WalletBackendError(
                "lido withdrawal quote changed", code="lido_withdrawal_quote_changed"
            )
        preview = await self.preview_evm_lido_withdrawal(
            operation=operation,
            amount_raw=amount_raw,
            request_id=request_id,
        )
        return {
            **preview,
            "hash": "0x" + "e" * 64,
            "approve_hash": (
                "0x" + "f" * 64
                if operation in {"request_withdrawal_steth", "request_withdrawal_wsteth"}
                else None
            ),
            "broadcasted": True,
            "confirmed": False,
        }

    async def get_evm_morpho_vaults(
        self,
        *,
        vault_address: str | None = None,
        limit: int | None = None,
        listed_only: bool = True,
        asset_address: str | None = None,
        min_tvl_usd: float | int | None = None,
        min_net_apy: float | int | None = None,
        order_by: str | None = None,
        order_direction: str | None = None,
    ) -> dict:
        vault = {
            "address": vault_address or "0xb576765fB15505433aF24FEe2c0325895C559FB2",
            "symbol": "pyUSDm",
            "name": "Paypal USD Main",
            "listed": bool(listed_only),
        }
        return {
            "chain": "evm",
            "network": self.network,
            "protocol": "morpho",
            "chain_id": 1 if self.network == "ethereum" else 8453,
            "listed_only": bool(listed_only),
            "requested_limit": limit or 100,
            "order_by": order_by or "TotalAssetsUsd",
            "order_direction": order_direction or "desc",
            "asset_address_filter": [asset_address] if asset_address else None,
            "found": vault_address is not None,
            "vault_count": 1,
            "vault": vault if vault_address else None,
            "vaults": [vault],
            "source": "fake",
        }

    async def get_evm_morpho_markets(
        self,
        *,
        market_id: str | None = None,
        limit: int | None = None,
        listed_only: bool = True,
        search: str | None = None,
        collateral_asset_address: str | None = None,
        loan_asset_address: str | None = None,
        min_supply_usd: float | int | None = None,
        min_net_supply_apy: float | int | None = None,
        order_by: str | None = None,
        order_direction: str | None = None,
    ) -> dict:
        market = {
            "marketId": market_id or "0x9103c3b4e834476c9a62ea009ba2c884ee42e94e6e314a26f04d312434191836",
            "loanAsset": {"symbol": "USDC", "address": "0x2222222222222222222222222222222222222222"},
            "collateralAsset": {"symbol": "cbBTC", "address": "0x3333333333333333333333333333333333333333"},
            "listed": bool(listed_only),
        }
        return {
            "chain": "evm",
            "network": self.network,
            "protocol": "morpho",
            "chain_id": 1 if self.network == "ethereum" else 8453,
            "listed_only": bool(listed_only),
            "requested_limit": limit or 100,
            "order_by": order_by or "SupplyAssetsUsd",
            "order_direction": order_direction or "desc",
            "search": search,
            "collateral_asset_filter": [collateral_asset_address] if collateral_asset_address else None,
            "loan_asset_filter": [loan_asset_address] if loan_asset_address else None,
            "found": market_id is not None,
            "market_count": 1,
            "market": market if market_id else None,
            "markets": [market],
            "source": "fake",
        }

    async def get_evm_morpho_positions(self) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "address": await self.get_address(),
            "protocol": "morpho",
            "chain_id": 1 if self.network == "ethereum" else 8453,
            "market_position_count": 1,
            "vault_position_count": 1,
            "market_positions": [{"market": {"marketId": "0xmarket"}, "state": {"borrowAssets": "0"}}],
            "vault_positions": [{"vault": {"address": "0xvault"}, "assets": "5000000"}],
            "source": "fake",
        }

    async def preview_evm_morpho_vault_operation(
        self,
        *,
        operation: str,
        token_address: str,
        vault_address: str | None = None,
        vault_preset: str | None = None,
        amount_raw: str | None = None,
        native_amount_raw: str | None = None,
    ) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "asset_type": "evm-morpho-vault",
            "asset": "ERC20",
            "wallet": "evm-wallet-123",
            "from_address": await self.get_address(),
            "protocol": "morpho",
            "surface": "vault",
            "operation": operation,
            "target": {
                "type": "vault",
                "vaultAddress": vault_address or "0xb576765fB15505433aF24FEe2c0325895C559FB2",
                "vaultPreset": vault_preset,
            },
            "token_address": token_address,
            "amount_raw": amount_raw,
            "native_amount_raw": native_amount_raw,
            "amount_ui": "2.5" if amount_raw else None,
            "native_amount_ui": "0.1" if native_amount_raw else None,
            "estimated_fee_wei": "10000000000000",
            "estimated_operation_fee_wei": "7000000000000",
            "estimated_requirements_fee_wei": "3000000000000",
            "fee_estimate_available": True,
            "quote_fingerprint": "morpho-vault-fingerprint-1",
            "requirements": {
                "required": operation == "supply",
                "requirement_count": 1 if operation == "supply" else 0,
                "approval_required": operation == "supply",
                "authorization_required": False,
                "sequence": (
                    [{"type": "approval", "amount": amount_raw or "0", "estimatedFeeWei": "3000000000000"}]
                    if operation == "supply"
                    else []
                ),
            },
            "token_metadata": {
                "address": token_address,
                "name": "PayPal USD",
                "symbol": "PYUSD",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
            "source": "fake",
        }

    async def send_evm_morpho_vault_operation(
        self,
        *,
        operation: str,
        token_address: str,
        vault_address: str | None = None,
        vault_preset: str | None = None,
        amount_raw: str | None = None,
        native_amount_raw: str | None = None,
        expected_quote_fingerprint: str | None = None,
    ) -> dict:
        if expected_quote_fingerprint and expected_quote_fingerprint != "morpho-vault-fingerprint-1":
            raise WalletBackendError("morpho vault quote changed", code="morpho_quote_changed")
        preview = await self.preview_evm_morpho_vault_operation(
            operation=operation,
            token_address=token_address,
            vault_address=vault_address,
            vault_preset=vault_preset,
            amount_raw=amount_raw,
            native_amount_raw=native_amount_raw,
        )
        return {
            **preview,
            "hash": "0x" + "1" * 64,
            "result": {
                "hash": "0x" + "1" * 64,
                "requirementsFee": "3000000000000",
                "totalFee": "10000000000000",
                "requirements": [{"type": "approval", "hash": "0x" + "2" * 64}],
            },
            "broadcasted": True,
            "confirmed": False,
        }

    async def preview_evm_morpho_market_operation(
        self,
        *,
        operation: str,
        token_address: str,
        market_id: str | None = None,
        market_preset: str | None = None,
        amount_raw: str | None = None,
        native_amount_raw: str | None = None,
    ) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "asset_type": "evm-morpho-market",
            "asset": "ERC20",
            "wallet": "evm-wallet-123",
            "from_address": await self.get_address(),
            "protocol": "morpho",
            "surface": "market",
            "operation": operation,
            "target": {
                "type": "market",
                "marketId": market_id or "0x9103c3b4e834476c9a62ea009ba2c884ee42e94e6e314a26f04d312434191836",
                "marketPreset": market_preset,
            },
            "token_address": token_address,
            "amount_raw": amount_raw,
            "native_amount_raw": native_amount_raw,
            "amount_ui": "1" if amount_raw else None,
            "native_amount_ui": "0.05" if native_amount_raw else None,
            "estimated_fee_wei": "14000000000000",
            "estimated_operation_fee_wei": "9000000000000",
            "estimated_requirements_fee_wei": "5000000000000" if operation == "borrow" else "0",
            "fee_estimate_available": True,
            "quote_fingerprint": "morpho-market-fingerprint-1",
            "requirements": {
                "required": operation == "borrow",
                "requirement_count": 1 if operation == "borrow" else 0,
                "approval_required": operation == "supply_collateral",
                "authorization_required": operation == "borrow",
                "sequence": (
                    [{"type": "authorization", "estimatedFeeWei": "5000000000000"}]
                    if operation == "borrow"
                    else []
                ),
            },
            "token_metadata": {
                "address": token_address,
                "name": "USD Coin",
                "symbol": "USDC",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
            "source": "fake",
        }

    async def send_evm_morpho_market_operation(
        self,
        *,
        operation: str,
        token_address: str,
        market_id: str | None = None,
        market_preset: str | None = None,
        amount_raw: str | None = None,
        native_amount_raw: str | None = None,
        expected_quote_fingerprint: str | None = None,
    ) -> dict:
        if expected_quote_fingerprint and expected_quote_fingerprint != "morpho-market-fingerprint-1":
            raise WalletBackendError("morpho market quote changed", code="morpho_quote_changed")
        preview = await self.preview_evm_morpho_market_operation(
            operation=operation,
            token_address=token_address,
            market_id=market_id,
            market_preset=market_preset,
            amount_raw=amount_raw,
            native_amount_raw=native_amount_raw,
        )
        return {
            **preview,
            "hash": "0x" + "3" * 64,
            "result": {
                "hash": "0x" + "3" * 64,
                "requirementsFee": "5000000000000" if operation == "borrow" else "0",
                "totalFee": "14000000000000",
                "requirements": (
                    [{"type": "authorization", "hash": "0x" + "4" * 64}]
                    if operation == "borrow"
                    else []
                ),
            },
            "broadcasted": True,
            "confirmed": False,
        }

    async def get_evm_swap_quote(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in_raw: str,
    ) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "address": await self.get_address(),
            "token_in": token_in,
            "token_out": token_out,
            "amount_in_raw": amount_in_raw,
            "amount_in_ui": "1",
            "estimated_output_amount_ui": "0.995",
            "quote": {
                "tokenInAmount": amount_in_raw,
                "tokenOutAmount": "995000",
                "route": "fake-velora-route",
            },
            "protocol": "velora",
            "execution_supported": True,
            "quote_fingerprint": "evm-swap-fingerprint-1",
            "router": "0x4444444444444444444444444444444444444444",
            "estimated_fee_wei": "67000000000000",
            "estimated_swap_fee_wei": "39000000000000",
            "estimated_approval_fee_wei": "28000000000000",
            "slippage_bps": 100,
            "minimum_output_amount_raw": "985050",
            "allowance": {
                "spender": "0x5555555555555555555555555555555555555555",
                "current_allowance_raw": "0",
                "required_allowance_raw": amount_in_raw,
                "approval_required": True,
                "approval_sequence": [
                    {"type": "approve", "amount": amount_in_raw, "estimatedFeeWei": "28000000000000"}
                ],
            },
            "simulation": {
                "ok": None,
                "skipped": True,
                "reason": "allowance_required",
                "message": None,
                "details": None,
            },
            "swap_transaction": {
                "to": "0x4444444444444444444444444444444444444444",
                "value": "0",
                "data_hash": "swap-data-hash-1",
            },
            "token_in_metadata": {
                "address": token_in,
                "name": "USD Coin",
                "symbol": "USDC",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
            "token_out_metadata": {
                "address": token_out,
                "name": "Tether USD",
                "symbol": "USDT",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
            "source": "fake",
        }

    async def get_uniswap_swap_quote(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in_raw: str,
        slippage_bps: int | None = None,
    ) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "token_in": token_in,
            "token_out": token_out,
            "amount_in_raw": amount_in_raw,
            "protocol": "uniswap",
            "routing": "CLASSIC",
            "chain_id": {"ethereum": 1, "base": 8453, "robinhood": 4663}[self.network],
            "slippage_bps": slippage_bps,
            "source": "fake",
        }

    async def preview_uniswap_swap(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in_raw: str,
        slippage_bps: int | None = None,
    ) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "asset_type": "evm-uniswap-swap",
            "asset": "ERC20",
            "wallet": "evm-wallet-123",
            "from_address": await self.get_address(),
            "token_in": token_in,
            "token_out": token_out,
            "input_amount_raw": amount_in_raw,
            "estimated_output_amount_raw": "995000",
            "minimum_output_amount_raw": "985050",
            "slippage_bps": slippage_bps,
            "swap_provider": "uniswap",
            "routing": "CLASSIC",
            "quote_fingerprint": "uniswap-fingerprint-1",
            "router": "0x8876789976decbfcbbbe364623c63652db8c0904",
            "simulation": {"ok": True, "skipped": False, "reason": None, "message": None, "details": None},
            "swap_transaction": {"to": "0x8876789976decbfcbbbe364623c63652db8c0904", "value": "0", "data_hash": "uniswap-data-hash-1"},
            "source": "fake",
        }

    async def send_uniswap_swap(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in_raw: str,
        slippage_bps: int | None = None,
        expected_quote_fingerprint: str | None = None,
        minimum_output_amount_raw: str | None = None,
    ) -> dict:
        if expected_quote_fingerprint and expected_quote_fingerprint != "uniswap-fingerprint-1":
            raise WalletBackendError("uniswap quote changed", code="uniswap_quote_changed")
        if minimum_output_amount_raw and minimum_output_amount_raw != "985050":
            raise WalletBackendError("minimum output mismatch", code="uniswap_quote_changed")
        return {
            **await self.preview_uniswap_swap(
                token_in=token_in,
                token_out=token_out,
                amount_in_raw=amount_in_raw,
                slippage_bps=slippage_bps,
            ),
            "hash": "0x" + "e" * 64,
            "broadcasted": True,
            "confirmed": False,
        }

    async def preview_evm_swap(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in_raw: str,
    ) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "asset_type": "evm-swap",
            "asset": "ERC20",
            "wallet": "evm-wallet-123",
            "from_address": await self.get_address(),
            "token_in": token_in,
            "token_out": token_out,
            "input_amount_raw": amount_in_raw,
            "input_amount_ui": "1",
            "estimated_output_amount_raw": "995000",
            "estimated_output_amount_ui": "0.995",
            "estimated_fee_wei": "67000000000000",
            "estimated_swap_fee_wei": "39000000000000",
            "estimated_approval_fee_wei": "28000000000000",
            "slippage_bps": 100,
            "minimum_output_amount_raw": "985050",
            "swap_provider": "velora",
            "execution_supported": True,
            "route_plan": "fake-velora-route",
            "quote_fingerprint": "evm-swap-fingerprint-1",
            "router": "0x4444444444444444444444444444444444444444",
            "allowance": {
                "spender": "0x5555555555555555555555555555555555555555",
                "current_allowance_raw": "0",
                "required_allowance_raw": amount_in_raw,
                "approval_required": True,
                "approval_sequence": [
                    {"type": "approve", "amount": amount_in_raw, "estimatedFeeWei": "28000000000000"}
                ],
            },
            "simulation": {
                "ok": None,
                "skipped": True,
                "reason": "allowance_required",
                "message": None,
                "details": None,
            },
            "swap_transaction": {
                "to": "0x4444444444444444444444444444444444444444",
                "value": "0",
                "data_hash": "swap-data-hash-1",
            },
            "token_in_metadata": {
                "address": token_in,
                "name": "USD Coin",
                "symbol": "USDC",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
            "token_out_metadata": {
                "address": token_out,
                "name": "Tether USD",
                "symbol": "USDT",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
            "source": "fake",
        }

    async def send_evm_swap(
        self,
        *,
        token_in: str,
        token_out: str,
        amount_in_raw: str,
        expected_quote_fingerprint: str | None = None,
        minimum_output_amount_raw: str | None = None,
    ) -> dict:
        if expected_quote_fingerprint and expected_quote_fingerprint != "evm-swap-fingerprint-1":
            raise WalletBackendError("swap quote changed", code="swap_quote_changed")
        if minimum_output_amount_raw and minimum_output_amount_raw != "985050":
            raise WalletBackendError("minimum output mismatch", code="swap_quote_changed")
        return {
            "chain": "evm",
            "network": self.network,
            "asset_type": "evm-swap",
            "asset": "ERC20",
            "wallet": "evm-wallet-123",
            "from_address": await self.get_address(),
            "token_in": token_in,
            "token_out": token_out,
            "input_amount_raw": amount_in_raw,
            "input_amount_ui": "1",
            "estimated_output_amount_raw": "995000",
            "estimated_output_amount_ui": "0.995",
            "estimated_fee_wei": "67000000000000",
            "estimated_swap_fee_wei": "39000000000000",
            "estimated_approval_fee_wei": "28000000000000",
            "slippage_bps": 100,
            "minimum_output_amount_raw": "985050",
            "swap_provider": "velora",
            "quote_fingerprint": "evm-swap-fingerprint-1",
            "router": "0x4444444444444444444444444444444444444444",
            "allowance": {
                "spender": "0x5555555555555555555555555555555555555555",
                "current_allowance_raw": amount_in_raw,
                "required_allowance_raw": amount_in_raw,
                "approval_required": False,
                "approval_sequence": [],
            },
            "simulation": {
                "ok": True,
                "skipped": False,
                "reason": None,
                "message": None,
                "details": None,
            },
            "swap_transaction": {
                "to": "0x4444444444444444444444444444444444444444",
                "value": "0",
                "data_hash": "swap-data-hash-1",
            },
            "token_in_metadata": {
                "address": token_in,
                "name": "USD Coin",
                "symbol": "USDC",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
            "token_out_metadata": {
                "address": token_out,
                "name": "Tether USD",
                "symbol": "USDT",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
            "output_amount_raw": "995000",
            "hash": "0x" + "d" * 64,
            "broadcasted": True,
            "confirmed": False,
            "source": "fake",
        }

    async def preview_evm_lifi_cross_chain_swap(
        self,
        *,
        token_in: str,
        destination_chain: str,
        output_token: str,
        destination_address: str,
        amount_in_raw: str,
        slippage: float | int | None = None,
        allow_bridges: list[str] | None = None,
        deny_bridges: list[str] | None = None,
        prefer_bridges: list[str] | None = None,
    ) -> dict:
        destination_chain_ids = {
            "ethereum": "1",
            "1": "1",
            "base": "8453",
            "8453": "8453",
            "solana": "1151111081099710",
            "1151111081099710": "1151111081099710",
        }
        destination_chain_id = destination_chain_ids.get(destination_chain, destination_chain)
        zero_address = "0x0000000000000000000000000000000000000000"
        token_in_lower = token_in.lower()
        output_token_lower = output_token.lower()
        normalized_token_in = (
            zero_address
            if token_in_lower in {"native", "eth"}
            else token_in_lower
            if token_in_lower.startswith("0x") and len(token_in_lower) == 42
            else token_in
        )
        normalized_output_token = (
            zero_address
            if destination_chain_id in {"1", "8453"} and output_token_lower in {"native", "eth"}
            else output_token_lower
            if destination_chain_id in {"1", "8453"}
            and output_token_lower.startswith("0x")
            and len(output_token_lower) == 42
            else output_token
        )
        return {
            "chain": "evm",
            "network": self.network,
            "asset_type": "evm-lifi-cross-chain-swap",
            "asset": "EVM",
            "wallet": "evm-wallet-123",
            "from_address": await self.get_address(),
            "source_chain": self.network,
            "destination_chain": destination_chain,
            "destination_chain_id": destination_chain_id,
            "token_in": normalized_token_in,
            "output_token": normalized_output_token,
            "destination_address": destination_address,
            "input_amount_raw": amount_in_raw,
            "input_amount_ui": "1",
            "estimated_output_amount_raw": "996830",
            "estimated_output_amount_ui": "0.99683",
            "estimated_fee_wei": "73000000000000",
            "estimated_swap_fee_wei": "45000000000000",
            "estimated_approval_fee_wei": "28000000000000",
            "slippage": 0.01 if slippage is None else slippage,
            "minimum_output_amount_raw": "996000",
            "swap_provider": "lifi",
            "execution_supported": True,
            "route_plan": {"tool": "across", "estimate": {"toAmount": "996830"}},
            "quote_fingerprint": "lifi-evm-fingerprint-1",
            "quote_type": "lifi",
            "quote_id": "lifi-quote-1",
            "tool": "across",
            "router": "0x1231DEB6f5749EF6cE6943a275A1D3E7486F4EaE",
            "allowance": {
                "spender": "0x1231DEB6f5749EF6cE6943a275A1D3E7486F4EaE",
                "current_allowance_raw": "0",
                "required_allowance_raw": amount_in_raw,
                "approval_required": normalized_token_in.lower() != zero_address,
                "approval_sequence": (
                    [{"type": "approve", "amount": amount_in_raw, "estimatedFeeWei": "28000000000000"}]
                    if normalized_token_in.lower() != zero_address
                    else []
                ),
            },
            "simulation": {
                "ok": None if normalized_token_in.lower() != zero_address else True,
                "skipped": normalized_token_in.lower() != zero_address,
                "reason": "allowance_required" if normalized_token_in.lower() != zero_address else None,
                "message": None,
                "details": None,
            },
            "swap_transaction": {
                "to": "0x1231DEB6f5749EF6cE6943a275A1D3E7486F4EaE",
                "value": "0",
                "data_hash": "lifi-evm-data-hash-1",
            },
            "token_in_metadata": {
                "address": normalized_token_in,
                "name": "USD Coin",
                "symbol": "USDC",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
            "output_token_metadata": {
                "address": normalized_output_token,
                "name": "USD Coin",
                "symbol": "USDC",
                "decimals": 6,
                "verified": True,
                "source": "fake",
            },
            "source": "fake",
        }

    async def send_evm_lifi_cross_chain_swap(
        self,
        *,
        token_in: str,
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
        if minimum_output_amount_raw and minimum_output_amount_raw != "996000":
            raise WalletBackendError("minimum output mismatch", code="swap_quote_changed")
        preview = await self.preview_evm_lifi_cross_chain_swap(
            token_in=token_in,
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
            "output_amount_raw": "996830",
            "hash": "0x" + "f" * 64,
            "broadcasted": True,
            "confirmed": False,
        }

    async def preview_evm_native_transfer(
        self,
        *,
        recipient: str,
        amount_wei: str,
    ) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "asset_type": "evm-native-transfer",
            "asset": "ETH",
            "wallet": "evm-wallet-123",
            "from_address": await self.get_address(),
            "recipient": recipient,
            "amount_wei": amount_wei,
            "estimated_fee_wei": "21000000000000",
            "source": "fake",
        }

    async def send_evm_native_transfer(
        self,
        *,
        recipient: str,
        amount_wei: str,
    ) -> dict:
        preview = await self.preview_evm_native_transfer(recipient=recipient, amount_wei=amount_wei)
        return {
            **preview,
            "hash": "0x" + "b" * 64,
            "broadcasted": True,
            "confirmed": False,
        }

    async def preview_evm_token_transfer(
        self,
        *,
        token_address: str,
        recipient: str,
        amount_raw: str,
    ) -> dict:
        return {
            "chain": "evm",
            "network": self.network,
            "asset_type": "evm-token-transfer",
            "wallet": "evm-wallet-123",
            "from_address": await self.get_address(),
            "recipient": recipient,
            "token_address": token_address,
            "amount_raw": amount_raw,
            "amount_ui": "5",
            "estimated_fee_wei": "45000000000000",
            "token_metadata": {
                "address": token_address,
                "name": "USD Coin",
                "symbol": "USDC",
                "decimals": 6,
                "verified": False,
                "source": "fake",
            },
            "source": "fake",
        }

    async def send_evm_token_transfer(
        self,
        *,
        token_address: str,
        recipient: str,
        amount_raw: str,
    ) -> dict:
        preview = await self.preview_evm_token_transfer(
            token_address=token_address,
            recipient=recipient,
            amount_raw=amount_raw,
        )
        return {
            **preview,
            "hash": "0x" + "c" * 64,
            "broadcasted": True,
            "confirmed": False,
        }

    def get_capabilities(self) -> WalletCapabilities:
        return WalletCapabilities(
            backend=self.name,
            chain=self.chain,
            custody_model="local_service_vault",
            sign_only=False,
            has_signer=True,
            can_get_address=True,
            can_get_balance=True,
            can_sign_message=False,
            can_sign_transaction=True,
            can_send_transaction=True,
            external_dependencies=["wdk-evm-wallet"],
        )


async def _main() -> None:
    adapter = OpenClawWalletAdapter(FakeEvmBackend())
    tool_names = {tool.name for tool in adapter.list_tools()}
    assert "get_lifi_supported_chains" in tool_names
    assert "get_lifi_quote" in tool_names
    assert "get_lifi_transfer_status" in tool_names
    assert "swap_evm_lifi_cross_chain_tokens" in tool_names
    assert "get_evm_network" in tool_names
    assert "set_evm_network" in tool_names
    assert "get_evm_token_metadata" in tool_names
    assert "get_evm_aave_account" in tool_names
    assert "get_evm_aave_reserves" in tool_names
    assert "get_evm_aave_positions" in tool_names
    assert "manage_evm_aave_position" in tool_names
    assert "get_evm_morpho_vaults" in tool_names
    assert "get_evm_morpho_markets" in tool_names
    assert "get_evm_morpho_positions" in tool_names
    assert "manage_evm_morpho_vault_position" in tool_names
    assert "manage_evm_morpho_market_position" in tool_names
    assert "get_evm_lido_overview" in tool_names
    assert "get_evm_lido_positions" in tool_names
    assert "manage_evm_lido_position" in tool_names
    assert "get_evm_lido_withdrawal_requests" in tool_names
    assert "manage_evm_lido_withdrawal" in tool_names
    assert "get_evm_swap_quote" in tool_names
    assert "swap_evm_tokens" in tool_names
    assert "get_uniswap_swap_quote" in tool_names
    assert "swap_evm_uniswap_tokens" in tool_names
    assert "transfer_evm_native" in tool_names
    assert "transfer_evm_token" in tool_names
    assert "transfer_btc" not in tool_names
    assert "transfer_sol" not in tool_names
    lifi_swap_tool = next(tool for tool in adapter.list_tools() if tool.name == "swap_evm_lifi_cross_chain_tokens")
    lifi_destination_enum = lifi_swap_tool.input_schema["properties"]["destination_chain"]["enum"]
    assert "ethereum" in lifi_destination_enum
    assert "base" in lifi_destination_enum
    assert "solana" in lifi_destination_enum
    assert (
        lifi.normalize_token_address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", chain_id="8453")
        == "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    )

    balance = await adapter.invoke("get_wallet_balance", {})
    assert balance.ok is True
    assert balance.data["balance_wei"] == "1230000000000000000"
    assert balance.data["token_count"] == 1
    assert balance.data["asset_count"] == 2
    assert balance.data["balance_usd"] == "3978"
    assert balance.data["total_value_usd"] == "3978"

    base_balance = await adapter.invoke("get_wallet_balance", {"network": "base"})
    assert base_balance.ok is True
    assert base_balance.data["network"] == "base"

    network_info = await adapter.invoke("get_evm_network", {"network": "base"})
    assert network_info.ok is True
    assert network_info.data["configured_network"] == "base"
    assert "ethereum" in network_info.data["agent_selectable_networks"]
    assert "base" in network_info.data["agent_selectable_networks"]
    assert "robinhood" in network_info.data["agent_selectable_networks"]

    switch_adapter = OpenClawWalletAdapter(FakeEvmBackend())
    switched_network = await switch_adapter.invoke("set_evm_network", {"network": "base"})
    assert switched_network.ok is True
    assert switched_network.data["selected_network"] == "base"
    assert switched_network.data["session_active_network"] == "base"
    assert switched_network.data["network_switch_persistent_for_runtime_session"] is True

    default_network_after_switch = await switch_adapter.invoke("get_evm_network", {})
    assert default_network_after_switch.ok is True
    assert default_network_after_switch.data["configured_network"] == "base"

    default_balance_after_switch = await switch_adapter.invoke(
        "get_wallet_balance",
        {},
    )
    assert default_balance_after_switch.ok is True
    assert default_balance_after_switch.data["network"] == "base"

    robinhood_network = await switch_adapter.invoke("set_evm_network", {"network": "robinhood"})
    assert robinhood_network.ok is True
    assert robinhood_network.data["session_active_network"] == "robinhood"
    robinhood_balance = await switch_adapter.invoke("get_wallet_balance", {})
    assert robinhood_balance.ok is True
    assert robinhood_balance.data["network"] == "robinhood"

    robinhood_uniswap_quote = await adapter.invoke(
        "get_uniswap_swap_quote",
        {
            "token_in": "native",
            "token_out": "0x2222222222222222222222222222222222222222",
            "amount_in_raw": "1000000000000000",
            "network": "robinhood",
        },
    )
    assert robinhood_uniswap_quote.ok is True
    assert robinhood_uniswap_quote.data["network"] == "robinhood"
    assert robinhood_uniswap_quote.data["chain_id"] == 4663

    robinhood_uniswap_preview = await adapter.invoke(
        "swap_evm_uniswap_tokens",
        {
            "token_in": "native",
            "token_out": "0x2222222222222222222222222222222222222222",
            "amount_in_raw": "1000000000000000",
            "mode": "preview",
            "purpose": "test robinhood uniswap preview",
            "network": "robinhood",
        },
    )
    assert robinhood_uniswap_preview.ok is True
    assert robinhood_uniswap_preview.data["network"] == "robinhood"

    rejected_network = await switch_adapter.invoke("set_evm_network", {"network": "polygon"})
    assert rejected_network.ok is False
    assert "EVM network must be" in str(rejected_network.error)

    token_balance = await adapter.invoke(
        "get_evm_token_balance",
        {"token_address": "0x2222222222222222222222222222222222222222", "network": "base"},
    )
    assert token_balance.ok is True
    assert token_balance.data["balance_raw"] == "42000000"
    assert token_balance.data["token_metadata"]["symbol"] == "USDC"
    assert token_balance.data["network"] == "base"

    token_metadata = await adapter.invoke(
        "get_evm_token_metadata",
        {"token_address": "0x2222222222222222222222222222222222222222", "network": "base"},
    )
    assert token_metadata.ok is True
    assert token_metadata.data["token_metadata"]["decimals"] == 6
    assert token_metadata.data["network"] == "base"

    lifi_chains = await adapter.invoke("get_lifi_supported_chains", {})
    assert lifi_chains.ok is True
    assert lifi_chains.data["chain_count"] == 3

    lifi_quote = await adapter.invoke(
        "get_lifi_quote",
        {
            "from_chain": "base",
            "to_chain": "solana",
            "from_token": "native",
            "to_token": "native",
            "amount_in_raw": "1000000",
            "to_address": "FakeSolanaAddress111111111111111111111111111",
            "slippage": 0.01,
        },
    )
    assert lifi_quote.ok is True
    assert lifi_quote.data["tool"] == "relay"

    lifi_status = await adapter.invoke(
        "get_lifi_transfer_status",
        {"tx_hash": "0xsourcehash", "from_chain": "base", "to_chain": "solana"},
    )
    assert lifi_status.ok is True
    assert lifi_status.data["status"] == "DONE"

    swap_quote = await adapter.invoke(
        "get_evm_swap_quote",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "token_out": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000",
            "network": "base",
        },
    )
    assert swap_quote.ok is True
    assert swap_quote.data["protocol"] == "velora"
    assert swap_quote.data["network"] == "base"
    assert swap_quote.data["execution_supported"] is True
    assert swap_quote.data["quote_fingerprint"] == "evm-swap-fingerprint-1"
    assert swap_quote.data["allowance"]["approval_required"] is True
    assert swap_quote.data["token_in_metadata"]["symbol"] == "USDC"
    assert swap_quote.data["token_out_metadata"]["symbol"] == "USDT"

    aave_account = await adapter.invoke("get_evm_aave_account", {"network": "base"})
    assert aave_account.ok is True
    assert aave_account.data["network"] == "base"
    assert aave_account.data["protocol"] == "aave-v3"
    assert aave_account.data["account_data"]["availableBorrowsBase"] == "80000000"

    aave_reserves = await adapter.invoke("get_evm_aave_reserves", {"network": "base"})
    assert aave_reserves.ok is True
    assert aave_reserves.data["network"] == "base"
    assert aave_reserves.data["reserve_count"] == 1
    assert aave_reserves.data["reserves"][0]["symbol"] == "USDC"

    aave_positions = await adapter.invoke("get_evm_aave_positions", {"network": "base"})
    assert aave_positions.ok is True
    assert aave_positions.data["network"] == "base"
    assert aave_positions.data["position_count"] == 1
    assert aave_positions.data["positions"][0]["suppliedBalanceRaw"] == "1000000"

    aave_preview = await adapter.invoke(
        "manage_evm_aave_position",
        {
            "operation": "supply",
            "token_address": "0x2222222222222222222222222222222222222222",
            "amount_raw": "1000000",
            "mode": "preview",
            "purpose": "test aave supply",
        },
    )
    assert aave_preview.ok is True
    assert aave_preview.data["asset_type"] == "evm-aave-v3"
    assert aave_preview.data["confirmation_summary"]["aave_operation"] == "supply"
    assert aave_preview.data["confirmation_summary"]["quote_fingerprint"] == "aave-v3-fingerprint-1"
    assert aave_preview.data["allowance"]["approval_required"] is True

    aave_prepare = await adapter.invoke(
        "manage_evm_aave_position",
        {
            "operation": "borrow",
            "token_address": "0x2222222222222222222222222222222222222222",
            "amount_raw": "1000000",
            "mode": "prepare",
            "purpose": "test aave borrow",
            "user_intent": True,
        },
    )
    assert aave_prepare.ok is True
    assert aave_prepare.data["execution_plan_only"] is True
    assert aave_prepare.data["allowance"]["approval_required"] is False

    aave_approval = issue_approval_token(
        tool_name="manage_evm_aave_position",
        network="ethereum",
        summary=aave_preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        issued_by="test",
    )
    aave_executed = await adapter.invoke(
        "manage_evm_aave_position",
        {
            "operation": "supply",
            "token_address": "0x2222222222222222222222222222222222222222",
            "amount_raw": "1000000",
            "mode": "execute",
            "purpose": "test aave supply",
            "approval_token": aave_approval,
        },
    )
    assert aave_executed.ok is True
    assert aave_executed.data["hash"].startswith("0x")
    assert aave_executed.data["approve_hash"].startswith("0x")

    morpho_vaults = await adapter.invoke("get_evm_morpho_vaults", {"network": "base", "limit": 5})
    assert morpho_vaults.ok is True
    assert morpho_vaults.data["vault_count"] == 1

    morpho_markets = await adapter.invoke("get_evm_morpho_markets", {"network": "base"})
    assert morpho_markets.ok is True
    assert morpho_markets.data["market_count"] == 1

    morpho_vaults_filtered = await adapter.invoke(
        "get_evm_morpho_vaults",
        {
            "network": "base",
            "asset_address": "0x2222222222222222222222222222222222222222",
            "order_by": "Apy",
            "order_direction": "asc",
        },
    )
    assert morpho_vaults_filtered.ok is True
    assert morpho_vaults_filtered.data["order_by"] == "Apy"
    assert morpho_vaults_filtered.data["order_direction"] == "asc"
    assert morpho_vaults_filtered.data["asset_address_filter"] == [
        "0x2222222222222222222222222222222222222222"
    ]

    morpho_markets_filtered = await adapter.invoke(
        "get_evm_morpho_markets",
        {"network": "base", "search": "cbBTC", "loan_asset_address": "0x2222222222222222222222222222222222222222"},
    )
    assert morpho_markets_filtered.ok is True
    assert morpho_markets_filtered.data["search"] == "cbBTC"
    assert morpho_markets_filtered.data["loan_asset_filter"] == [
        "0x2222222222222222222222222222222222222222"
    ]

    morpho_positions = await adapter.invoke("get_evm_morpho_positions", {"network": "base"})
    assert morpho_positions.ok is True
    assert morpho_positions.data["vault_position_count"] == 1
    assert morpho_positions.data["market_position_count"] == 1

    morpho_vault_preview = await adapter.invoke(
        "manage_evm_morpho_vault_position",
        {
            "operation": "supply",
            "token_address": "0x2222222222222222222222222222222222222222",
            "vault_address": "0xb576765fB15505433aF24FEe2c0325895C559FB2",
            "amount_raw": "2500000",
            "mode": "preview",
            "purpose": "test morpho vault supply",
            "network": "base",
        },
    )
    assert morpho_vault_preview.ok is True
    assert morpho_vault_preview.data["asset_type"] == "evm-morpho-vault"
    assert morpho_vault_preview.data["confirmation_summary"]["morpho_operation"] == "supply"
    assert morpho_vault_preview.data["confirmation_summary"]["quote_fingerprint"] == "morpho-vault-fingerprint-1"
    assert morpho_vault_preview.data["requirements"]["approval_required"] is True

    morpho_vault_prepare = await adapter.invoke(
        "manage_evm_morpho_vault_position",
        {
            "operation": "withdraw",
            "token_address": "0x2222222222222222222222222222222222222222",
            "vault_address": "0xb576765fB15505433aF24FEe2c0325895C559FB2",
            "amount_raw": "1000000",
            "mode": "prepare",
            "purpose": "test morpho vault withdraw",
            "user_intent": True,
            "network": "base",
        },
    )
    assert morpho_vault_prepare.ok is True
    assert morpho_vault_prepare.data["execution_plan_only"] is True

    morpho_vault_approval = issue_approval_token(
        tool_name="manage_evm_morpho_vault_position",
        network="base",
        summary=morpho_vault_preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        issued_by="test",
    )
    morpho_vault_executed = await adapter.invoke(
        "manage_evm_morpho_vault_position",
        {
            "operation": "supply",
            "token_address": "0x2222222222222222222222222222222222222222",
            "vault_address": "0xb576765fB15505433aF24FEe2c0325895C559FB2",
            "amount_raw": "2500000",
            "mode": "execute",
            "purpose": "test morpho vault supply",
            "approval_token": morpho_vault_approval,
            "network": "base",
        },
    )
    assert morpho_vault_executed.ok is True
    assert morpho_vault_executed.data["hash"].startswith("0x")

    morpho_market_preview = await adapter.invoke(
        "manage_evm_morpho_market_position",
        {
            "operation": "borrow",
            "token_address": "0x2222222222222222222222222222222222222222",
            "market_id": "0x9103c3b4e834476c9a62ea009ba2c884ee42e94e6e314a26f04d312434191836",
            "amount_raw": "1000000",
            "mode": "preview",
            "purpose": "test morpho borrow",
            "network": "base",
        },
    )
    assert morpho_market_preview.ok is True
    assert morpho_market_preview.data["asset_type"] == "evm-morpho-market"
    assert morpho_market_preview.data["confirmation_summary"]["morpho_operation"] == "borrow"
    assert morpho_market_preview.data["requirements"]["authorization_required"] is True

    morpho_market_approval = issue_approval_token(
        tool_name="manage_evm_morpho_market_position",
        network="base",
        summary=morpho_market_preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        issued_by="test",
    )
    morpho_market_executed = await adapter.invoke(
        "manage_evm_morpho_market_position",
        {
            "operation": "borrow",
            "token_address": "0x2222222222222222222222222222222222222222",
            "market_id": "0x9103c3b4e834476c9a62ea009ba2c884ee42e94e6e314a26f04d312434191836",
            "amount_raw": "1000000",
            "mode": "execute",
            "purpose": "test morpho borrow",
            "approval_token": morpho_market_approval,
            "network": "base",
        },
    )
    assert morpho_market_executed.ok is True
    assert morpho_market_executed.data["hash"].startswith("0x")

    lido_overview = await adapter.invoke("get_evm_lido_overview", {"network": "ethereum"})
    assert lido_overview.ok is True
    assert lido_overview.data["protocol"] == "lido"
    assert lido_overview.data["preferred_position_token"] == "wstETH"
    assert lido_overview.data["staking_apr"]["lastApr"] == 2.829
    assert lido_overview.data["staking_apr"]["smaApr"] == 2.54475

    lido_positions = await adapter.invoke("get_evm_lido_positions", {"network": "ethereum"})
    assert lido_positions.ok is True
    assert lido_positions.data["position_count"] == 2
    assert lido_positions.data["positions"][1]["asset"] == "wstETH"

    lido_preview = await adapter.invoke(
        "manage_evm_lido_position",
        {
            "operation": "wrap_steth",
            "amount_raw": "1000000000000000000",
            "mode": "preview",
            "purpose": "test lido wrap",
            "network": "ethereum",
        },
    )
    assert lido_preview.ok is True
    assert lido_preview.data["asset_type"] == "evm-lido-staking"
    assert lido_preview.data["confirmation_summary"]["lido_operation"] == "wrap_steth"
    assert lido_preview.data["confirmation_summary"]["quote_fingerprint"] == "lido-fingerprint-1"
    assert lido_preview.data["allowance"]["approval_required"] is True

    lido_prepare = await adapter.invoke(
        "manage_evm_lido_position",
        {
            "operation": "stake_eth_for_wsteth",
            "amount_raw": "1000000000000000000",
            "mode": "prepare",
            "purpose": "test lido stake",
            "user_intent": True,
            "network": "ethereum",
        },
    )
    assert lido_prepare.ok is True
    assert lido_prepare.data["execution_plan_only"] is True
    assert lido_prepare.data["allowance"]["approval_required"] is False

    lido_approval = issue_approval_token(
        tool_name="manage_evm_lido_position",
        network="ethereum",
        summary=lido_preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        issued_by="test",
    )
    lido_executed = await adapter.invoke(
        "manage_evm_lido_position",
        {
            "operation": "wrap_steth",
            "amount_raw": "1000000000000000000",
            "mode": "execute",
            "purpose": "test lido wrap",
            "approval_token": lido_approval,
            "network": "ethereum",
        },
    )
    assert lido_executed.ok is True
    assert lido_executed.data["hash"].startswith("0x")
    assert lido_executed.data["approve_hash"].startswith("0x")

    lido_withdrawals = await adapter.invoke("get_evm_lido_withdrawal_requests", {"network": "ethereum"})
    assert lido_withdrawals.ok is True
    assert lido_withdrawals.data["request_count"] == 2
    assert lido_withdrawals.data["claimable_count"] == 1

    lido_withdrawal_preview = await adapter.invoke(
        "manage_evm_lido_withdrawal",
        {
            "operation": "request_withdrawal_steth",
            "amount_raw": "1000000000000000000",
            "mode": "preview",
            "purpose": "test lido withdraw request",
            "network": "ethereum",
        },
    )
    assert lido_withdrawal_preview.ok is True
    assert lido_withdrawal_preview.data["asset_type"] == "evm-lido-withdrawal-queue"
    assert (
        lido_withdrawal_preview.data["confirmation_summary"]["lido_withdrawal_operation"]
        == "request_withdrawal_steth"
    )
    assert (
        lido_withdrawal_preview.data["confirmation_summary"]["quote_fingerprint"]
        == "lido-withdrawal-fingerprint-1"
    )
    assert lido_withdrawal_preview.data["allowance"]["approval_required"] is True

    lido_claim_prepare = await adapter.invoke(
        "manage_evm_lido_withdrawal",
        {
            "operation": "claim_withdrawal",
            "request_id": "102",
            "mode": "prepare",
            "purpose": "test lido claim",
            "user_intent": True,
            "network": "ethereum",
        },
    )
    assert lido_claim_prepare.ok is True
    assert lido_claim_prepare.data["execution_plan_only"] is True
    assert lido_claim_prepare.data["allowance"]["approval_required"] is False

    lido_withdrawal_approval = issue_approval_token(
        tool_name="manage_evm_lido_withdrawal",
        network="ethereum",
        summary=lido_withdrawal_preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        issued_by="test",
    )
    lido_withdrawal_executed = await adapter.invoke(
        "manage_evm_lido_withdrawal",
        {
            "operation": "request_withdrawal_steth",
            "amount_raw": "1000000000000000000",
            "mode": "execute",
            "purpose": "test lido withdraw request",
            "approval_token": lido_withdrawal_approval,
            "network": "ethereum",
        },
    )
    assert lido_withdrawal_executed.ok is True
    assert lido_withdrawal_executed.data["hash"].startswith("0x")
    assert lido_withdrawal_executed.data["approve_hash"].startswith("0x")

    lido_claim_preview = await adapter.invoke(
        "manage_evm_lido_withdrawal",
        {
            "operation": "claim_withdrawal",
            "request_id": "102",
            "mode": "preview",
            "purpose": "test lido claim",
            "network": "ethereum",
        },
    )
    assert lido_claim_preview.ok is True
    assert lido_claim_preview.data["withdrawal_request"]["claimable"] is True

    lido_claim_approval = issue_approval_token(
        tool_name="manage_evm_lido_withdrawal",
        network="ethereum",
        summary=lido_claim_preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        issued_by="test",
    )
    lido_claim_executed = await adapter.invoke(
        "manage_evm_lido_withdrawal",
        {
            "operation": "claim_withdrawal",
            "request_id": "102",
            "mode": "execute",
            "purpose": "test lido claim",
            "approval_token": lido_claim_approval,
            "network": "ethereum",
        },
    )
    assert lido_claim_executed.ok is True
    assert lido_claim_executed.data["hash"].startswith("0x")
    assert lido_claim_executed.data["approve_hash"] is None

    swap_preview = await adapter.invoke(
        "swap_evm_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "token_out": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000",
            "mode": "preview",
            "purpose": "test evm swap",
        },
    )
    assert swap_preview.ok is True
    assert swap_preview.data["asset_type"] == "evm-swap"
    # A preview must carry mode="preview" so the host bridge caches it for
    # auto-approval at execute; without it, preview -> execute fails with
    # "confirmation context expired".
    assert swap_preview.data["mode"] == "preview"
    assert swap_preview.data["estimated_output_amount_raw"] == "995000"
    assert swap_preview.data["estimated_output_amount_ui"] == "0.995"
    assert swap_preview.data["quote_fingerprint"] == "evm-swap-fingerprint-1"
    assert swap_preview.data["estimated_approval_fee_wei"] == "28000000000000"
    assert swap_preview.data["swap_transaction"]["data_hash"] == "swap-data-hash-1"
    assert swap_preview.data["minimum_output_amount_raw"] == "985050"
    assert swap_preview.data["slippage_bps"] == 100

    lifi_cross_chain_preview = await adapter.invoke(
        "swap_evm_lifi_cross_chain_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "destination_chain": "solana",
            "output_token": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "destination_address": "ENsytooJVSZyNHbxvueUeX8Am8gcNqPivVVE8USCBiy5",
            "amount_in_raw": "1000000",
            "slippage": 0.01,
            "mode": "preview",
            "purpose": "test evm lifi cross-chain swap",
        },
    )
    assert lifi_cross_chain_preview.ok is True
    assert lifi_cross_chain_preview.data["asset_type"] == "evm-lifi-cross-chain-swap"
    assert lifi_cross_chain_preview.data["swap_provider"] == "lifi"
    assert lifi_cross_chain_preview.data["tool"] == "across"
    assert lifi_cross_chain_preview.data["minimum_output_amount_raw"] == "996000"

    lifi_evm_to_evm_preview = await adapter.invoke(
        "swap_evm_lifi_cross_chain_tokens",
        {
            "token_in": "0x0000000000000000000000000000000000000000",
            "destination_chain": "base",
            "output_token": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "destination_address": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000000000000",
            "slippage": 0.01,
            "mode": "preview",
            "purpose": "test evm lifi evm-to-evm cross-chain swap",
        },
    )
    assert lifi_evm_to_evm_preview.ok is True
    assert lifi_evm_to_evm_preview.data["destination_chain"] == "base"
    assert lifi_evm_to_evm_preview.data["destination_chain_id"] == "8453"
    assert (
        lifi_evm_to_evm_preview.data["confirmation_summary"]["output_token"]
        == "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    )

    lifi_native_alias_preview = await adapter.invoke(
        "swap_evm_lifi_cross_chain_tokens",
        {
            "token_in": "eth",
            "destination_chain": "base",
            "output_token": "native",
            "destination_address": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000000000000",
            "slippage": 0.01,
            "mode": "preview",
            "purpose": "test evm lifi native alias approval binding",
        },
    )
    assert lifi_native_alias_preview.ok is True
    assert (
        lifi_native_alias_preview.data["confirmation_summary"]["token_in"]
        == "0x0000000000000000000000000000000000000000"
    )
    assert (
        lifi_native_alias_preview.data["confirmation_summary"]["output_token"]
        == "0x0000000000000000000000000000000000000000"
    )
    lifi_native_alias_approval = issue_approval_token(
        tool_name="swap_evm_lifi_cross_chain_tokens",
        network="ethereum",
        summary=lifi_native_alias_preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        issued_by="test",
    )
    lifi_native_alias_execute = await adapter.invoke(
        "swap_evm_lifi_cross_chain_tokens",
        {
            "token_in": "eth",
            "destination_chain": "8453",
            "output_token": "native",
            "destination_address": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000000000000",
            "slippage": 0.01,
            "mode": "execute",
            "purpose": "test evm lifi native alias approval binding",
            "approval_token": lifi_native_alias_approval,
        },
    )
    assert lifi_native_alias_execute.ok is True
    assert lifi_native_alias_execute.data["hash"].startswith("0x")

    native_velora_preview = await adapter.invoke(
        "swap_evm_tokens",
        {
            "token_in": "eth",
            "token_out": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000000000000",
            "mode": "preview",
            "purpose": "test evm velora native alias approval binding",
        },
    )
    assert native_velora_preview.ok is True
    assert (
        native_velora_preview.data["confirmation_summary"]["token_in"]
        == "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    )
    native_velora_approval = issue_approval_token(
        tool_name="swap_evm_tokens",
        network="ethereum",
        summary=native_velora_preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        issued_by="test",
    )
    native_velora_execute = await adapter.invoke(
        "swap_evm_tokens",
        {
            "token_in": "eth",
            "token_out": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000000000000",
            "mode": "execute",
            "purpose": "test evm velora native alias approval binding",
            "approval_token": native_velora_approval,
        },
    )
    assert native_velora_execute.ok is True
    assert (
        native_velora_execute.data["token_in"]
        == "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    )
    assert native_velora_execute.data["hash"].startswith("0x")

    native_velora_output_preview = await adapter.invoke(
        "swap_evm_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "token_out": "eth",
            "amount_in_raw": "1000000",
            "mode": "preview",
            "purpose": "test evm velora native output alias approval binding",
        },
    )
    assert native_velora_output_preview.ok is True
    assert (
        native_velora_output_preview.data["confirmation_summary"]["token_out"]
        == "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    )
    native_velora_output_approval = issue_approval_token(
        tool_name="swap_evm_tokens",
        network="ethereum",
        summary=native_velora_output_preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        issued_by="test",
    )
    native_velora_output_execute = await adapter.invoke(
        "swap_evm_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "token_out": "eth",
            "amount_in_raw": "1000000",
            "mode": "execute",
            "purpose": "test evm velora native output alias approval binding",
            "approval_token": native_velora_output_approval,
        },
    )
    assert native_velora_output_execute.ok is True
    assert (
        native_velora_output_execute.data["token_out"]
        == "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    )
    assert native_velora_output_execute.data["hash"].startswith("0x")

    lifi_cross_chain_prepare = await adapter.invoke(
        "swap_evm_lifi_cross_chain_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "destination_chain": "solana",
            "output_token": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "destination_address": "ENsytooJVSZyNHbxvueUeX8Am8gcNqPivVVE8USCBiy5",
            "amount_in_raw": "1000000",
            "slippage": 0.01,
            "mode": "prepare",
            "purpose": "test evm lifi cross-chain swap",
            "user_intent": True,
        },
    )
    assert lifi_cross_chain_prepare.ok is True
    assert lifi_cross_chain_prepare.data["execution_plan_only"] is True

    lifi_cross_chain_approval = issue_approval_token(
        tool_name="swap_evm_lifi_cross_chain_tokens",
        network="ethereum",
        summary=lifi_cross_chain_preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        issued_by="test",
    )
    lifi_cross_chain_execute = await adapter.invoke(
        "swap_evm_lifi_cross_chain_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "destination_chain": "solana",
            "output_token": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "destination_address": "ENsytooJVSZyNHbxvueUeX8Am8gcNqPivVVE8USCBiy5",
            "amount_in_raw": "1000000",
            "slippage": 0.01,
            "mode": "execute",
            "purpose": "test evm lifi cross-chain swap",
            "approval_token": lifi_cross_chain_approval,
        },
    )
    assert lifi_cross_chain_execute.ok is True
    assert lifi_cross_chain_execute.data["hash"].startswith("0x")
    assert lifi_cross_chain_execute.data["minimum_output_amount_raw"] == "996000"

    preview = await adapter.invoke(
        "transfer_evm_native",
        {
            "recipient": "0x3333333333333333333333333333333333333333",
            "amount_wei": "10000000000000000",
            "mode": "preview",
            "purpose": "test evm transfer",
        },
    )
    assert preview.ok is True
    assert preview.data["estimated_fee_wei"] == "21000000000000"

    prepared = await adapter.invoke(
        "transfer_evm_token",
        {
            "token_address": "0x2222222222222222222222222222222222222222",
            "recipient": "0x3333333333333333333333333333333333333333",
            "amount_raw": "5000000",
            "mode": "prepare",
            "purpose": "test token transfer",
            "user_intent": True,
        },
    )
    assert prepared.ok is True
    assert prepared.data["execution_plan_only"] is True
    assert prepared.data["token_metadata"]["decimals"] == 6

    swap_approval = issue_approval_token(
        tool_name="swap_evm_tokens",
        network="ethereum",
        summary=swap_preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        issued_by="test",
    )
    swap_executed = await adapter.invoke(
        "swap_evm_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "token_out": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000",
            "mode": "execute",
            "purpose": "test evm swap",
            "approval_token": swap_approval,
        },
    )
    assert swap_executed.ok is True
    assert swap_executed.data["hash"].startswith("0x")
    assert swap_executed.data["allowance"]["approval_required"] is False
    assert swap_executed.data["simulation"]["ok"] is True
    assert swap_preview.data["confirmation_summary"]["quote_fingerprint"] == "evm-swap-fingerprint-1"
    assert swap_preview.data["confirmation_summary"]["minimum_output_amount_raw"] == "985050"
    assert swap_preview.data["confirmation_summary"]["slippage_bps"] == 100

    class NoRepreviewEvmBackend(FakeEvmBackend):
        def __init__(self) -> None:
            self.preview_calls = 0

        async def preview_evm_swap(
            self,
            *,
            token_in: str,
            token_out: str,
            amount_in_raw: str,
        ) -> dict:
            self.preview_calls += 1
            if self.preview_calls > 1:
                raise WalletBackendError("execute should not request a second preview")
            return await super().preview_evm_swap(
                token_in=token_in,
                token_out=token_out,
                amount_in_raw=amount_in_raw,
            )

    no_repreview_backend = NoRepreviewEvmBackend()
    no_repreview_adapter = OpenClawWalletAdapter(no_repreview_backend)
    no_repreview_preview = await no_repreview_adapter.invoke(
        "swap_evm_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "token_out": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000",
            "mode": "preview",
            "purpose": "test evm swap",
        },
    )
    no_repreview_approval = issue_approval_token(
        tool_name="swap_evm_tokens",
        network="ethereum",
        summary=no_repreview_preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        issued_by="test",
    )
    no_repreview_execute = await no_repreview_adapter.invoke(
        "swap_evm_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "token_out": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000",
            "mode": "execute",
            "purpose": "test evm swap",
            "approval_token": no_repreview_approval,
        },
    )
    assert no_repreview_execute.ok is True
    assert no_repreview_backend.preview_calls == 1

    class QuoteChangedEvmBackend(FakeEvmBackend):
        async def send_evm_swap(
            self,
            *,
            token_in: str,
            token_out: str,
            amount_in_raw: str,
            expected_quote_fingerprint: str | None = None,
            minimum_output_amount_raw: str | None = None,
        ) -> dict:
            raise WalletBackendError(
                "Swap quote changed since preview. Generate a new preview and approval before execute.",
                code="swap_quote_changed",
                details={"source": "wdk-evm-wallet"},
            )

    quote_changed_adapter = OpenClawWalletAdapter(QuoteChangedEvmBackend())
    quote_changed_preview = await quote_changed_adapter.invoke(
        "swap_evm_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "token_out": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000",
            "mode": "preview",
            "purpose": "test evm swap",
        },
    )
    quote_changed_approval = issue_approval_token(
        tool_name="swap_evm_tokens",
        network="ethereum",
        summary=quote_changed_preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        issued_by="test",
    )
    quote_changed = await quote_changed_adapter.invoke(
        "swap_evm_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "token_out": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000",
            "mode": "execute",
            "purpose": "test evm swap",
            "approval_token": quote_changed_approval,
        },
    )
    assert quote_changed.ok is False
    assert quote_changed.error_code == "swap_quote_changed"

    class CleanupFailedEvmBackend(FakeEvmBackend):
        async def send_evm_swap(
            self,
            *,
            token_in: str,
            token_out: str,
            amount_in_raw: str,
            expected_quote_fingerprint: str | None = None,
            minimum_output_amount_raw: str | None = None,
        ) -> dict:
            raise WalletBackendError(
                "Swap failed after approval and automatic allowance restore did not complete.",
                code="swap_cleanup_failed",
                details={"source": "wdk-evm-wallet", "cleanup": {"attempted": True, "restored": False}},
            )

    cleanup_failed_adapter = OpenClawWalletAdapter(CleanupFailedEvmBackend())
    cleanup_failed_preview = await cleanup_failed_adapter.invoke(
        "swap_evm_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "token_out": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000",
            "mode": "preview",
            "purpose": "test evm swap",
        },
    )
    cleanup_failed_approval = issue_approval_token(
        tool_name="swap_evm_tokens",
        network="ethereum",
        summary=cleanup_failed_preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        issued_by="test",
    )
    cleanup_failed = await cleanup_failed_adapter.invoke(
        "swap_evm_tokens",
        {
            "token_in": "0x2222222222222222222222222222222222222222",
            "token_out": "0x3333333333333333333333333333333333333333",
            "amount_in_raw": "1000000",
            "mode": "execute",
            "purpose": "test evm swap",
            "approval_token": cleanup_failed_approval,
        },
    )
    assert cleanup_failed.ok is False
    assert cleanup_failed.error_code == "swap_cleanup_failed"

    approval = issue_approval_token(
        tool_name="transfer_evm_native",
        network="ethereum",
        summary=preview.data["confirmation_summary"],
        mainnet_confirmed=True,
        issued_by="test",
    )
    executed = await adapter.invoke(
        "transfer_evm_native",
        {
            "recipient": "0x3333333333333333333333333333333333333333",
            "amount_wei": "10000000000000000",
            "mode": "execute",
            "purpose": "test evm transfer",
            "approval_token": approval,
        },
    )
    assert executed.ok is True
    assert executed.data["hash"].startswith("0x")

    class LockedEvmBackend(FakeEvmBackend):
        async def get_balance(self, address: str | None = None) -> dict:
            raise WalletBackendError(
                "Wallet is locked. Unlock it first or provide seedPhrase explicitly.",
                code="wallet_locked",
                details={"source": "wdk-evm-wallet"},
            )

    shaped_error = await OpenClawWalletAdapter(LockedEvmBackend()).invoke("get_wallet_balance", {})
    assert shaped_error.ok is False
    assert shaped_error.error_code == "wallet_locked"
    assert shaped_error.error_details == {"source": "wdk-evm-wallet"}


def main() -> None:
    temp_home = Path("/tmp/openclaw-evm-adapter-smoke")
    if temp_home.exists():
        shutil.rmtree(temp_home)
    install_test_sealed_secrets(
        temp_home,
        boot_key="test-boot-key-for-evm-adapter-smoke",
        master_key="test-master-key-for-evm-adapter-smoke",
        approval_secret="test-approval-secret-for-evm-adapter-smoke",
    )
    asyncio.run(_main())
    print("smoke_openclaw_evm_adapter: ok")


if __name__ == "__main__":
    main()
