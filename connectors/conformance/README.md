# AgentLayer connector conformance

Run Protocol v1 contract checks against a deployed read-only connector:

```bash
npx @agentlayer.tech/connector-conformance \
  --manifest ./connector.json \
  --fixture ./conformance.json \
  --endpoint https://your-connector.up.railway.app
```

The suite validates the official manifest schema, fixture coverage, health
identity, every declared read tool's input/output schemas, response binding and
expiry, and rejection of wrong identities and undeclared tools.

Example fixture:

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

Run conformance against the final immutable deployment URL before publishing a
manifest. A passing report is required for review, but it does not grant
`verified_write` status.
