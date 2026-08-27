# Releasing connector npm packages

The public packages are:

- `@agentlayer.tech/connector-sdk`
- `@agentlayer.tech/connector-conformance`

Both packages use the same immutable version. Beta versions are published under
the npm `beta` dist-tag; stable versions use `latest`.

## One-time namespace bootstrap

npm requires the first publication of a new package to use an authenticated
maintainer session. From a clean checkout of the exact release commit:

```bash
cd connectors
npm ci
npm run check
npm run check:pack
npm login
cd sdk-typescript && npm publish --access public --tag beta
cd ../conformance && npm publish --access public --tag beta
```

Use an npm account with 2FA and permission to publish under `@agentlayer.tech`.
Do not create or commit an npm token.

After both packages exist, configure each package's npm trusted publisher with:

- repository: `lopushok9/Agent-Layer`
- workflow: `connectors-publish.yml`
- environment: `npm-connectors`

Protect the GitHub `npm-connectors` environment and keep the workflow's
`id-token: write` permission. No `NODE_AUTH_TOKEN` secret is used.

## Subsequent releases

1. Set the same version in the SDK, conformance package, template dependency,
   reference connector dependency, and `connectors/package-lock.json`.
2. Run `npm ci`, `npm run check`, and `npm run check:pack` in `connectors/`.
3. Merge the reviewed release commit to `main`.
4. Create and push the exact tag `connectors-v<version>` from that main commit.
5. Verify both registry artifacts, their provenance, and the expected dist-tag.

Never reuse a published version. A failed partial release is repaired with a
new version rather than overwriting the existing SDK artifact.
