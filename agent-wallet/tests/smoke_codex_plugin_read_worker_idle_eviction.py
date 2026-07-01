"""Smoke test: idle resident read workers for stale configs get reaped."""

from __future__ import annotations

import importlib.util
import os
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
        os.environ["AGENT_WALLET_READ_WORKER_IDLE_SECONDS"] = "1"
        try:
            module = _load_module(server_path, "codex_agent_wallet_server_idle_eviction")

            closed: list[str] = []

            # A worker sitting under an old, no-longer-active config key
            # (e.g. the user switched Solana network mid-session) that has
            # been idle well past the 1s threshold configured above.
            stale = module._ResidentReadWorker(user_id="u", config={"network": "devnet"})
            stale._last_used -= 9999
            original_close = stale.close

            def fake_close():
                closed.append("stale")
                original_close()

            stale.close = fake_close
            module.resident_read_workers["stale-key"] = stale

            # Looking up a *different* config must reap the stale worker.
            active = module._resident_read_worker_for_config("u", {"network": "mainnet"})
            assert closed == ["stale"], "idle worker for a stale config was not reaped"
            assert "stale-key" not in module.resident_read_workers
            assert module.resident_read_workers.get(
                module._resident_worker_cache_key("u", {"network": "mainnet"})
            ) is active

            # Re-fetching the same (now active) config must never evict
            # itself, no matter how idle it looks, and must return the same
            # cached instance rather than respawning.
            active._last_used -= 9999
            active.close = lambda: closed.append("active-should-not-close")
            again = module._resident_read_worker_for_config("u", {"network": "mainnet"})
            assert again is active
            assert "active-should-not-close" not in closed
        finally:
            os.environ.pop("AGENT_WALLET_READ_WORKER_IDLE_SECONDS", None)

    print("smoke_codex_plugin_read_worker_idle_eviction: ok")


if __name__ == "__main__":
    main()
