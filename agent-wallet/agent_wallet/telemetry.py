"""Anonymous, privacy-first adoption telemetry for the AgentLayer wallet.

Why this exists: we want to know how many people use the wallet and through which
host (Claude Code / Codex / Hermes / OpenClaw) — nothing more. It deliberately
records NO PII: no wallet addresses, balances, amounts, tx hashes, tool
arguments, or secrets. Only a random local install id, the host name, the
invoked tool's registered name, the backend family, the plugin version, and a
success flag.

Design for a short-lived CLI subprocess:
  - `record()` appends one JSON line to a local spool file. This is instant and
    durable: a single small append is atomic on POSIX, and the event survives
    even if this process exits before any network call completes.
  - A throttled, best-effort flush claims the spool (atomic rename), POSTs each
    event to the provider-gateway, and re-spools anything that failed. Because
    durability lives in the spool, a killed flush never loses data — the next
    invocation (or a longer-lived process) ships it.

Everything here swallows its own errors. Telemetry must never slow down or break
a wallet operation. Users opt out with AGENT_WALLET_NO_TELEMETRY=1.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
import uuid
from pathlib import Path
from threading import Thread
from typing import Any

from . import __version__
from .config import DEFAULT_PROVIDER_GATEWAY_URL, resolve_openclaw_home

ALLOWED_HOSTS = {"claude-code", "codex", "hermes", "openclaw"}

SPOOL_NAME = "telemetry_spool.jsonl"
ID_NAME = "telemetry_id"
LAST_FLUSH_NAME = "telemetry_last_flush"

# Keep the spool bounded if the gateway is unreachable for a long time.
MAX_SPOOL_LINES = 500
# Don't attempt a network flush more than this often (seconds), unless the spool
# has grown past the soft cap below.
FLUSH_THROTTLE_SECONDS = 20
FLUSH_FORCE_LINES = 50
# Tight network bounds: telemetry never blocks meaningfully.
HTTP_TIMEOUT_SECONDS = 1.5
MAX_EVENTS_PER_FLUSH = 100


def _enabled() -> bool:
    raw = os.getenv("AGENT_WALLET_NO_TELEMETRY", "").strip().lower()
    return raw not in ("1", "true", "yes", "on")


def _home() -> Path:
    return resolve_openclaw_home()


def _gateway_url() -> str:
    url = os.getenv("PROVIDER_GATEWAY_URL", "").strip() or DEFAULT_PROVIDER_GATEWAY_URL
    return url.rstrip("/")


def _host() -> str:
    host = os.getenv("AGENT_WALLET_HOST", "").strip().lower()
    return host if host in ALLOWED_HOSTS else "unknown"


def _install_id() -> str:
    """Stable, random, non-identifying id for this install. Created once."""
    path = _home() / ID_NAME
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass
    new_id = uuid.uuid4().hex
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_id, encoding="utf-8")
    except OSError:
        pass
    return new_id


def record(
    tool: str,
    *,
    backend: str = "",
    ok: bool = True,
    event: str = "tool_invoke",
) -> None:
    """Append an anonymous event to the spool and best-effort flush. Never raises."""
    try:
        if not _enabled():
            return
        payload = {
            "event": event,
            "install_id": _install_id(),
            "host": _host(),
            "tool": tool or "",
            "backend": backend or "",
            "plugin_version": __version__,
            "ok": bool(ok),
            "ts": int(time.time()),
        }
        _append_spool(payload)
        _maybe_flush_async()
    except Exception:
        # Telemetry is never allowed to affect the wallet call.
        pass


# --- spool I/O --------------------------------------------------------------


def _spool_path() -> Path:
    return _home() / SPOOL_NAME


def _append_spool(payload: dict[str, Any]) -> None:
    path = _spool_path()
    line = json.dumps(payload, separators=(",", ":")) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    # A single write of a short line is atomic across processes on POSIX.
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line)


def _spool_line_count() -> int:
    try:
        with open(_spool_path(), "r", encoding="utf-8") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def _should_flush_now() -> bool:
    count = _spool_line_count()
    if count == 0:
        return False
    if count >= FLUSH_FORCE_LINES:
        return True
    last_path = _home() / LAST_FLUSH_NAME
    try:
        last = float(last_path.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        last = 0.0
    return (time.time() - last) >= FLUSH_THROTTLE_SECONDS


def _mark_flush_attempt() -> None:
    try:
        (_home() / LAST_FLUSH_NAME).write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def _maybe_flush_async() -> None:
    if not _should_flush_now():
        return
    _mark_flush_attempt()
    # Daemon thread: durability is in the spool, so a killed thread loses nothing.
    Thread(target=_flush, daemon=True).start()


def _flush() -> None:
    """Claim the spool atomically, POST each event, re-spool failures."""
    spool = _spool_path()
    claim = spool.with_suffix(spool.suffix + f".flushing.{os.getpid()}")
    try:
        os.rename(spool, claim)  # atomic; only one process wins the batch
    except OSError:
        return  # nothing to flush, or another process claimed it

    try:
        lines = claim.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    # If we've accumulated a huge backlog, keep only the most recent events.
    if len(lines) > MAX_SPOOL_LINES:
        lines = lines[-MAX_SPOOL_LINES:]

    url = _gateway_url() + "/v1/telemetry"
    failed: list[str] = []
    sent = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if sent >= MAX_EVENTS_PER_FLUSH:
            failed.append(line)  # defer the rest to the next flush
            continue
        if _post(url, line):
            sent += 1
        else:
            failed.append(line)

    try:
        claim.unlink()
    except OSError:
        pass

    # Re-spool anything that didn't make it so the next flush retries it.
    if failed:
        try:
            with open(spool, "a", encoding="utf-8") as fh:
                fh.write("\n".join(failed) + "\n")
        except OSError:
            pass


def _post(url: str, body: str) -> bool:
    try:
        req = urllib.request.Request(
            url,
            data=body.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False
