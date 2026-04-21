from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .constants import PENDING_TTL_SECONDS, STARTING_BALANCES, SUPPORTED_ASSETS
from .models import PendingAction, TransactionRecord


UTC = timezone.utc


class Storage:
    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_user_id INTEGER NOT NULL UNIQUE,
                    username TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS balances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    asset TEXT NOT NULL,
                    amount REAL NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, asset)
                );

                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    from_asset TEXT NOT NULL,
                    to_asset TEXT NOT NULL,
                    from_amount REAL NOT NULL,
                    to_amount REAL NOT NULL,
                    fee_amount REAL NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pending_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                """
            )

    def get_or_create_user(self, telegram_user_id: int, username: str | None) -> int:
        created_at = self._now_iso()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM users WHERE telegram_user_id = ?",
                (telegram_user_id,),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET username = ? WHERE id = ?",
                    (username, row["id"]),
                )
                user_id = int(row["id"])
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO users (telegram_user_id, username, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (telegram_user_id, username, created_at),
                )
                user_id = int(cursor.lastrowid)

            self._ensure_starting_balances(conn, user_id)
            return user_id

    def reset_user(self, user_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM balances WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM pending_actions WHERE user_id = ?", (user_id,))
            self._ensure_starting_balances(conn, user_id)

    def _ensure_starting_balances(self, conn: sqlite3.Connection, user_id: int) -> None:
        now = self._now_iso()
        for asset in SUPPORTED_ASSETS:
            amount = float(STARTING_BALANCES[asset])
            conn.execute(
                """
                INSERT INTO balances (user_id, asset, amount, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, asset)
                DO NOTHING
                """,
                (user_id, asset, amount, now),
            )

    def get_balances(self, user_id: int) -> dict[str, float]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT asset, amount FROM balances WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        return {str(row["asset"]): float(row["amount"]) for row in rows}

    def replace_balances(self, user_id: int, balances: dict[str, float]) -> None:
        now = self._now_iso()
        with self._connect() as conn:
            for asset, amount in balances.items():
                conn.execute(
                    """
                    UPDATE balances
                    SET amount = ?, updated_at = ?
                    WHERE user_id = ? AND asset = ?
                    """,
                    (float(amount), now, user_id, asset),
                )

    def insert_transaction(self, user_id: int, record: TransactionRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO transactions (
                    user_id, type, from_asset, to_asset, from_amount,
                    to_amount, fee_amount, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    record.type,
                    record.from_asset,
                    record.to_asset,
                    record.from_amount,
                    record.to_amount,
                    record.fee_amount,
                    "executed",
                    record.created_at,
                ),
            )

    def list_transactions(self, user_id: int, limit: int = 10) -> list[sqlite3.Row]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT type, from_asset, to_asset, from_amount, to_amount, fee_amount, created_at
                FROM transactions
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return list(rows)

    def put_pending_action(self, user_id: int, action_type: str, payload: dict[str, Any]) -> PendingAction:
        self.clear_pending_actions(user_id)
        now = datetime.now(tz=UTC)
        expires_at = now + timedelta(seconds=PENDING_TTL_SECONDS)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO pending_actions (user_id, action_type, payload_json, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    action_type,
                    json.dumps(payload, ensure_ascii=False),
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )
            pending_id = int(cursor.lastrowid)
        return PendingAction(
            id=pending_id,
            user_id=user_id,
            action_type=action_type,
            payload=payload,
            expires_at=expires_at,
        )

    def get_pending_action(self, user_id: int, pending_id: int | None = None) -> PendingAction | None:
        self._purge_expired_actions(user_id)
        query = """
            SELECT id, user_id, action_type, payload_json, expires_at
            FROM pending_actions
            WHERE user_id = ?
        """
        params: list[Any] = [user_id]
        if pending_id is not None:
            query += " AND id = ?"
            params.append(pending_id)
        query += " ORDER BY id DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        if not row:
            return None
        return PendingAction(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            action_type=str(row["action_type"]),
            payload=json.loads(str(row["payload_json"])),
            expires_at=datetime.fromisoformat(str(row["expires_at"])),
        )

    def clear_pending_actions(self, user_id: int, pending_id: int | None = None) -> None:
        with self._connect() as conn:
            if pending_id is None:
                conn.execute("DELETE FROM pending_actions WHERE user_id = ?", (user_id,))
            else:
                conn.execute(
                    "DELETE FROM pending_actions WHERE user_id = ? AND id = ?",
                    (user_id, pending_id),
                )

    def _purge_expired_actions(self, user_id: int) -> None:
        now = self._now_iso()
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM pending_actions WHERE user_id = ? AND expires_at <= ?",
                (user_id, now),
            )

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(tz=UTC).isoformat()
