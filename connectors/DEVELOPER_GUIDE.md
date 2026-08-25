# Build an AgentLayer connector

This guide covers community read-only connectors. They may be hosted by their
publisher and can expose public DeFi data, analytics, discovery, x402 service
metadata, or marketplace data. They cannot prepare or execute transactions.

## 1. Copy the starter

Copy `templates/read-only` into a new project. During development inside this
repository, install and verify the whole workspace:

```bash
cd connectors
npm install
npm run check
```

The starter requires Node.js 24 or newer and uses the local
`@agentlayer.tech/connector-sdk` workspace package.

## 2. Define identity and permissions

Edit `connector.json`:

- use a stable reverse-domain identifier such as `com.publisher.protocol`
- start at a semantic version such as `1.0.0`
- set the final public HTTPS deployment URL
- list only exact upstream hostnames in `permissions.network_hosts`
- keep `trust: community_read_only`
- keep `transaction_intents: false`
- do not put API keys or other credentials in the manifest

Published `(id, version)` pairs are immutable. Any code, schema, permission,
endpoint behavior, or artifact change requires a new version.

## 3. Declare tools before implementing them

Every tool needs a narrow input and output JSON Schema. Prefer bounded arrays,
string lengths, numeric ranges, `required`, and
`additionalProperties: false`. A connector tool name uses lowercase letters,
digits, and underscores; AgentLayer adds its global namespace automatically.

Read results are untrusted external data. Return normalized fields rather than
passing arbitrary upstream payloads through to the agent.

## 4. Implement handlers

Register exactly one handler for every declared tool with
`defineReadOnlyConnector`. The SDK validates handler input and output. Outbound
requests should:

- use HTTPS
- match `permissions.network_hosts`
- use explicit timeouts
- reject redirects
- cap or paginate upstream results
- keep provider credentials in Railway variables

The starter demonstrates each of these rules. The SDK has no signer, wallet
file, approval-token, transaction, or broadcast API.

## 5. Add fixture coverage

Add valid arguments for every read tool to `conformance.json`:

```json
{
  "schema_version": 1,
  "tools": {
    "get_pools": {
      "arguments": { "chain": "base", "limit": 10 }
    }
  }
}
```

Run SDK and handler tests before deployment:

```bash
npm run check --workspace @agentlayer.tech/read-only-connector-template
```

## 6. Deploy to Railway

Create a new isolated Railway project for the connector and deploy with the
included `Dockerfile` and `railway.toml`. Configure secrets as service
variables. Do not share variables, volumes, service identities, or internal
network access with the AgentLayer wallet or verified-write gateway projects.

Confirm that `GET /healthz` returns the exact manifest identity. Replace the
placeholder `transport.url` with the final Railway HTTPS domain before the
release version becomes immutable.

## 7. Run conformance

From this repository:

```bash
cd connectors
npm run build --workspace @agentlayer.tech/connector-conformance
node conformance/dist/cli.js \
  --manifest ./templates/read-only/connector.json \
  --fixture ./templates/read-only/conformance.json \
  --endpoint https://your-connector.up.railway.app
```

The runner checks the official manifest schema, fixture coverage, health
identity, read responses, schema compatibility, TTL, wrong-identity rejection,
and unknown-tool rejection. A passing report does not grant verified status.

## 8. Install locally

Install and enable the final manifest, then restart the agent host so its tool
catalog is rebuilt:

```bash
wallet connectors install ./connector.json --enable
wallet connectors doctor
wallet connectors list
```

Disable without deleting the pinned manifest:

```bash
wallet connectors disable com.publisher.protocol
```

Community connectors remain read-only even if their server attempts to return
calldata, transaction intents, payment intents, or signed payloads. The wallet
rejects those responses.
