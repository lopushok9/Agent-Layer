"""Smoke test for the Codex bridge's background resident-read-worker prewarm."""

from __future__ import annotations

import importlib.util
import os
import tempfile
import threading
from pathlib import Path


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    server_path = repo_root / "codex" / "plugins" / "agent-wallet" / "server.py"

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["OPENCLAW_HOME"] = tmp
        os.environ.pop("AGENT_WALLET_PREWARM_READ_WORKER", None)

        module = _load_module(server_path, "codex_agent_wallet_server_prewarm")

        # Enabled by default: prewarm spawns the resident worker in the
        # background without blocking the caller.
        warmed = threading.Event()
        warm_calls: list[tuple[str, dict]] = []

        class FakeWorker:
            def warm(self) -> None:
                warm_calls.append(("warm", {}))
                warmed.set()

        def fake_resident_read_worker_for_config(user_id, config):
            warm_calls.append(("lookup", {"user_id": user_id, "config": dict(config)}))
            return FakeWorker()

        module._resident_read_worker_for_config = fake_resident_read_worker_for_config
        module._prewarm_resident_read_worker()
        assert warmed.wait(timeout=5), "prewarm did not call worker.warm() in time"
        assert warm_calls[0][0] == "lookup"
        assert warm_calls[1][0] == "warm"

        # Opt-out: AGENT_WALLET_PREWARM_READ_WORKER=0 must skip the background
        # spawn entirely, leaving no worker lookup.
        second_calls: list[str] = []

        def fake_resident_read_worker_for_config_should_not_run(user_id, config):
            second_calls.append("lookup")
            return FakeWorker()

        module._resident_read_worker_for_config = fake_resident_read_worker_for_config_should_not_run
        os.environ["AGENT_WALLET_PREWARM_READ_WORKER"] = "0"
        try:
            module._prewarm_resident_read_worker()
        finally:
            os.environ.pop("AGENT_WALLET_PREWARM_READ_WORKER", None)
        assert second_calls == [], "prewarm ran despite AGENT_WALLET_PREWARM_READ_WORKER=0"

        # A worker lookup failure must not raise out of the background thread.
        def fake_resident_read_worker_for_config_raises(user_id, config):
            raise RuntimeError("boom")

        module._resident_read_worker_for_config = fake_resident_read_worker_for_config_raises
        module._prewarm_resident_read_worker()  # should not raise synchronously
        for thread in threading.enumerate():
            if thread.name == "agent-wallet-read-worker-prewarm":
                thread.join(timeout=5)

    print("smoke_codex_plugin_read_worker_prewarm: ok")


if __name__ == "__main__":
    main()
