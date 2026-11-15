"""Two local demo merchants for the treasury routing demo.

  /x402/market-data  answers HTTP 402 with x402 v1 terms (USDC on Base)
  /checkout/saas     a card-only checkout page (no x402)

    python agent-wallet/examples/demo_merchants.py   # http://127.0.0.1:8799
"""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

PAY_TO = os.getenv("DEMO_X402_PAY_TO", "0x000000000000000000000000000000000000dEaD")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/x402/market-data"):
            body = {"x402Version": 1, "error": "X-PAYMENT header is required", "accepts": [{
                "scheme": "exact", "network": "base", "maxAmountRequired": "50000",
                "resource": "http://127.0.0.1:8799/x402/market-data", "description": "BTC order book snapshot",
                "mimeType": "application/json", "payTo": PAY_TO, "maxTimeoutSeconds": 60,
                "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "extra": {"name": "USD Coin", "version": "2"}}]}
            self._send(402, json.dumps(body), "application/json")
        elif self.path.startswith("/checkout"):
            self._send(200, "<html><body><h1>SaaS seat</h1><form>Card number <input name=cc> <button>Pay $12</button></form></body></html>", "text/html")
        else:
            self._send(404, "not found", "text/plain")

    def _send(self, code, text, ctype):
        data = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(os.getenv("DEMO_MERCHANT_PORT", "8799"))
    print(f"demo merchants on http://127.0.0.1:{port}")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
