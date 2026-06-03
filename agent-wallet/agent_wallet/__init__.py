"""OpenClaw agent wallet package."""

# Keep in sync with package.json, pyproject.toml, and the npm installer version.
# scripts/check_release_version.mjs enforces this on release.
__version__ = "0.1.35"

__all__ = [
    "config",
    "exceptions",
    "models",
    "openclaw_runtime",
    "providers",
    "update_check",
    "validation",
    "wallet_layer",
]
