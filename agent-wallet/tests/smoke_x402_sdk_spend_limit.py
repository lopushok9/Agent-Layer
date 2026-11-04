"""Exercise the installed x402 SDK's independent per-payment limit."""

from agent_wallet.providers.x402 import _bind_sdk_spend_limit
from x402 import x402Client
from x402.schemas import PaymentRequirements


NETWORK = "eip155:8453"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


class ExactScheme:
    scheme = "exact"

    def find_default_asset(self, asset, network):
        if network == NETWORK and asset.lower() == USDC.lower():
            return {"decimals": 6, "asset": USDC, "symbol": "USDC"}
        return None


def requirement(amount, asset=USDC):
    return PaymentRequirements.model_validate({
        "scheme": "exact", "network": NETWORK, "asset": asset,
        "amount": amount, "payTo": "0x1111111111111111111111111111111111111111",
        "maxTimeoutSeconds": 300,
    })


def rejected(client, req):
    try:
        client._select_requirements_v2([req])
    except Exception as exc:
        assert "spend_controls" in str(exc)
        return
    raise AssertionError("SDK accepted a requirement beyond the bound")


def main():
    client = x402Client()
    client.register(NETWORK, ExactScheme())
    rejected(client, requirement("4990000"))
    _bind_sdk_spend_limit(client, {"network": NETWORK, "asset": USDC, "amount": "4990000"})
    assert client._select_requirements_v2([requirement("4990000")]).amount == "4990000"
    rejected(client, requirement("4990001"))
    rejected(client, requirement("100", "0x2222222222222222222222222222222222222222"))
    _bind_sdk_spend_limit(object(), {"network": NETWORK, "asset": USDC, "amount": "4990000"})
    print("smoke_x402_sdk_spend_limit: ok")


if __name__ == "__main__":
    main()
