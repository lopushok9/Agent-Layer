# OpenClaw A2A Gateway

Thin HTTP wrapper that exposes A2A-style endpoints for an existing OpenClaw runtime.

Endpoints:
- `GET /health`
- `GET /.well-known/agent.json`
- `GET /oasf.json`
- `POST /a2a` (proxies to `POST {OPENCLAW_BASE_URL}/v1/responses`)

## Why

Your OpenClaw agent can stay in Telegram, while this gateway provides a public endpoint for registry/discovery and agent-to-agent calls.

## Run

```bash
cd agent-a2a-gateway
cp .env.example .env
# edit .env

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8787
```

If module path with dash causes issues in your environment, always use:

```bash
cd agent-a2a-gateway
uvicorn app:app --host 0.0.0.0 --port 8787
```

## Production (systemd)

Create a systemd unit (adjust paths/user):

```ini
[Unit]
Description=OpenClaw A2A Gateway
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/openclaw/agent-a2a-gateway
EnvironmentFile=/opt/openclaw/agent-a2a-gateway/.env
ExecStart=/opt/openclaw/agent-a2a-gateway/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8787
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now openclaw-a2a-gateway
sudo systemctl status openclaw-a2a-gateway
```

## Test

```bash
curl -s http://127.0.0.1:8787/health
curl -s http://127.0.0.1:8787/.well-known/agent.json | jq
curl -s http://127.0.0.1:8787/oasf.json | jq

curl -s -X POST http://127.0.0.1:8787/a2a \
  -H 'Content-Type: application/json' \
  -d '{"input":"Give me BTC and ETH market overview"}'
```

JSON-RPC-like requests with `id` are also accepted and returned in JSON-RPC shape.

## Nginx Example (VPS)

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # TLS config here (certbot or your certs)

    location /a2a {
        proxy_pass http://127.0.0.1:8787/a2a;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /.well-known/agent.json {
        proxy_pass http://127.0.0.1:8787/.well-known/agent.json;
        proxy_set_header Host $host;
    }

    location /oasf.json {
        proxy_pass http://127.0.0.1:8787/oasf.json;
        proxy_set_header Host $host;
    }
}
```

Keep `OPENCLAW_BASE_URL` internal (`http://127.0.0.1:18789`) and do not expose the raw gateway port publicly.

## 8004 Integration

After public deployment (HTTPS):
- `AGENT_A2A_URL=https://your-domain/a2a`
- `AGENT_OASF_URL=https://your-domain/oasf.json`
- keep `AGENT_MCP_URL` as your MCP endpoint

Then run your registration script again (or update agent URI later).
