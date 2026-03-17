"""In-memory nonce registry to prevent approval token replay.

Each approval token can be used exactly once. After successful verification,
the token fingerprint is recorded and any subsequent attempt to reuse it is
rejected with a clear error.

For single-process deployments the in-memory registry is sufficient. For
multi-instance deployments, swap ``_registry`` for a shared store (Redis,
SQLite, etc.) behind the same interface.
"""

from __future__ import annotations

import hashlib
import threading
import time

from agent_wallet.wallet_layer.base import WalletBackendError


class NonceRegistry:
    """Thread-safe, self-cleaning registry of consumed approval-token fingerprints."""

    def __init__(self, max_age_seconds: int = 900) -> None:
        self._used: dict[str, float] = {}
        self._lock = threading.Lock()
        self._max_age = max_age_seconds

    def mark_used(self, token_fingerprint: str) -> None:
        """Record a token as consumed.  Raises on duplicate."""
        with self._lock:
            self._cleanup()
            if token_fingerprint in self._used:
                raise WalletBackendError(
                    "Approval token has already been used. "
                    "Each approval token is single-use — request a new one."
                )
            self._used[token_fingerprint] = time.monotonic()

    def _cleanup(self) -> None:
        cutoff = time.monotonic() - self._max_age
        expired = [k for k, t in self._used.items() if t < cutoff]
        for k in expired:
            del self._used[k]


# Module-level singleton — shared across the process.
_registry = NonceRegistry()


def require_single_use(token: str) -> None:
    """Reject reused approval tokens.

    Computes a SHA-256 fingerprint of the raw token string and checks it
    against the registry.  Safe to call from async or sync contexts because
    the registry uses an ordinary ``threading.Lock``.
    """
    fp = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    _registry.mark_used(fp)
