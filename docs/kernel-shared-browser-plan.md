# Shared Kernel browsers: upgrade and installation contract

Status: broker and automatic client connection implemented in source; deployment,
live isolation checks and upgrade regression checks are pending.

## Product requirement

An ordinary install or update must enable shared browser access without asking
the end user to create a Kernel account, enter an API key, initialize another
vault, or approve a separate gateway setup. Infrastructure provisioning belongs
to the service operator. A host restart after a plugin update remains the normal
way to reload tool schemas and resident workers.

## Compatibility

- Preserve the direct-upgrade floor of `0.1.53` documented in
  `../agent-wallet/UPGRADE_COMPATIBILITY.md`.
- Preserve wallet identity, sealed runtime secrets, existing Kernel keys,
  vault records, and pending operation records during upgrade and rollback.
- Keep existing gateway routes and authentication contracts compatible with
  older plugins. Add browser-specific routes and authentication independently.
- An existing personal Kernel key keeps the current direct connection path.
  Without a personal key, the new client selects shared access automatically.
- Select and persist the connection mode when creating a browser. Never switch
  providers or recreate a browser while executing a private operation.
- Browser records without new shared-access metadata keep their existing
  direct-connection meaning. Do not rewrite existing confirmation summaries or
  reinterpret previously approved operations to add shared access.
- Scope new shared credentials to their browser record and encrypt them using
  local runtime storage. Never replace or export the vault's owner key.
- Do not introduce mandatory migration prompts as part of shared-browser setup.
  Existing explicit owner recovery/migration requirements remain unchanged.
- Feature availability is discovered from the gateway. A temporary service
  failure produces a recoverable service error before private execution, not a
  requirement for the user to obtain a personal Kernel key.

## Proposed data path

1. The local backend automatically establishes an installation identity.
2. The gateway authenticates the installation and creates a separate Kernel
   browser, recording its authenticated owner, expiration, and key identifiers.
3. The gateway issues a short-lived Kernel key with `browsers:use` restricted
   to that existing browser resource. No project wildcard, browser creation,
   key management, shared profiles, or shared vault grants reach the client.
4. The local backend stores the session credentials in its encrypted browser
   record and calls Kernel directly for public preparation and private fill.
5. Existing local preview/prepare/execute approvals and private-browser locks
   remain authoritative. The model receives only opaque references and safe
   results. PAN/CVV do not traverse the gateway.
6. Close deletes the browser and revokes its temporary key. Server expiration
   and cleanup also work after client crashes. Key expiration alone is not
   sufficient to revoke previously obtained connection URLs.

The gateway's current shared bearer token is not a user identity. New browser
routes must enforce ownership independently of the optional bearer setting.
An installation-generated identifier alone is not authenticated identity;
the client must prove possession of its individual credential. Quotas must also
include service-wide limits because installation identities alone do not stop
one person from enrolling multiple clients.

Kernel and authorized administrators of the Kernel organization remain trusted
processors. This design separates end users and keeps card payloads off the
gateway request path; it does not provide cryptographic isolation from those
administrators.

## Release acceptance criteria

Before enabling the shared capability for public installs, verify:

- Fresh install without a Kernel key can create and close a shared browser.
- Direct upgrades from `0.1.53` and the latest published stable preserve wallet
  addresses, sealed secrets, vault contents, and host registrations.
- Existing personal-key users keep their connection and credentials.
- Existing direct browser records and operation summaries remain readable.
- A gateway without the new capability does not break existing tools or direct
  Kernel access; deployment sequencing cannot force manual reconfiguration.
- User A's credential cannot list, control, close, or mint access to user B's
  browser, including when a different browser ID is supplied deliberately.
- Credentials and card payloads are absent from model output, gateway request
  bodies, telemetry, and ordinary logs.
- Upgrade, restart, expiration, and rollback never refill or resubmit an
  operation that reached private dispatch or `outcome_unknown`.

These are future release gates, not claims of completed verification.

## Kernel references

- https://www.kernel.sh/docs/info/api-keys
- https://www.kernel.sh/docs/info/api-key-permissions
- https://www.kernel.sh/docs/info/projects
- https://www.kernel.sh/docs/security
- https://www.kernel.sh/docs/browsers/profiles
