"""Universal local MCP entry point for the AgentLayer wallet.

The wallet MCP implementation is deliberately shared with the established
Codex and Claude Code bridges. This small neutral entry point makes that
surface available to any stdio MCP client without changing either host plugin.
"""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path


def main() -> None:
    bridge = Path(__file__).resolve().parents[1] / "codex" / "plugins" / "agent-wallet" / "server.py"
    if not bridge.is_file():
        print(
            json.dumps(
                {
                    "error": "AgentLayer MCP bridge is missing from this runtime.",
                    "fix": "Run: wallet install --yes",
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)
    runpy.run_path(str(bridge), run_name="__main__")


if __name__ == "__main__":
    main()
