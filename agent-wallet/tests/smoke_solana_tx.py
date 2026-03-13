"""Basic serialization test for the minimal Solana transfer builder."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.solana_tx import (  # noqa: E402
    build_legacy_sol_transfer_message,
    encode_shortvec,
    encode_transaction_base64,
    serialize_legacy_transaction,
)


def main() -> None:
    assert encode_shortvec(0) == b"\x00"
    assert encode_shortvec(127) == b"\x7f"
    assert encode_shortvec(128) == b"\x80\x01"

    sender = "11111111111111111111111111111111"
    recipient = "11111111111111111111111111111111"
    recent_blockhash = "11111111111111111111111111111111"
    message = build_legacy_sol_transfer_message(
        sender=sender,
        recipient=recipient,
        recent_blockhash=recent_blockhash,
        lamports=1_000_000,
    )
    assert len(message) > 100

    fake_signature = b"\x11" * 64
    tx_bytes = serialize_legacy_transaction(fake_signature, message)
    assert len(tx_bytes) == len(message) + 65
    assert encode_transaction_base64(tx_bytes)

    print("smoke_solana_tx: ok")


if __name__ == "__main__":
    main()
