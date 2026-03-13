"""Minimal legacy Solana transaction builder for native SOL transfers."""

from __future__ import annotations

import base64
import struct

from agent_wallet.wallet_layer.base58 import b58decode

SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"
SYSTEM_TRANSFER_INSTRUCTION = 2


def encode_shortvec(value: int) -> bytes:
    """Encode an integer using Solana's compact-u16/shortvec format."""
    if value < 0:
        raise ValueError("shortvec cannot encode negative values")

    encoded = bytearray()
    remaining = value
    while True:
        element = remaining & 0x7F
        remaining >>= 7
        if remaining:
            encoded.append(element | 0x80)
        else:
            encoded.append(element)
            break
    return bytes(encoded)


def build_legacy_sol_transfer_message(
    sender: str,
    recipient: str,
    recent_blockhash: str,
    lamports: int,
) -> bytes:
    """Build a legacy transaction message for a native SOL transfer."""
    if lamports <= 0:
        raise ValueError("lamports must be greater than zero")

    sender_key = b58decode(sender)
    recipient_key = b58decode(recipient)
    system_program_key = b58decode(SYSTEM_PROGRAM_ID)
    blockhash_bytes = b58decode(recent_blockhash)

    if len(sender_key) != 32 or len(recipient_key) != 32 or len(system_program_key) != 32:
        raise ValueError("All account keys must decode to 32 bytes")
    if len(blockhash_bytes) != 32:
        raise ValueError("Recent blockhash must decode to 32 bytes")

    header = bytes(
        [
            1,  # num_required_signatures
            0,  # num_readonly_signed_accounts
            1,  # num_readonly_unsigned_accounts (system program)
        ]
    )
    account_keys = [sender_key, recipient_key, system_program_key]
    message = bytearray()
    message.extend(header)
    message.extend(encode_shortvec(len(account_keys)))
    for account_key in account_keys:
        message.extend(account_key)
    message.extend(blockhash_bytes)

    instruction_data = struct.pack("<IQ", SYSTEM_TRANSFER_INSTRUCTION, lamports)
    compiled_instruction = bytearray()
    compiled_instruction.append(2)  # system program index
    compiled_instruction.extend(encode_shortvec(2))
    compiled_instruction.extend(bytes([0, 1]))  # sender, recipient
    compiled_instruction.extend(encode_shortvec(len(instruction_data)))
    compiled_instruction.extend(instruction_data)

    message.extend(encode_shortvec(1))
    message.extend(compiled_instruction)
    return bytes(message)


def serialize_legacy_transaction(signature: bytes, message: bytes) -> bytes:
    """Serialize a signed legacy transaction."""
    if len(signature) != 64:
        raise ValueError("Solana signatures must be 64 bytes")
    payload = bytearray()
    payload.extend(encode_shortvec(1))
    payload.extend(signature)
    payload.extend(message)
    return bytes(payload)


def encode_transaction_base64(transaction_bytes: bytes) -> str:
    """Encode serialized transaction bytes for sendTransaction RPC."""
    return base64.b64encode(transaction_bytes).decode("ascii")
