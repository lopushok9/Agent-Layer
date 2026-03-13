"""Example: host-side onboarding flow for attaching agent-wallet to OpenClaw."""

from __future__ import annotations

import json

from agent_wallet.openclaw_runtime import onboard_openclaw_user_wallet


def main() -> None:
    user_id = "demo-user-123"
    # Set AGENT_WALLET_MASTER_KEY in the environment before first run.
    context = onboard_openclaw_user_wallet(
        user_id,
        sign_only=False,
        network="devnet",
    )

    print("Session metadata:")
    print(context.session_metadata().model_dump_json(indent=2))
    print()

    print("Serializable bundle for OpenClaw runtime:")
    print(json.dumps(context.serializable_bundle(), indent=2))


if __name__ == "__main__":
    main()
