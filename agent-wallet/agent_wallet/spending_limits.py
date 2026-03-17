"""In-process spending ledger with configurable per-transaction, hourly, and daily limits.

All limits default to ``0`` (unlimited).  When a limit is set, every
``check_and_record`` call verifies that the requested spend would not
exceed the configured thresholds.  If a limit would be breached, a
``WalletBackendError`` is raised *before* the on-chain transaction is
submitted.

Thread-safe: uses ``threading.Lock`` for concurrent access.  For
multi-instance deployments, replace ``SpendingLedger`` with a shared
store (Redis / SQLite) behind the same interface.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from agent_wallet.wallet_layer.base import WalletBackendError

# ---------------------------------------------------------------------------
# 1 SOL = 1_000_000_000 lamports
# ---------------------------------------------------------------------------
LAMPORTS_PER_SOL = 1_000_000_000


@dataclass(frozen=True)
class SpendingConfig:
    """Configurable spending limits (all values in lamports, 0 = unlimited)."""

    max_per_tx_lamports: int = 0
    max_hourly_lamports: int = 0
    max_daily_lamports: int = 0
    max_txs_per_minute: int = 0


class SpendingLedger:
    """Records executed spends and rejects operations that exceed limits."""

    def __init__(self, config: SpendingConfig) -> None:
        self.config = config
        self._entries: list[tuple[float, int]] = []  # (monotonic-ts, lamports)
        self._lock = threading.Lock()

    # -- public API ----------------------------------------------------------

    def check_and_record(self, lamports: int) -> None:
        """Validate *lamports* against limits and record the spend.

        Raises ``WalletBackendError`` if any limit would be exceeded.
        """
        with self._lock:
            now = time.monotonic()
            self._cleanup(now)

            # Per-transaction cap
            if self.config.max_per_tx_lamports > 0:
                if lamports > self.config.max_per_tx_lamports:
                    raise WalletBackendError(
                        f"Transaction exceeds per-tx limit: "
                        f"{lamports} > {self.config.max_per_tx_lamports} lamports "
                        f"({self.config.max_per_tx_lamports / LAMPORTS_PER_SOL:.4f} SOL)."
                    )

            # Transactions-per-minute rate limit
            if self.config.max_txs_per_minute > 0:
                recent_count = sum(1 for ts, _ in self._entries if now - ts < 60)
                if recent_count >= self.config.max_txs_per_minute:
                    raise WalletBackendError(
                        f"Transaction rate limit exceeded: "
                        f"max {self.config.max_txs_per_minute} txs/minute."
                    )

            # Hourly cumulative cap
            if self.config.max_hourly_lamports > 0:
                hourly_total = sum(lam for ts, lam in self._entries if now - ts < 3600)
                if hourly_total + lamports > self.config.max_hourly_lamports:
                    raise WalletBackendError(
                        f"Hourly spending limit exceeded: "
                        f"would reach {(hourly_total + lamports) / LAMPORTS_PER_SOL:.4f} SOL, "
                        f"limit is {self.config.max_hourly_lamports / LAMPORTS_PER_SOL:.4f} SOL."
                    )

            # Daily cumulative cap
            if self.config.max_daily_lamports > 0:
                daily_total = sum(lam for ts, lam in self._entries if now - ts < 86400)
                if daily_total + lamports > self.config.max_daily_lamports:
                    raise WalletBackendError(
                        f"Daily spending limit exceeded: "
                        f"would reach {(daily_total + lamports) / LAMPORTS_PER_SOL:.4f} SOL, "
                        f"limit is {self.config.max_daily_lamports / LAMPORTS_PER_SOL:.4f} SOL."
                    )

            self._entries.append((now, lamports))

    # -- internal ------------------------------------------------------------

    def _cleanup(self, now: float) -> None:
        """Evict entries older than 24 h to bound memory usage."""
        self._entries = [(ts, lam) for ts, lam in self._entries if now - ts < 86400]
