"""Smoke test for local wallet bootstrap file creation."""

from __future__ import annotations

import json
import importlib.util
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.bootstrap import create_solana_wallet_file  # noqa: E402


def main() -> None:
    if importlib.util.find_spec("nacl") is None:
        print("smoke_bootstrap: skipped (PyNaCl not installed in current shell)")
        return

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "wallet.json"
        created = create_solana_wallet_file(path)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 64
        assert created["address"]
        assert created["path"] == str(path)

    print("smoke_bootstrap: ok")


if __name__ == "__main__":
    main()
