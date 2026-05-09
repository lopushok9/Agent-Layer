"""Wallet package exceptions."""


class ProviderError(Exception):
    """A provider failed to return data."""

    def __init__(self, provider: str, message: str, *, details: dict | None = None):
        self.provider = provider
        self.details = dict(details) if isinstance(details, dict) else None
        super().__init__(f"[{provider}] {message}")
