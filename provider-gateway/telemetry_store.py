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

ALLOWED_EVENTS = {"tool_invoke", "session_start"}
ALLOWED_HOSTS = {"claude-code", "codex", "hermes", "openclaw", "unknown"}
ALLOWED_BACKENDS = {
    "solana_local",
    "wdk_btc_local",
    "wdk_evm_local",
    "unknown",
    "",
}

_INSTALL_ID_RE = re.compile(r"^[0-9a-f\-]{8,64}$")
# Tool names are registered identifiers (get_wallet_balance, transfer_sol, ...):
# always a lowercase letter first, then [a-z0-9_], max 48. The leading-letter
# rule rejects address-like tokens (0x… hex) so the one free-text field cannot
# carry a wallet address even from a buggy client. The authoritative guarantee
# is upstream: the CLI only ever emits the invoked tool's registered name.
_TOOL_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
_VERSION_RE = re.compile(r"^[0-9A-Za-z.\-+]{1,32}$")

# Only these keys are ever read from an inbound payload. Everything else is
# dropped, so a client cannot smuggle a wallet address into an extra field.
ALLOWED_KEYS = {"event", "install_id", "host", "tool", "backend", "plugin_version", "ok", "ts"}

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
    }


# --- storage ----------------------------------------------------------------

_DB_LOCK = threading.Lock()
_CONN: sqlite3.Connection | None = None
_NPM_CACHE_LOCK = threading.Lock()
_NPM_CACHE: dict[str, Any] | None = None
_NPM_CACHE_TS = 0.0


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
                (event, install_id, host, tool, backend, plugin_version, ok, client_ts, received_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        conn.commit()


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
    with _DB_LOCK:
        conn = _connect()

        def _scalar(sql: str, args: tuple = ()) -> int:
            row = conn.execute(sql, args).fetchone()
            return int(row[0]) if row and row[0] is not None else 0

        total_events = _scalar(
            "SELECT COUNT(*) FROM events WHERE received_ts >= ?", (since,)
        )
        active_installs = _scalar(
            "SELECT COUNT(DISTINCT install_id) FROM events WHERE received_ts >= ?",
            (since,),
        )
        day_ago = int(time.time()) - 86400
        dau = _scalar(
            "SELECT COUNT(DISTINCT install_id) FROM events WHERE received_ts >= ?",
            (day_ago,),
        )

        def _breakdown(column: str, limit: int = 20) -> list[dict[str, Any]]:
            rows = conn.execute(
                f"""
                SELECT {column} AS k,
                       COUNT(*) AS calls,
                       COUNT(DISTINCT install_id) AS installs
                FROM events
                WHERE received_ts >= ?
                GROUP BY {column}
                ORDER BY calls DESC
                LIMIT ?
                """,
                (since, limit),
            ).fetchall()
            return [
                {"key": r[0], "calls": int(r[1]), "installs": int(r[2])} for r in rows
            ]

        ok_calls = _scalar(
            "SELECT COUNT(*) FROM events WHERE received_ts >= ? AND ok = 1", (since,)
        )

    success_rate = (ok_calls / total_events) if total_events else None
    return {
        "ok": True,
        "window_days": window_days,
        "total_events": total_events,
        "active_installs": active_installs,
        "dau": dau,
        "success_rate": success_rate,
        "by_host": _breakdown("host"),
        "by_tool": _breakdown("tool"),
        "by_backend": _breakdown("backend"),
        "by_version": _breakdown("plugin_version"),
        "npm_downloads": npm_downloads_summary(),
    }
