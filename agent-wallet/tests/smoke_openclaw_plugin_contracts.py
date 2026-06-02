"""Smoke test that the OpenClaw wallet plugin declares every registered tool contract."""

from __future__ import annotations

import json
import re
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    manifest_path = repo_root / ".openclaw" / "extensions" / "agent-wallet" / "openclaw.plugin.json"
    index_path = repo_root / ".openclaw" / "extensions" / "agent-wallet" / "index.ts"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    declared = manifest.get("contracts", {}).get("tools")
    assert isinstance(declared, list) and declared, "contracts.tools must be a non-empty array"
    assert len(declared) == len(set(declared)), "contracts.tools must not contain duplicate names"

    text = index_path.read_text(encoding="utf-8")
    registered = sorted(set(re.findall(r'name:\s*"([^"]+)"', text)))
    assert sorted(declared) == registered, (
        "contracts.tools must match the registered tool names in index.ts.\n"
        f"declared_only={sorted(set(declared) - set(registered))}\n"
        f"registered_only={sorted(set(registered) - set(declared))}"
    )

    print("smoke_openclaw_plugin_contracts: ok")


if __name__ == "__main__":
    main()
