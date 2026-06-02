"""Non-blocking "a newer version is available" check for the agent wallet.

Distribution is the npm package ``@agentlayer.tech/wallet``; a new release is a
new npm publish. This module compares the installed version against the latest
version published on the npm registry and decides whether to surface a notice.

Design constraints (must all hold):

* **Never block startup.** The network refresh runs in a daemon thread and only
  updates a cache file for the *next* start. The synchronous notice decision
  reads that cache and returns instantly without touching the network.
* **At most once per usage cycle.** The notice is injected into the MCP server
  ``instructions`` string, which a client reads exactly once per session.
* **At most once per day per version across sessions.** A cached
  ``last_shown_*`` record throttles repeats to :data:`NAG_INTERVAL_SECONDS`.
* **Fail-open.** Any error (offline, timeout, malformed cache) results in no
  notice and no exception — the wallet keeps working.
* **Opt-out.** Set ``AGENT_WALLET_DISABLE_UPDATE_CHECK=1`` to disable entirely.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Callable

from .config import resolve_openclaw_home

PACKAGE_NAME = "@agentlayer.tech/wallet"
# URL-encoded scoped package name for the npm registry endpoint.
_REGISTRY_URL = "https://registry.npmjs.org/@agentlayer.tech%2Fwallet/latest"

CACHE_TTL_SECONDS = 24 * 3600
NAG_INTERVAL_SECONDS = 24 * 3600
NET_TIMEOUT_SECONDS = 1.5

ENV_DISABLE = "AGENT_WALLET_DISABLE_UPDATE_CHECK"


def installed_version() -> str:
    """Return the installed agent-wallet version."""
    from . import __version__

    return __version__


def is_disabled(env: dict | None = None) -> bool:
    """Return True when the update check is opted out via environment."""
    env = os.environ if env is None else env
    return str(env.get(ENV_DISABLE, "")).strip().lower() in {"1", "true", "yes", "on"}


def cache_path() -> Path:
    """Location of the shared update-check cache file."""
    return resolve_openclaw_home() / "agent-wallet-runtime" / "update-check.json"


def _read_cache() -> dict:
    try:
        return json.loads(cache_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_cache(data: dict) -> None:
    try:
        path = cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        # Cache is best-effort; never let a write failure surface.
        pass


def _parse_semver(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in str(value).strip().split("."):
        num = ""
        for ch in chunk:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    return tuple(parts)


def _is_newer(latest: str, current: str) -> bool:
    try:
        return _parse_semver(latest) > _parse_semver(current)
    except Exception:
        return False


def pending_notice(
    *,
    mark_shown: bool,
    current: str | None = None,
    now: float | None = None,
) -> str | None:
    """Return a human-readable notice when a newer version should be surfaced.

    Reads only the cache (no network, instant). Returns ``None`` when disabled,
    when no newer version is known, or when the same version was already shown
    within :data:`NAG_INTERVAL_SECONDS`. When ``mark_shown`` is True and a notice
    is returned, the "last shown" record is persisted to throttle later sessions.
    """
    if is_disabled():
        return None
    current = installed_version() if current is None else current
    now = time.time() if now is None else now

    cache = _read_cache()
    latest = cache.get("latest_version")
    if not latest or not _is_newer(str(latest), current):
        return None

    if (
        cache.get("last_shown_version") == latest
        and isinstance(cache.get("last_shown_at"), (int, float))
        and now - cache["last_shown_at"] < NAG_INTERVAL_SECONDS
    ):
        return None

    if mark_shown:
        cache["last_shown_version"] = latest
        cache["last_shown_at"] = now
        _write_cache(cache)

    return (
        f"newer agent-wallet version {latest} is available (you have {current}). "
        f"Update with: npx {PACKAGE_NAME} update --yes"
    )


def _fetch_latest_version() -> str | None:
    """Fetch the latest published version from the npm registry (blocking)."""
    import httpx

    resp = httpx.get(_REGISTRY_URL, timeout=NET_TIMEOUT_SECONDS)
    resp.raise_for_status()
    version = resp.json().get("version")
    return str(version) if version else None


def _refresh_now(
    fetcher: Callable[[], str | None] | None = None,
    now: float | None = None,
) -> None:
    """Refresh the cached latest version if stale. Synchronous, fail-open."""
    if is_disabled():
        return
    now = time.time() if now is None else now
    cache = _read_cache()
    checked_at = cache.get("checked_at")
    if isinstance(checked_at, (int, float)) and now - checked_at < CACHE_TTL_SECONDS:
        return  # cache fresh enough; skip network
    fetcher = _fetch_latest_version if fetcher is None else fetcher
    try:
        latest = fetcher()
    except Exception:
        return  # fail-open: leave cache untouched
    if not latest:
        return
    cache["latest_version"] = str(latest)
    cache["checked_at"] = now
    _write_cache(cache)


def maybe_refresh_in_background(
    fetcher: Callable[[], str | None] | None = None,
) -> threading.Thread | None:
    """Start a daemon thread to refresh the cache without blocking the caller.

    Returns the started thread (for tests) or ``None`` when disabled.
    """
    if is_disabled():
        return None
    thread = threading.Thread(
        target=_refresh_now,
        kwargs={"fetcher": fetcher},
        name="agent-wallet-update-check",
        daemon=True,
    )
    thread.start()
    return thread
