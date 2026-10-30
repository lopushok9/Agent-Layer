"""Anonymous telemetry ingest + storage for the AgentLayer wallet.

This module is deliberately privacy-first. It accepts ONLY a fixed allowlist of
non-identifying fields (see ``validate_event``) and persists them to a local
SQLite database. It never stores wallet addresses, balances, amounts, tx hashes,
tool arguments, seed phrases, or any secret material — anything outside the
allowlist is rejected before it reaches the database.

The store powers adoption metrics (active installs, per-host breakdown across
Claude Code / Codex / Hermes / OpenClaw, top tools, success rate) without
touching PII.

Storage note: ``TELEMETRY_DB_PATH`` defaults to a file next to this module. On
ephemeral hosts (e.g. Railway without a mounted volume) the DB resets on
redeploy — point it at a mounted volume or swap in Postgres for durable history.
"""

from __future__ import annotations

import os
import json
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any

# --- allowlist / validation rules -------------------------------------------

ALLOWED_EVENTS = {
    "tool_invoke",
    "session_start",
    "install_start",
    "install_success",
    "install_failed",
    "plugin_install_start",
    "plugin_install_success",
    "plugin_install_failed",
    "update_start",
    "update_success",
    "update_failed",
    "x402_previewed",
    "x402_preview_failed",
    "x402_payment_attempted",
    "x402_payment_not_required",
    "x402_payment_settled",
    "x402_payment_failed",
}
# Must stay a superset of the client allowlist (agent_wallet/telemetry.py and
# bin/openclaw-agent-wallet.mjs); a host missing here silently becomes "unknown".
ALLOWED_HOSTS = {"claude-code", "codex", "cursor", "hermes", "mcp", "openclaw", "unknown"}
# The BTC backend is retired: new events carrying it are counted as "unknown".
ALLOWED_BACKENDS = {
    "solana_local",
    "wdk_evm_local",
    "unknown",
    "",
}
# Write tools run as preview/execute (or intent_* for intent-bound tools).
ALLOWED_MODES = {"preview", "execute", "intent_preview", "intent_execute", ""}

_INSTALL_ID_RE = re.compile(r"^[0-9a-f\-]{8,64}$")
# Tool names are registered identifiers (get_wallet_balance, transfer_sol, ...):
# always a lowercase letter first, then [a-z0-9_], max 48. The leading-letter
# rule rejects address-like tokens (0x… hex) so the one free-text field cannot
# carry a wallet address even from a buggy client. The authoritative guarantee
# is upstream: the CLI only ever emits the invoked tool's registered name.
_TOOL_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
_VERSION_RE = re.compile(r"^[0-9A-Za-z.\-+]{1,32}$")
_SOURCE_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
_COMMAND_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
_X402_DIMENSION_RE = re.compile(r"^[a-z0-9_:.-]{1,64}$")

# Only these keys are ever read from an inbound payload. Everything else is
# dropped, so a client cannot smuggle a wallet address into an extra field.
ALLOWED_KEYS = {
    "event",
    "install_id",
    "host",
    "tool",
    "backend",
    "plugin_version",
    "ok",
    "ts",
    "source",
    "command",
    "network",
    "scheme",
    "asset_family",
    "amount_bucket",
    "settlement_status",
    "error_class",
    "mode",
}

MAX_BODY_BYTES = 2048
NPM_DOWNLOADS_PACKAGE = "@agentlayer.tech/wallet"
NPM_DOWNLOADS_SINCE = "2026-05-01"
NPM_DOWNLOADS_CACHE_TTL_SECONDS = int(os.getenv("NPM_DOWNLOADS_CACHE_TTL_SECONDS", "21600") or "21600")
NPM_DOWNLOADS_HTTP_TIMEOUT_SECONDS = float(os.getenv("NPM_DOWNLOADS_HTTP_TIMEOUT_SECONDS", "1.0") or "1.0")


class TelemetryValidationError(ValueError):
    """Raised when an inbound event violates the privacy-first allowlist."""


def validate_event(raw: Any) -> dict[str, Any]:
    """Coerce an untrusted payload into a safe, allowlisted event dict.

    Raises TelemetryValidationError on anything unexpected. The returned dict
    contains only the allowlisted keys, normalized.
    """
    if not isinstance(raw, dict):
        raise TelemetryValidationError("event must be a JSON object")

    extra = set(raw.keys()) - ALLOWED_KEYS
    if extra:
        raise TelemetryValidationError(f"unexpected fields: {sorted(extra)}")

    event = str(raw.get("event", "")).strip()
    if event not in ALLOWED_EVENTS:
        raise TelemetryValidationError(f"event not allowed: {event!r}")

    install_id = str(raw.get("install_id", "")).strip().lower()
    if not _INSTALL_ID_RE.match(install_id):
        raise TelemetryValidationError("install_id must be a uuid/hex token")

    host = str(raw.get("host", "unknown")).strip().lower()
    if host not in ALLOWED_HOSTS:
        host = "unknown"

    tool = str(raw.get("tool", "")).strip().lower()
    if event == "tool_invoke":
        if not _TOOL_RE.match(tool):
            raise TelemetryValidationError("tool must be a registered name [a-z][a-z0-9_]{0,47}")
    else:
        tool = ""

    backend = str(raw.get("backend", "")).strip().lower()
    if backend not in ALLOWED_BACKENDS:
        backend = "unknown"

    plugin_version = str(raw.get("plugin_version", "")).strip()
    if plugin_version and not _VERSION_RE.match(plugin_version):
        raise TelemetryValidationError("plugin_version has invalid characters")

    source = str(raw.get("source", "")).strip().lower()
    if source and not _SOURCE_RE.match(source):
        raise TelemetryValidationError("source has invalid characters")

    command = str(raw.get("command", "")).strip().lower().replace("-", "_")
    if command and not _COMMAND_RE.match(command):
        raise TelemetryValidationError("command has invalid characters")

    def _x402_dimension(name: str) -> str:
        value = str(raw.get(name, "")).strip().lower()
        if value and not _X402_DIMENSION_RE.match(value):
            raise TelemetryValidationError(f"{name} has invalid characters")
        return value

    mode = str(raw.get("mode", "")).strip().lower()
    if mode not in ALLOWED_MODES:
        mode = ""

    ok_raw = raw.get("ok", True)
    if not isinstance(ok_raw, bool):
        raise TelemetryValidationError("ok must be a boolean")

    # Client clock is untrusted; keep it but the server stamps its own time too.
    try:
        ts = int(raw.get("ts", 0))
    except (TypeError, ValueError):
        ts = 0

    return {
        "event": event,
        "install_id": install_id,
        "host": host,
        "tool": tool,
        "backend": backend,
        "plugin_version": plugin_version,
        "ok": 1 if ok_raw else 0,
        "ts": ts,
        "source": source,
        "command": command,
        "network": _x402_dimension("network"),
        "scheme": _x402_dimension("scheme"),
        "asset_family": _x402_dimension("asset_family"),
        "amount_bucket": _x402_dimension("amount_bucket"),
        "settlement_status": _x402_dimension("settlement_status"),
        "error_class": _x402_dimension("error_class"),
        "mode": mode if event == "tool_invoke" else "",
    }


