"""Smoke test: background update-check notice cadence and fail-open behaviour.

Covers the agent_wallet.update_check module that decides whether to surface an
"a newer version is available" notice to the agent (via MCP instructions) and to
the human (via CLI doctor/status), backed by a cached, non-blocking npm check.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from agent_wallet import update_check


TMP = Path("/tmp/openclaw-update-check-test")


def _reset_home() -> Path:
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True, exist_ok=True)
    os.environ["OPENCLAW_HOME"] = str(TMP)
    os.environ.pop(update_check.ENV_DISABLE, None)
    return TMP


def _write_cache(**fields) -> None:
    path = update_check.cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fields), encoding="utf-8")


def _read_cache() -> dict:
    return json.loads(update_check.cache_path().read_text(encoding="utf-8"))


def test_no_cache_returns_none() -> None:
    _reset_home()
    assert update_check.pending_notice(mark_shown=True, current="0.1.33") is None


def test_latest_equal_or_older_returns_none() -> None:
    _reset_home()
    _write_cache(latest_version="0.1.33", checked_at=time.time())
    assert update_check.pending_notice(mark_shown=True, current="0.1.33") is None

    _reset_home()
    _write_cache(latest_version="0.1.30", checked_at=time.time())
    assert update_check.pending_notice(mark_shown=True, current="0.1.33") is None


def test_newer_returns_notice_and_marks_shown() -> None:
    _reset_home()
    now = 1_000_000.0
    _write_cache(latest_version="0.1.40", checked_at=now)
    notice = update_check.pending_notice(mark_shown=True, current="0.1.33", now=now)
    assert notice is not None
    assert "0.1.40" in notice and "0.1.33" in notice
    cache = _read_cache()
    assert cache["last_shown_version"] == "0.1.40"
    assert cache["last_shown_at"] == now


def test_daily_throttle_suppresses_repeat_same_version() -> None:
    _reset_home()
    base = 2_000_000.0
    _write_cache(latest_version="0.1.40", checked_at=base)
    assert update_check.pending_notice(mark_shown=True, current="0.1.33", now=base) is not None
    # Same version, well within the nag window -> suppressed.
    soon = base + update_check.NAG_INTERVAL_SECONDS - 10
    assert update_check.pending_notice(mark_shown=True, current="0.1.33", now=soon) is None
    # After the nag window elapses -> shown again.
    later = base + update_check.NAG_INTERVAL_SECONDS + 10
    assert update_check.pending_notice(mark_shown=True, current="0.1.33", now=later) is not None


def test_read_only_mark_shown_false_does_not_persist() -> None:
    _reset_home()
    _write_cache(latest_version="0.1.40", checked_at=time.time())
    assert update_check.pending_notice(mark_shown=False, current="0.1.33") is not None
    assert "last_shown_version" not in _read_cache()


def test_disabled_env_returns_none() -> None:
    _reset_home()
    _write_cache(latest_version="0.1.40", checked_at=time.time())
    os.environ[update_check.ENV_DISABLE] = "1"
    assert update_check.pending_notice(mark_shown=True, current="0.1.33") is None


def test_refresh_skips_network_when_cache_fresh() -> None:
    _reset_home()
    now = 3_000_000.0
    _write_cache(latest_version="0.1.40", checked_at=now - 10)
    calls = []

    def fetcher() -> str:
        calls.append(1)
        return "0.1.99"

    update_check._refresh_now(fetcher=fetcher, now=now)
    assert calls == []  # fresh cache -> no network


def test_refresh_hits_network_when_stale_and_updates_cache() -> None:
    _reset_home()
    now = 4_000_000.0
    _write_cache(latest_version="0.1.40", checked_at=now - update_check.CACHE_TTL_SECONDS - 10)

    def fetcher() -> str:
        return "0.1.99"

    update_check._refresh_now(fetcher=fetcher, now=now)
    cache = _read_cache()
    assert cache["latest_version"] == "0.1.99"
    assert cache["checked_at"] == now


def test_refresh_fail_open_on_fetcher_error() -> None:
    _reset_home()
    now = 5_000_000.0
    _write_cache(latest_version="0.1.40", checked_at=now - update_check.CACHE_TTL_SECONDS - 10)

    def fetcher() -> str:
        raise RuntimeError("network down")

    update_check._refresh_now(fetcher=fetcher, now=now)  # must not raise
    assert _read_cache()["latest_version"] == "0.1.40"  # unchanged


def test_refresh_disabled_skips_network() -> None:
    _reset_home()
    os.environ[update_check.ENV_DISABLE] = "1"
    calls = []

    def fetcher() -> str:
        calls.append(1)
        return "0.1.99"

    update_check._refresh_now(fetcher=fetcher, now=time.time())
    assert calls == []


def test_background_refresh_thread_updates_cache() -> None:
    _reset_home()
    _write_cache(latest_version="0.1.40", checked_at=0)  # very stale

    def fetcher() -> str:
        return "0.2.0"

    thread = update_check.maybe_refresh_in_background(fetcher=fetcher)
    assert thread is not None
    thread.join(timeout=5)
    assert _read_cache()["latest_version"] == "0.2.0"


def test_installed_version_matches_package() -> None:
    import agent_wallet

    assert update_check.installed_version() == agent_wallet.__version__


def main() -> None:
    tests = [
        test_no_cache_returns_none,
        test_latest_equal_or_older_returns_none,
        test_newer_returns_notice_and_marks_shown,
        test_daily_throttle_suppresses_repeat_same_version,
        test_read_only_mark_shown_false_does_not_persist,
        test_disabled_env_returns_none,
        test_refresh_skips_network_when_cache_fresh,
        test_refresh_hits_network_when_stale_and_updates_cache,
        test_refresh_fail_open_on_fetcher_error,
        test_refresh_disabled_skips_network,
        test_background_refresh_thread_updates_cache,
        test_installed_version_matches_package,
    ]
    try:
        for t in tests:
            t()
        print("OK smoke_update_check")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
