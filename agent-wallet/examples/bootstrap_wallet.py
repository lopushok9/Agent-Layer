"""Example bootstrap entrypoint for OpenClaw plugin startup."""

from __future__ import annotations

import json

from agent_wallet.bootstrap import describe_bootstrap, ensure_solana_wallet_ready


def main() -> None:
    print("Bootstrap configuration:")
    print(json.dumps(describe_bootstrap(), indent=2))
    print()

    result = ensure_solana_wallet_ready()
    print("Bootstrap result:")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