# --- storage ----------------------------------------------------------------

_DB_LOCK = threading.Lock()
_CONN: sqlite3.Connection | None = None
_NPM_CACHE_LOCK = threading.Lock()
_NPM_CACHE: dict[str, Any] | None = None
_NPM_CACHE_TS = 0.0
_RPC_LOCK = threading.Lock()
_RPC_PENDING: dict[tuple[str, str, str, str, str, str, str], int] = {}
_RPC_FLUSH_THREAD_STARTED = False
_RPC_FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")

_CORE_WALLET_TOOLS = {
    "get_wallet_capabilities",
    "get_wallet_address",
    "get_wallet_balance",
    "get_wallet_portfolio",
    "issue_wallet_approval",
    "sign_wallet_message",
}
# Served by the MCP bridge itself (no wallet subprocess); only visible since the
# bridge started recording tool calls.
_BRIDGE_TOOLS = {
    "get_wallet_overview",
    "get_active_wallet_backend",
    "set_wallet_backend",
}


def _db_path() -> Path:
    raw = os.getenv("TELEMETRY_DB_PATH", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(__file__).resolve().parent / "telemetry.db"


def _connect() -> sqlite3.Connection:
    global _CONN
    if _CONN is not None:
        return _CONN
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            event        TEXT NOT NULL,
            install_id   TEXT NOT NULL,
            host         TEXT NOT NULL,
            tool         TEXT NOT NULL DEFAULT '',
            backend      TEXT NOT NULL DEFAULT '',
            plugin_version TEXT NOT NULL DEFAULT '',
            ok           INTEGER NOT NULL DEFAULT 1,
            client_ts    INTEGER NOT NULL DEFAULT 0,
            received_ts  INTEGER NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_received ON events(received_ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_install ON events(install_id)")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(events)").fetchall()}
    if "source" not in columns:
        conn.execute("ALTER TABLE events ADD COLUMN source TEXT NOT NULL DEFAULT ''")
    if "command" not in columns:
        conn.execute("ALTER TABLE events ADD COLUMN command TEXT NOT NULL DEFAULT ''")
    for column in ("network", "scheme", "asset_family", "amount_bucket", "settlement_status", "error_class", "mode"):
        if column not in columns:
            conn.execute(f"ALTER TABLE events ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rpc_usage_rollups (
            day            TEXT NOT NULL,
            endpoint       TEXT NOT NULL,
            network        TEXT NOT NULL,
            provider       TEXT NOT NULL,
            method         TEXT NOT NULL,
            status_bucket  TEXT NOT NULL,
            latency_bucket TEXT NOT NULL,
            count          INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (day, endpoint, network, provider, method, status_bucket, latency_bucket)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rpc_usage_day ON rpc_usage_rollups(day)")
    conn.commit()
    _CONN = conn
    return conn


def record_event(event: dict[str, Any]) -> None:
    """Persist a validated event. Caller must pass the output of validate_event."""
    received_ts = int(time.time())
    with _DB_LOCK:
        conn = _connect()
        conn.execute(
            """
            INSERT INTO events
                (event, install_id, host, tool, backend, plugin_version, ok, client_ts, received_ts, source, command,
                 network, scheme, asset_family, amount_bucket, settlement_status, error_class, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["event"],
                event["install_id"],
                event["host"],
                event["tool"],
                event["backend"],
                event["plugin_version"],
                event["ok"],
                event["ts"],
                received_ts,
                event["source"],
                event["command"],
                event["network"],
                event["scheme"],
                event["asset_family"],
                event["amount_bucket"],
                event["settlement_status"],
                event["error_class"],
                event["mode"],
            ),
        )
        conn.commit()


def _tool_category(tool: str) -> str:
    tool = str(tool or "").strip().lower()
    if not tool:
        return "other"
    if tool.startswith("x402_"):
        return "x402"
    if "autonomous" in tool:
        return "autonomous"
    if tool.startswith("get_lifi_") or tool.startswith("swap_evm_lifi_") or tool.startswith("swap_solana_lifi_"):
        return "cross_chain"
    if tool in _CORE_WALLET_TOOLS or tool in _BRIDGE_TOOLS:
        return "core_wallet"
    if tool.startswith("imd_"):
        return "imd"
    if tool == "get_transaction_activity":
        return "core_wallet"
    if tool.startswith("get_evm_") or tool.startswith("transfer_evm_") or tool == "set_evm_network":
        if any(part in tool for part in ("aave", "lido", "morpho", "uniswap", "swap_quote")):
            return "evm_defi"
        return "evm_wallet"
    if (
        tool.startswith(("manage_evm_", "swap_evm_", "rebalance_evm_", "get_morpho_"))
        or tool in {"get_uniswap_swap_quote", "search_uniswap_pairs"}
    ):
        return "evm_defi"
    if tool.startswith("get_solana_") or tool in {
        "stake_sol_native",
        "deactivate_solana_stake",
        "withdraw_solana_stake",
        "transfer_sol",
        "transfer_spl_token",
        "close_empty_token_accounts",
    }:
        if "stake" in tool or "staking" in tool or tool in {
            "transfer_sol",
            "transfer_spl_token",
            "close_empty_token_accounts",
            "get_solana_token_prices",
        }:
            return "solana_wallet"
        return "solana_defi"
    if tool.startswith("get_kamino_") or tool.startswith("kamino_"):
        return "solana_defi"
    if tool.startswith("launch_bags_") or tool == "swap_solana_tokens":
        return "solana_defi"
    return "other"


def _series_days(window_days: int) -> list[str]:
    today = date.today()
    start = today - timedelta(days=max(window_days - 1, 0))
    days: list[str] = []
    cursor = start
    while cursor <= today:
        days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return days


def _daily_series(conn: sqlite3.Connection, since_ts: int, window_days: int) -> dict[str, list[dict[str, Any]]]:
    days = _series_days(window_days)
    event_rows = conn.execute(
        """
        SELECT date(received_ts, 'unixepoch') AS day,
               COUNT(*) AS events,
               COUNT(DISTINCT install_id) AS active_installs,
               COUNT(DISTINCT CASE WHEN event = 'tool_invoke' THEN install_id END) AS wallet_active_installs,
               SUM(CASE WHEN event = 'tool_invoke' THEN 1 ELSE 0 END) AS tool_invocations,
               SUM(CASE WHEN event = 'tool_invoke' AND ok = 1 THEN 1 ELSE 0 END) AS tool_successes
        FROM ev
        WHERE received_ts >= ?
        GROUP BY date(received_ts, 'unixepoch')
        ORDER BY day ASC
        """,
        (since_ts,),
    ).fetchall()
    by_day = {
        str(row[0]): {
            "events": int(row[1] or 0),
            "active_installs": int(row[2] or 0),
            "wallet_active_installs": int(row[3] or 0),
            "tool_invocations": int(row[4] or 0),
            "tool_successes": int(row[5] or 0),
        }
        for row in event_rows
    }

    rpc_since_day = days[0] if days else date.today().isoformat()
    rpc_rows = conn.execute(
        """
        SELECT day, SUM(count) AS calls
        FROM rpc_usage_rollups
        WHERE day >= ?
        GROUP BY day
        ORDER BY day ASC
        """,
        (rpc_since_day,),
    ).fetchall()
    rpc_by_day = {str(row[0]): int(row[1] or 0) for row in rpc_rows}

    return {
        "events": [{"day": day, "count": by_day.get(day, {}).get("events", 0)} for day in days],
        "active_installs": [{"day": day, "count": by_day.get(day, {}).get("active_installs", 0)} for day in days],
        "wallet_active_installs": [{"day": day, "count": by_day.get(day, {}).get("wallet_active_installs", 0)} for day in days],
        "tool_invocations": [{"day": day, "count": by_day.get(day, {}).get("tool_invocations", 0)} for day in days],
        "tool_successes": [{"day": day, "count": by_day.get(day, {}).get("tool_successes", 0)} for day in days],
        "rpc_calls": [{"day": day, "count": rpc_by_day.get(day, 0)} for day in days],
    }


def _cumulative_wallet_installs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Unique installs by first received wallet call, across retained history."""
    rows = conn.execute(
        """
        SELECT date(first_ts, 'unixepoch'), COUNT(*) FROM (
            SELECT MIN(received_ts) AS first_ts FROM ev
            WHERE event = 'tool_invoke' GROUP BY install_id
        ) GROUP BY date(first_ts, 'unixepoch') ORDER BY 1
        """
    ).fetchall()
    if not rows:
        return []
    counts = {str(day): int(count) for day, count in rows}
    day = date.fromisoformat(str(rows[0][0]))
    today = date.today()
    total = 0
    result = []
    while day <= today:
        key = day.isoformat()
        total += counts.get(key, 0)
        result.append({"day": key, "count": total})
        day += timedelta(days=1)
    return result


def _tool_category_breakdown(conn: sqlite3.Connection, since_ts: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT tool, install_id, COUNT(*) AS calls
        FROM ev
        WHERE received_ts >= ?
          AND event = 'tool_invoke'
          AND tool != ''
        GROUP BY tool, install_id
        """,
        (since_ts,),
    ).fetchall()
    calls_by_key: dict[str, int] = {}
    installs_by_key: dict[str, set[str]] = {}
    for tool, install_id, calls in rows:
        key = _tool_category(str(tool or ""))
        calls_by_key[key] = calls_by_key.get(key, 0) + int(calls or 0)
        # Summing per-tool distinct counts would count one install once per
        # tool it used; keep a set so each install counts once per category.
        installs_by_key.setdefault(key, set()).add(str(install_id))
    return sorted(
        (
            {"key": key, "calls": calls, "installs": len(installs_by_key.get(key, ()))}
            for key, calls in calls_by_key.items()
        ),
        key=lambda item: (-item["calls"], item["key"]),
    )


def _excluded_install_ids() -> list[str]:
    """Install ids to hide from stats (our own dev/test machines).

    ``TELEMETRY_EXCLUDE_INSTALL_IDS`` is a comma/space separated list. Ids are
    validated against the install_id format so they are safe to inline in SQL.
    """
    raw = os.getenv("TELEMETRY_EXCLUDE_INSTALL_IDS", "")
    ids = {part.strip().lower() for part in re.split(r"[,\s]+", raw) if part.strip()}
    return sorted(i for i in ids if _INSTALL_ID_RE.match(i))


def _create_scoped_view(conn: sqlite3.Connection, excluded: list[str]) -> None:
    """(Re)create the temp view ``ev`` that every stats query reads from."""
    conn.execute("DROP VIEW IF EXISTS temp.ev")
    if excluded:
        id_list = ",".join(f"'{i}'" for i in excluded)
        conn.execute(f"CREATE TEMP VIEW ev AS SELECT * FROM main.events WHERE install_id NOT IN ({id_list})")
    else:
        conn.execute("CREATE TEMP VIEW ev AS SELECT * FROM main.events")


def _tool_breakdown(conn: sqlite3.Connection, since_ts: int, limit: int = 300) -> list[dict[str, Any]]:
    """Every tool with call volume, reach, success and write-mode split."""
    rows = conn.execute(
        """
        SELECT tool,
               COUNT(*) AS calls,
               COUNT(DISTINCT install_id) AS installs,
               SUM(CASE WHEN ok = 1 THEN 1 ELSE 0 END) AS ok_calls,
               SUM(CASE WHEN mode IN ('preview', 'intent_preview') THEN 1 ELSE 0 END) AS previews,
               SUM(CASE WHEN mode IN ('execute', 'intent_execute') THEN 1 ELSE 0 END) AS executes,
               COUNT(DISTINCT host) AS hosts,
               MAX(received_ts) AS last_ts
        FROM ev
        WHERE received_ts >= ?
          AND event = 'tool_invoke'
          AND tool != ''
        GROUP BY tool
        ORDER BY calls DESC, tool ASC
        LIMIT ?
        """,
        (since_ts, limit),
    ).fetchall()
    return [
        {
            "key": str(row[0]),
            "category": _tool_category(str(row[0])),
            "calls": int(row[1] or 0),
            "installs": int(row[2] or 0),
            "ok_calls": int(row[3] or 0),
            "success_rate": (int(row[3] or 0) / int(row[1])) if row[1] else None,
            "previews": int(row[4] or 0),
            "executes": int(row[5] or 0),
            "hosts": int(row[6] or 0),
            "last_seen": time.strftime("%Y-%m-%d", time.gmtime(int(row[7] or 0))),
        }
        for row in rows
    ]


def _host_tool_breakdown(conn: sqlite3.Connection, since_ts: int, limit: int = 400) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT host, tool,
               COUNT(*) AS calls,
               COUNT(DISTINCT install_id) AS installs,
               SUM(CASE WHEN ok = 1 THEN 1 ELSE 0 END) AS ok_calls
        FROM ev
        WHERE received_ts >= ?
          AND event = 'tool_invoke'
          AND tool != ''
        GROUP BY host, tool
        ORDER BY calls DESC, host ASC, tool ASC
        LIMIT ?
        """,
        (since_ts, limit),
    ).fetchall()
    return [
        {
            "host": str(row[0]),
            "tool": str(row[1]),
            "calls": int(row[2] or 0),
            "installs": int(row[3] or 0),
            "ok_calls": int(row[4] or 0),
        }
        for row in rows
    ]


def _tool_error_breakdown(conn: sqlite3.Connection, since_ts: int, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT tool, error_class, COUNT(*) AS calls, COUNT(DISTINCT install_id) AS installs
        FROM ev
        WHERE received_ts >= ?
          AND event = 'tool_invoke'
          AND ok = 0
        GROUP BY tool, error_class
        ORDER BY calls DESC, tool ASC
        LIMIT ?
        """,
        (since_ts, limit),
    ).fetchall()
    return [
        {
            "tool": str(row[0]),
            "error_class": str(row[1] or "unclassified"),
            "calls": int(row[2] or 0),
            "installs": int(row[3] or 0),
        }
        for row in rows
    ]


# Frameworks reported in the per-host table, in display order.
_HOST_ORDER = ("claude-code", "codex", "cursor", "hermes", "openclaw", "mcp", "unknown")


def _host_summary(conn: sqlite3.Connection, since_ts: int) -> list[dict[str, Any]]:
    """Per-framework adoption: installed -> launched -> used -> returned.

    * plugin_installs: installs that successfully wired the plugin into this host
    * launched_installs: installs whose host actually started the MCP bridge
      (``session_start``; MCP hosts only, emitted since the bridge recorder)
    * wallet_users: installs that made at least one tool call from this host
    * returning_users: wallet users with tool calls on 2+ distinct UTC days
    """
    stats: dict[str, dict[str, Any]] = {}

    def _row(host: str) -> dict[str, Any]:
        return stats.setdefault(
            host,
            {
                "key": host,
                "plugin_installs": 0,
                "launched_installs": 0,
                "sessions": 0,
                "wallet_users": 0,
                "returning_users": 0,
                "tool_calls": 0,
                "ok_calls": 0,
                "success_rate": None,
                "calls_per_user": None,
            },
        )

    for host, installs in conn.execute(
        """
        SELECT host, COUNT(DISTINCT install_id) FROM ev
        WHERE received_ts >= ? AND event = 'plugin_install_success'
        GROUP BY host
        """,
        (since_ts,),
    ).fetchall():
        _row(str(host))["plugin_installs"] = int(installs or 0)

    for host, sessions, installs in conn.execute(
        """
        SELECT host, COUNT(*), COUNT(DISTINCT install_id) FROM ev
        WHERE received_ts >= ? AND event = 'session_start'
        GROUP BY host
        """,
        (since_ts,),
    ).fetchall():
        row = _row(str(host))
        row["sessions"] = int(sessions or 0)
        row["launched_installs"] = int(installs or 0)

    for host, users, calls, ok_calls in conn.execute(
        """
        SELECT host, COUNT(DISTINCT install_id), COUNT(*), SUM(CASE WHEN ok = 1 THEN 1 ELSE 0 END)
        FROM ev
        WHERE received_ts >= ? AND event = 'tool_invoke'
        GROUP BY host
        """,
        (since_ts,),
    ).fetchall():
        row = _row(str(host))
        row["wallet_users"] = int(users or 0)
        row["tool_calls"] = int(calls or 0)
        row["ok_calls"] = int(ok_calls or 0)
        row["success_rate"] = (row["ok_calls"] / row["tool_calls"]) if row["tool_calls"] else None
        row["calls_per_user"] = (row["tool_calls"] / row["wallet_users"]) if row["wallet_users"] else None

    for host, returning in conn.execute(
        """
        SELECT host, COUNT(*) FROM (
            SELECT host, install_id
            FROM ev
            WHERE received_ts >= ? AND event = 'tool_invoke'
            GROUP BY host, install_id
            HAVING COUNT(DISTINCT date(received_ts, 'unixepoch')) >= 2
        )
        GROUP BY host
        """,
        (since_ts,),
    ).fetchall():
        _row(str(host))["returning_users"] = int(returning or 0)

    order = {host: idx for idx, host in enumerate(_HOST_ORDER)}
    return sorted(stats.values(), key=lambda row: (order.get(row["key"], len(order)), row["key"]))


def _user_summary(conn: sqlite3.Connection, since_ts: int) -> dict[str, Any]:
    """Real-usage signals that installer noise (CI, retries, npx) can't inflate."""
    now = int(time.time())

    def _scalar(sql: str, args: tuple = ()) -> int:
        row = conn.execute(sql, args).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    per_install = conn.execute(
        """
        SELECT install_id,
               COUNT(*) AS calls,
               COUNT(DISTINCT date(received_ts, 'unixepoch')) AS days,
               SUM(CASE WHEN mode IN ('execute', 'intent_execute') THEN 1 ELSE 0 END) AS executes
        FROM ev
        WHERE received_ts >= ? AND event = 'tool_invoke'
        GROUP BY install_id
        """,
        (since_ts,),
    ).fetchall()
    wallet_users = len(per_install)
    returning = sum(1 for row in per_install if int(row[2] or 0) >= 2)
    engaged = sum(1 for row in per_install if int(row[1] or 0) >= 5)
    executing = sum(1 for row in per_install if int(row[3] or 0) > 0)
    first_seen_in_window = _scalar(
        """
        SELECT COUNT(*) FROM (
            SELECT install_id, MIN(received_ts) AS first_ts
            FROM ev
            WHERE event = 'tool_invoke'
            GROUP BY install_id
        )
        WHERE first_ts >= ?
        """,
        (since_ts,),
    )
    call_buckets = {"1": 0, "2-4": 0, "5-19": 0, "20-99": 0, "100+": 0}
    for row in per_install:
        calls = int(row[1] or 0)
        if calls <= 1:
            call_buckets["1"] += 1
        elif calls <= 4:
            call_buckets["2-4"] += 1
        elif calls <= 19:
            call_buckets["5-19"] += 1
        elif calls <= 99:
            call_buckets["20-99"] += 1
        else:
            call_buckets["100+"] += 1

    # Funnel over installs seen in the window. Each stage is a subset of the
    # previous one so drop-off reads directly.
    funnel_rows = conn.execute(
        """
        SELECT install_id,
               MAX(CASE WHEN event = 'install_success' THEN 1 ELSE 0 END),
               MAX(CASE WHEN event = 'plugin_install_success' THEN 1 ELSE 0 END),
               MAX(CASE WHEN event = 'session_start' THEN 1 ELSE 0 END),
               MAX(CASE WHEN event = 'tool_invoke' THEN 1 ELSE 0 END)
        FROM ev
        WHERE received_ts >= ?
        GROUP BY install_id
        """,
        (since_ts,),
    ).fetchall()
    installed = [row for row in funnel_rows if row[1]]
    wired = [row for row in installed if row[2]]
    used = [row for row in wired if row[4]]
    returning_ids = {str(row[0]) for row in per_install if int(row[2] or 0) >= 2}
    funnel = [
        {"key": "npm install succeeded", "installs": len(installed)},
        {"key": "plugin wired into a host", "installs": len(wired)},
        {"key": "host launched the bridge", "installs": sum(1 for row in wired if row[3])},
        {"key": "made a wallet tool call", "installs": len(used)},
        {"key": "came back another day", "installs": sum(1 for row in used if str(row[0]) in returning_ids)},
    ]

    return {
        "wallet_users": wallet_users,
        "new_wallet_users": first_seen_in_window,
        "returning_users": returning,
        "engaged_users": engaged,
        "executing_users": executing,
        "wallet_dau": _scalar(
            "SELECT COUNT(DISTINCT install_id) FROM ev WHERE received_ts >= ? AND event = 'tool_invoke'",
            (now - 86400,),
        ),
        "wallet_wau": _scalar(
            "SELECT COUNT(DISTINCT install_id) FROM ev WHERE received_ts >= ? AND event = 'tool_invoke'",
            (now - 7 * 86400,),
        ),
        "launched_installs": _scalar(
            "SELECT COUNT(DISTINCT install_id) FROM ev WHERE received_ts >= ? AND event = 'session_start'",
            (since_ts,),
        ),
        "calls_per_user": [{"key": key, "installs": value} for key, value in call_buckets.items()],
        "funnel": funnel,
    }


def _backend_tool_breakdown(conn: sqlite3.Connection, since_ts: int, limit: int = 200) -> list[dict[str, Any]]:
    """Break tool usage down by the backend recorded on the same invocation."""
    rows = conn.execute(
        """
        SELECT backend, tool,
               COUNT(*) AS calls,
               COUNT(DISTINCT install_id) AS installs
        FROM ev
        WHERE received_ts >= ?
          AND event = 'tool_invoke'
          AND backend != ''
          AND tool != ''
        GROUP BY backend, tool
        ORDER BY calls DESC, backend ASC, tool ASC
        LIMIT ?
        """,
        (since_ts, limit),
    ).fetchall()
    return [
        {
            "backend": str(row[0]),
            "tool": str(row[1]),
            "calls": int(row[2] or 0),
            "installs": int(row[3] or 0),
        }
        for row in rows
    ]


def _success_rate_breakdown(conn: sqlite3.Connection, since_ts: int) -> list[dict[str, Any]]:
    families = {
        "tool_invocations": ("tool_invoke",),
        "installs": ("install_start", "install_success", "install_failed"),
        "plugin_installs": ("plugin_install_start", "plugin_install_success", "plugin_install_failed"),
        "updates": ("update_start", "update_success", "update_failed"),
    }
    rows: list[dict[str, Any]] = []
    for key, events in families.items():
        placeholders = ",".join("?" for _ in events)
        total_row = conn.execute(
            f"""
            SELECT COUNT(*),
                   SUM(CASE WHEN ok = 1 THEN 1 ELSE 0 END)
            FROM ev
            WHERE received_ts >= ?
              AND event IN ({placeholders})
            """,
            (since_ts, *events),
        ).fetchone()
        total = int(total_row[0] or 0) if total_row else 0
        ok_count = int(total_row[1] or 0) if total_row else 0
        rows.append(
            {
                "key": key,
                "calls": total,
                "ok_calls": ok_count,
                "success_rate": (ok_count / total) if total else None,
            }
        )
    return rows


def _x402_summary(conn: sqlite3.Connection, since_ts: int) -> dict[str, Any]:
    """Return an x402 funnel where success means settled payment, never a tool call."""

    def _count(event: str) -> int:
        row = conn.execute(
            "SELECT COUNT(*) FROM ev WHERE received_ts >= ? AND event = ?",
            (since_ts, event),
        ).fetchone()
        return int(row[0] or 0) if row else 0

    tool_invocations_row = conn.execute(
        """
        SELECT COUNT(*) FROM ev
        WHERE received_ts >= ? AND event = 'tool_invoke' AND tool = 'x402_pay_request'
        """,
        (since_ts,),
    ).fetchone()
    tool_invocations = int(tool_invocations_row[0] or 0) if tool_invocations_row else 0
    attempted = _count("x402_payment_attempted")
    not_required = _count("x402_payment_not_required")
    settled = _count("x402_payment_settled")
    failed = _count("x402_payment_failed")
    paid_attempts = max(attempted - not_required, 0)

    def _breakdown(column: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            f"""
            SELECT {column}, COUNT(*)
            FROM ev
            WHERE received_ts >= ?
              AND event IN ('x402_payment_attempted', 'x402_payment_settled', 'x402_payment_failed')
              AND {column} != ''
            GROUP BY {column}
            ORDER BY COUNT(*) DESC, {column} ASC
            """,
            (since_ts,),
        ).fetchall()
        return [{"key": str(row[0]), "calls": int(row[1] or 0)} for row in rows]

    return {
        # Keep this explicit so the generic tool-call count is never mistaken
        # for a payment-success metric.
        "pay_tool_invocations": tool_invocations,
        "previewed": _count("x402_previewed"),
        "preview_failed": _count("x402_preview_failed"),
        "payment_attempted": attempted,
        "payment_not_required": not_required,
        "paid_attempts": paid_attempts,
        "payment_settled": settled,
        "payment_failed": failed,
        "payment_settlement_rate": (settled / paid_attempts) if paid_attempts else None,
        "by_network": _breakdown("network"),
        "by_scheme": _breakdown("scheme"),
        "by_asset_family": _breakdown("asset_family"),
        "by_amount_bucket": _breakdown("amount_bucket"),
        "by_settlement_status": _breakdown("settlement_status"),
        "by_error_class": _breakdown("error_class"),
    }


def _rpc_enabled() -> bool:
    raw = os.getenv("RPC_USAGE_TELEMETRY_ENABLED", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _rpc_flush_interval_seconds() -> float:
    raw = os.getenv("RPC_USAGE_FLUSH_INTERVAL_SECONDS", "30").strip() or "30"
    try:
        return max(float(raw), 1.0)
    except ValueError:
        return 30.0


def _clean_rpc_field(value: str, fallback: str = "unknown") -> str:
    value = str(value or "").strip()
    return value if _RPC_FIELD_RE.match(value) else fallback


def _rpc_day(ts: int | None = None) -> str:
    return date.fromtimestamp(ts or int(time.time())).isoformat()


def _start_rpc_flush_thread() -> None:
    global _RPC_FLUSH_THREAD_STARTED
    if _RPC_FLUSH_THREAD_STARTED:
        return
    _RPC_FLUSH_THREAD_STARTED = True

    def _loop() -> None:
        while True:
            time.sleep(_rpc_flush_interval_seconds())
            try:
                flush_rpc_usage()
            except Exception:
                pass

    thread = threading.Thread(target=_loop, name="rpc-usage-flush", daemon=True)
    thread.start()


def record_rpc_usage(
    *,
    endpoint: str,
    network: str,
    provider: str,
    method: str,
    status_bucket: str,
    latency_bucket: str,
    count: int = 1,
) -> None:
    """Record one aggregate RPC usage counter without touching SQLite.

    The hot path only normalizes a few short identifiers and increments an
    in-memory counter. A daemon thread flushes rollups to SQLite later.
    """
    if not _rpc_enabled():
        return
    try:
        safe_count = max(int(count), 1)
    except (TypeError, ValueError):
        safe_count = 1
    key = (
        _rpc_day(),
        _clean_rpc_field(endpoint),
        _clean_rpc_field(network),
        _clean_rpc_field(provider),
        _clean_rpc_field(method),
        _clean_rpc_field(status_bucket),
        _clean_rpc_field(latency_bucket),
    )
    with _RPC_LOCK:
        _RPC_PENDING[key] = _RPC_PENDING.get(key, 0) + safe_count
    _start_rpc_flush_thread()


def flush_rpc_usage() -> int:
    """Flush pending RPC counters to SQLite rollups. Never called on hot path."""
    with _RPC_LOCK:
        if not _RPC_PENDING:
            return 0
        pending = dict(_RPC_PENDING)
        _RPC_PENDING.clear()

    try:
        with _DB_LOCK:
            conn = _connect()
            conn.executemany(
                """
                INSERT INTO rpc_usage_rollups
                    (day, endpoint, network, provider, method, status_bucket, latency_bucket, count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(day, endpoint, network, provider, method, status_bucket, latency_bucket)
                DO UPDATE SET count = count + excluded.count
                """,
                [(*key, count) for key, count in pending.items()],
            )
            conn.commit()
        return sum(pending.values())
    except Exception:
        with _RPC_LOCK:
            for key, count in pending.items():
                _RPC_PENDING[key] = _RPC_PENDING.get(key, 0) + count
        return 0


def rpc_usage_summary(window_days: int = 30) -> dict[str, Any]:
    flush_rpc_usage()
    since_day = date.fromtimestamp(int(time.time()) - window_days * 86400).isoformat()
    with _DB_LOCK:
        conn = _connect()

        def _rows(column: str, limit: int = 20) -> list[dict[str, Any]]:
            rows = conn.execute(
                f"""
                SELECT {column} AS k, SUM(count) AS calls
                FROM rpc_usage_rollups
                WHERE day >= ?
                GROUP BY {column}
                ORDER BY calls DESC
                LIMIT ?
                """,
                (since_day, limit),
            ).fetchall()
            return [{"key": r[0], "calls": int(r[1] or 0)} for r in rows]

        total_row = conn.execute(
            "SELECT SUM(count) FROM rpc_usage_rollups WHERE day >= ?",
            (since_day,),
        ).fetchone()
        total_calls = int(total_row[0] or 0) if total_row else 0
        by_endpoint = _rows("endpoint")
        by_network = _rows("network")
        by_provider = _rows("provider")
        by_method = _rows("method")
        by_status = _rows("status_bucket")
        by_latency = _rows("latency_bucket")

    with _RPC_LOCK:
        pending = sum(_RPC_PENDING.values())

    return {
        "ok": True,
        "window_days": window_days,
        "total_calls": total_calls,
        "pending_flush": pending,
        "by_endpoint": by_endpoint,
        "by_network": by_network,
        "by_provider": by_provider,
        "by_method": by_method,
        "by_status": by_status,
        "by_latency": by_latency,
    }


def _downloads_end_date() -> str:
    # npm daily downloads are complete for past UTC days; avoid partial today.
    return (date.today() - timedelta(days=1)).isoformat()


def _fetch_npm_downloads_range(start: str, end: str) -> dict[str, Any]:
    package = os.getenv("NPM_DOWNLOADS_PACKAGE", NPM_DOWNLOADS_PACKAGE).strip() or NPM_DOWNLOADS_PACKAGE
    quoted_package = urllib.parse.quote(package, safe="")
    url = f"https://api.npmjs.org/downloads/range/{start}:{end}/{quoted_package}"
    req = urllib.request.Request(url, headers={"User-Agent": "AgentLayer/provider-gateway telemetry stats"})
    with urllib.request.urlopen(req, timeout=NPM_DOWNLOADS_HTTP_TIMEOUT_SECONDS) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("downloads"), list):
        raise RuntimeError("npm downloads response has unexpected shape")
    return payload


def npm_downloads_summary() -> dict[str, Any]:
    """Return cached npm download totals for the public installer package.

    This runs only from the privileged stats endpoint, never from telemetry
    ingest or RPC handlers. On npm failures it returns stale cache when
    available, preserving stats endpoint availability.
    """
    global _NPM_CACHE, _NPM_CACHE_TS

    if os.getenv("NPM_DOWNLOADS_ENABLED", "true").strip().lower() in {"0", "false", "no", "off"}:
        return {"ok": False, "disabled": True}

    now = time.time()
    with _NPM_CACHE_LOCK:
        if _NPM_CACHE and (now - _NPM_CACHE_TS) < NPM_DOWNLOADS_CACHE_TTL_SECONDS:
            return {**_NPM_CACHE, "cached": True, "stale": False}

    package = os.getenv("NPM_DOWNLOADS_PACKAGE", NPM_DOWNLOADS_PACKAGE).strip() or NPM_DOWNLOADS_PACKAGE
    since = os.getenv("NPM_DOWNLOADS_SINCE", NPM_DOWNLOADS_SINCE).strip() or NPM_DOWNLOADS_SINCE
    end = _downloads_end_date()
    try:
        payload = _fetch_npm_downloads_range(since, end)
        daily = [
            {
                "day": str(item.get("day", "")),
                "downloads": int(item.get("downloads", 0) or 0),
            }
            for item in payload.get("downloads", [])
            if isinstance(item, dict)
        ]
        total = sum(item["downloads"] for item in daily)
        last_30_days = sum(item["downloads"] for item in daily[-30:])
        last_7_days = sum(item["downloads"] for item in daily[-7:])
        result = {
            "ok": True,
            "package": package,
            "since": str(payload.get("start") or since),
            "through": str(payload.get("end") or end),
            "all_time": total,
            "last_30_days": last_30_days,
            "last_7_days": last_7_days,
            "days": len(daily),
            "daily": daily,
            "cached": False,
            "stale": False,
        }
        with _NPM_CACHE_LOCK:
            _NPM_CACHE = result
            _NPM_CACHE_TS = now
        return result
    except (OSError, urllib.error.URLError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        with _NPM_CACHE_LOCK:
            if _NPM_CACHE:
                return {**_NPM_CACHE, "cached": True, "stale": True, "error": str(exc)}
        return {
            "ok": False,
            "package": package,
            "since": since,
            "through": end,
            "error": str(exc),
            "cached": False,
            "stale": False,
        }


def summary(window_days: int = 30) -> dict[str, Any]:
    """Aggregate adoption metrics over the trailing ``window_days``."""
    since = int(time.time()) - window_days * 86400
    excluded = _excluded_install_ids()
    with _DB_LOCK:
        conn = _connect()
        _create_scoped_view(conn, excluded)

        def _scalar(sql: str, args: tuple = ()) -> int:
            row = conn.execute(sql, args).fetchone()
            return int(row[0]) if row and row[0] is not None else 0

        total_events = _scalar(
            "SELECT COUNT(*) FROM ev WHERE received_ts >= ?", (since,)
        )
        active_installs = _scalar("SELECT COUNT(DISTINCT install_id) FROM ev WHERE received_ts >= ?", (since,))
        wallet_active_installs = _scalar(
            "SELECT COUNT(DISTINCT install_id) FROM ev WHERE received_ts >= ? AND event = 'tool_invoke'",
            (since,),
        )
        day_ago = int(time.time()) - 86400
        dau = _scalar("SELECT COUNT(DISTINCT install_id) FROM ev WHERE received_ts >= ?", (day_ago,))
        wallet_dau = _scalar(
            "SELECT COUNT(DISTINCT install_id) FROM ev WHERE received_ts >= ? AND event = 'tool_invoke'",
            (day_ago,),
        )

        def _breakdown(
            column: str,
            limit: int = 20,
            *,
            non_empty: bool = False,
            event_filter: str | None = None,
        ) -> list[dict[str, Any]]:
            value_filter = f"AND {column} != ''" if non_empty else ""
            event_clause = "AND event = ?" if event_filter else ""
            args: tuple[Any, ...] = (since, event_filter, limit) if event_filter else (since, limit)
            rows = conn.execute(
                f"""
                SELECT {column} AS k,
                       COUNT(*) AS calls,
                       COUNT(DISTINCT install_id) AS installs
                FROM ev
                WHERE received_ts >= ?
                  {value_filter}
                  {event_clause}
                GROUP BY {column}
                ORDER BY calls DESC
                LIMIT ?
                """,
                args,
            ).fetchall()
            return [
                {"key": r[0], "calls": int(r[1]), "installs": int(r[2])} for r in rows
            ]

        excluded_events = _scalar(
            "SELECT COUNT(*) FROM main.events WHERE received_ts >= ?", (since,)
        ) - total_events
        by_event = _breakdown("event")
        by_host = _breakdown("host")
        wallet_by_host = _breakdown("host", event_filter="tool_invoke")
        by_tool = _breakdown("tool", 100, non_empty=True, event_filter="tool_invoke")
        tools = _tool_breakdown(conn, since)
        host_tools = _host_tool_breakdown(conn, since)
        tool_errors = _tool_error_breakdown(conn, since)
        hosts = _host_summary(conn, since)
        users = _user_summary(conn, since)
        by_mode = _breakdown("mode", non_empty=True, event_filter="tool_invoke")
        by_backend_tool = _backend_tool_breakdown(conn, since)
        by_tool_category = _tool_category_breakdown(conn, since)
        by_backend = _breakdown("backend", non_empty=True, event_filter="tool_invoke")
        by_version = _breakdown("plugin_version")
        by_source = _breakdown("source", non_empty=True)
        by_command = _breakdown("command", non_empty=True)
        success_by_family = _success_rate_breakdown(conn, since)
        x402 = _x402_summary(conn, since)
        daily = _daily_series(conn, since, window_days)
        cumulative_wallet_active_installs = _cumulative_wallet_installs(conn)

    # Overall success is about wallet tool calls; installer events have their
    # own families in success_by_family.
    tool_family = next((row for row in success_by_family if row["key"] == "tool_invocations"), {})
    success_rate = tool_family.get("success_rate")
    npm_downloads = npm_downloads_summary()
    if npm_downloads.get("ok"):
        daily_downloads = list(npm_downloads.get("daily") or [])
        if window_days > 0:
            daily_downloads = daily_downloads[-window_days:]
        npm_downloads["daily_window"] = daily_downloads
    return {
        "ok": True,
        "window_days": window_days,
        "total_events": total_events,
        "active_installs": active_installs,
        "wallet_active_installs": wallet_active_installs,
        "dau": dau,
        "wallet_dau": wallet_dau,
        "success_rate": success_rate,
        "excluded_install_ids": len(excluded),
        "excluded_events": excluded_events,
        "users": users,
        "hosts": hosts,
        "tools": tools,
        "host_tools": host_tools,
        "tool_errors": tool_errors,
        "by_mode": by_mode,
        "by_event": by_event,
        "by_host": by_host,
        "wallet_by_host": wallet_by_host,
        "by_tool": by_tool,
        "by_backend_tool": by_backend_tool,
        "by_tool_category": by_tool_category,
        "by_backend": by_backend,
        "by_version": by_version,
        "by_source": by_source,
        "by_command": by_command,
        "success_by_family": success_by_family,
        "x402": x402,
        "daily": daily,
        "cumulative_wallet_active_installs": cumulative_wallet_active_installs,
        "npm_downloads": npm_downloads,
        "rpc_usage": rpc_usage_summary(window_days),
    }
