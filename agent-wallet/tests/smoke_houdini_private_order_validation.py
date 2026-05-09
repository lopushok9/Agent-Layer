"""Smoke test for Houdini private order validation semantics."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.wallet_layer.base import WalletBackendError
from agent_wallet.wallet_layer.solana import SolanaWalletBackend


def main() -> None:
    backend = SolanaWalletBackend(
        rpc_url="http://127.0.0.1:8899",
        network="mainnet",
        address="11111111111111111111111111111111",
        sign_only=True,
    )

    preview = {
        "destination_address": "GkcdCet7HRRCS3PypzwZHgd5uzVT4A9uoKrUvXXj31Rf",
        "input_token_id": "usdc-token-id",
        "output_token_id": "usdc-token-id",
        "input_amount_ui": 30,
        "input_token_address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "output_token_address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "input_token_symbol": "USDC",
        "output_token_symbol": "USDC",
    }

    order_with_display_symbol_drift = {
        "receiverAddress": "GkcdCet7HRRCS3PypzwZHgd5uzVT4A9uoKrUvXXj31Rf",
        "anonymous": True,
        "from": "usdc-token-id",
        "to": "usdc-token-id",
        "fromAddress": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "toAddress": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "inAmount": 30,
        "inSymbol": "USDC.e",
        "outSymbol": "USDC.e",
    }
    validated = backend._validate_houdini_order_against_preview(
        order=order_with_display_symbol_drift,
        preview=preview,
    )
    assert validated["validated"] is True
    assert len(validated["warnings"]) == 2
    assert "display symbol" in validated["warnings"][0]

    order_with_real_input_mismatch = {
        **order_with_display_symbol_drift,
        "from": "usdt-token-id",
    }
    try:
        backend._validate_houdini_order_against_preview(
            order=order_with_real_input_mismatch,
            preview=preview,
        )
    except WalletBackendError as exc:
        assert "input token id does not match" in str(exc)
    else:
        raise AssertionError("Expected token id mismatch to be rejected.")

    preview_with_amount = {
        **preview,
        "estimated_output_amount_ui": 29.254723,
    }
    order_with_small_output_drift = {
        **order_with_display_symbol_drift,
        "outAmount": 29.2521,
    }
    output_validation = backend._validate_houdini_order_output_against_preview(
        order=order_with_small_output_drift,
        preview=preview_with_amount,
    )
    assert output_validation["validated"] is True
    assert output_validation["warnings"]

    order_with_large_output_drift = {
        **order_with_display_symbol_drift,
        "outAmount": 28.8,
    }
    try:
        backend._validate_houdini_order_output_against_preview(
            order=order_with_large_output_drift,
            preview=preview_with_amount,
        )
    except WalletBackendError as exc:
        assert "fell materially below" in str(exc)
    else:
        raise AssertionError("Expected large output drift to be rejected.")

    print("smoke_houdini_private_order_validation: ok")


if __name__ == "__main__":
    main()
