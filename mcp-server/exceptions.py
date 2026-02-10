"""Custom exceptions for the MCP server."""


class ProviderError(Exception):
    """A data provider failed to return data."""

    def __init__(self, provider: str, message: str):
        self.provider = provider
        super().__init__(f"[{provider}] {message}")


class RateLimitError(ProviderError):
    """Provider rate limit exceeded."""

    def __init__(self, provider: str, retry_after: float | None = None):
        self.retry_after = retry_after
        msg = "Rate limit exceeded"
        if retry_after:
            msg += f" (retry after {retry_after:.1f}s)"
        super().__init__(provider, msg)


class AllProvidersFailedError(Exception):
    """All providers in a fallback chain failed."""

    def __init__(self, errors: list[Exception]):
        self.errors = errors
        details = "; ".join(str(e) for e in errors)
        super().__init__(f"All providers failed: {details}")
