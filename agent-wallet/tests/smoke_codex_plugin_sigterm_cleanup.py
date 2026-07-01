"""Smoke test: SIGTERM closes resident read workers before the process exits."""

from __future__ import annotations

import importlib.util
import os
import signal
import tempfile
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
        module = _load_module(server_path, "codex_agent_wallet_server_sigterm")

        closed: list[str] = []

        class FakeWorker:
            def close(self) -> None:
                closed.append("worker")

        module.resident_read_workers["k"] = FakeWorker()

        # Never let the handler actually terminate this test process: capture
        # what it would have done instead of calling the real os.kill/signal.
        kill_calls: list[tuple[int, int]] = []
        original_kill = module.os.kill
        original_signal = module.signal.signal
        module.os.kill = lambda pid, sig: kill_calls.append((pid, sig))
        module.signal.signal = lambda sig, handler: None
        try:
            module._handle_termination_signal(signal.SIGTERM, None)
        finally:
            module.os.kill = original_kill
            module.signal.signal = original_signal

        assert closed == ["worker"], "SIGTERM handler did not close resident workers"
        assert module.resident_read_workers == {}
        assert kill_calls == [(os.getpid(), signal.SIGTERM)], (
            "SIGTERM handler must re-raise the signal after cleanup so the "
            "process still exits the normal way"
        )

    print("smoke_codex_plugin_sigterm_cleanup: ok")


if __name__ == "__main__":
    main()
