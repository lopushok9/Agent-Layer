"""Wallet package exceptions."""


class ProviderError(Exception):
    """A provider failed to return data."""

    def __init__(self, provider: str, message: str):
        self.provider = provider
        super().__init__(f"[{provider}] {message}")
