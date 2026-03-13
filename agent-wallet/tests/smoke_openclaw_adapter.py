"""Basic smoke test for the OpenClaw wallet adapter without external RPC."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
            "source": "fake",
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


async def main() -> None:
    adapter = OpenClawWalletAdapter(FakeBackend())
    bundle = build_openclaw_plugin_bundle(FakeBackend())

    assert len(adapter.list_tools()) == 11
    assert bundle["manifest"]["id"] == "agent-wallet"
    assert len(bundle["tools"]) == 11
    assert "Wallet Operator" in bundle["instructions"]

    capabilities = await adapter.invoke("get_wallet_capabilities")
    assert capabilities.ok and capabilities.data["backend"] == "fake_wallet"

    address = await adapter.invoke("get_wallet_address")
    assert address.ok and address.data["configured"] is True

    balance = await adapter.invoke("get_wallet_balance")
    assert balance.ok and balance.data["balance_native"] == 1.25

    portfolio = await adapter.invoke("get_wallet_portfolio")
    assert portfolio.ok and portfolio.data["token_count"] == 1

    prices = await adapter.invoke(
        "get_solana_token_prices",
        {"mints": ["So11111111111111111111111111111111111111112"]},
    )
    assert prices.ok and prices.data["count"] == 1

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

    denied_transfer = await adapter.invoke(
        "transfer_sol",
        {
            "recipient": "FakeRecipient1111111111111111111111111111111111",
            "amount": 0.25,
            "mode": "execute",
            "purpose": "test transfer execute",
            "user_confirmed": False,
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
    assert prepared_transfer.ok and prepared_transfer.data["transaction_format"] == "legacy"

    executed_transfer = await adapter.invoke(
        "transfer_sol",
        {
            "recipient": "FakeRecipient1111111111111111111111111111111111",
            "amount": 0.25,
            "mode": "execute",
            "purpose": "test transfer execute",
            "user_confirmed": True,
        },
    )
    assert executed_transfer.ok and executed_transfer.data["confirmed"] is True

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
            "user_confirmed": False,
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
    assert prepared_spl_transfer.ok and prepared_spl_transfer.data["transaction_format"] == "legacy"

    executed_spl_transfer = await adapter.invoke(
        "transfer_spl_token",
        {
            "recipient": "FakeRecipient1111111111111111111111111111111111",
            "mint": "So11111111111111111111111111111111111111112",
            "amount": 0.25,
            "mode": "execute",
            "purpose": "test SPL transfer execute",
            "user_confirmed": True,
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

    denied_swap = await adapter.invoke(
        "swap_solana_tokens",
        {
            "input_mint": "So11111111111111111111111111111111111111112",
            "output_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount": 0.1,
            "slippage_bps": 50,
            "mode": "execute",
            "purpose": "test swap execute",
            "user_confirmed": False,
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
    assert prepared_swap.ok and prepared_swap.data["transaction_format"] == "versioned"

    executed_swap = await adapter.invoke(
        "swap_solana_tokens",
        {
            "input_mint": "So11111111111111111111111111111111111111112",
            "output_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount": 0.1,
            "slippage_bps": 50,
            "mode": "execute",
            "purpose": "test swap execute",
            "user_confirmed": True,
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
            "user_confirmed": False,
        },
    )
    assert denied_close.ok is False

    executed_close = await adapter.invoke(
        "close_empty_token_accounts",
        {
            "limit": 4,
            "mode": "execute",
            "purpose": "test close execute",
            "user_confirmed": True,
        },
    )
    assert executed_close.ok and executed_close.data["confirmed"] is True

    airdrop = await adapter.invoke("request_devnet_airdrop", {"amount": 1.0})
    assert airdrop.ok and airdrop.data["mode"] == "airdrop"

    print("smoke_openclaw_adapter: ok")

    mainnet_backend = FakeBackend()
    mainnet_backend.network = "mainnet"
    mainnet_adapter = OpenClawWalletAdapter(mainnet_backend)

    denied_mainnet_execute = await mainnet_adapter.invoke(
        "transfer_sol",
        {
            "recipient": "FakeRecipient1111111111111111111111111111111111",
            "amount": 0.25,
            "mode": "execute",
            "purpose": "mainnet execute without extra confirm",
            "user_confirmed": True,
            "mainnet_confirmed": False,
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

    allowed_mainnet_execute = await mainnet_adapter.invoke(
        "transfer_sol",
        {
            "recipient": "FakeRecipient1111111111111111111111111111111111",
            "amount": 0.25,
            "mode": "execute",
            "purpose": "mainnet execute with extra confirm",
            "user_confirmed": True,
            "mainnet_confirmed": True,
        },
    )
    assert allowed_mainnet_execute.ok is True

    denied_mainnet_swap = await mainnet_adapter.invoke(
        "swap_solana_tokens",
        {
            "input_mint": "So11111111111111111111111111111111111111112",
            "output_mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "amount": 0.1,
            "slippage_bps": 50,
            "mode": "execute",
            "purpose": "mainnet swap execute without extra confirm",
            "user_confirmed": True,
            "mainnet_confirmed": False,
        },
    )
    assert denied_mainnet_swap.ok is False

    allowed_mainnet_balance = await mainnet_adapter.invoke("get_wallet_balance")
    assert allowed_mainnet_balance.ok is True


if __name__ == "__main__":
    asyncio.run(main())
