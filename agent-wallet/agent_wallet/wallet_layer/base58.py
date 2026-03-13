"""Minimal base58 helpers to avoid extra runtime dependencies."""

from __future__ import annotations

_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_ALPHABET_INDEX = {char: index for index, char in enumerate(_ALPHABET)}


def b58encode(raw: bytes) -> str:
    """Encode bytes into a base58 string."""
    if not raw:
        return ""

    zeros = 0
    for byte in raw:
        if byte == 0:
            zeros += 1
        else:
            break

    value = int.from_bytes(raw, "big")
    encoded = []
    while value > 0:
        value, remainder = divmod(value, 58)
        encoded.append(_ALPHABET[remainder])

    return ("1" * zeros) + "".join(reversed(encoded or ["1"]))


def b58decode(value: str) -> bytes:
    """Decode a base58 string into bytes."""
    cleaned = value.strip()
    if not cleaned:
        return b""

    number = 0
    for char in cleaned:
        if char not in _ALPHABET_INDEX:
            raise ValueError(f"Invalid base58 character: {char!r}")
        number = (number * 58) + _ALPHABET_INDEX[char]

    decoded = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    leading_zeros = len(cleaned) - len(cleaned.lstrip("1"))
    return (b"\x00" * leading_zeros) + decoded
