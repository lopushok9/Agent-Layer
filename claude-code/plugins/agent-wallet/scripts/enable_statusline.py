#!/usr/bin/env python3
"""Add the wallet-balance statusLine to the user's Claude Code settings.json.

Stdlib-only (runs under the system python3, not the wallet backend's venv).
Refuses to overwrite a statusLine the user configured for something else —
this only ever runs when the user explicitly invokes /wallet-statusline, but
it still shouldn't clobber an unrelated existing config.
"""
import json
import sys
from pathlib import Path

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: enable_statusline.py <path-to-wallet_statusline.py>", file=sys.stderr)
        return 2
    script_path = sys.argv[1]
    command = f"python3 {script_path}"

    settings = {}
    if SETTINGS_PATH.exists():
        settings = json.loads(SETTINGS_PATH.read_text())

    existing = settings.get("statusLine")
    if existing and existing.get("command") != command:
        print(
            f"A different statusLine is already configured in {SETTINGS_PATH}: "
            f"{existing!r}. Not overwriting it — run /statusline delete first "
            "if you want to replace it, then re-run /wallet-statusline.",
            file=sys.stderr,
        )
        return 1

    settings["statusLine"] = {
        "type": "command",
        "command": command,
        "refreshInterval": 30,
    }

    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n")
    tmp.replace(SETTINGS_PATH)
    print(f"statusLine configured in {SETTINGS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
