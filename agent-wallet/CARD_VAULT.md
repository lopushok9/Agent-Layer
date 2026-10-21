# Private card vault

Implementation and research notes, 2026-10-21. This is our own local vault;
AgentCard, 1Claw, Bitwarden and Infisical are research references, not dependencies.
Fixed HTTPS and managed Kernel browser executors are included. Local Chrome
autofill, vault cloud sync and AgentCard integration remain separate.

## Automatic setup and owner access

On macOS, installation and updates automatically provision the card vault.
The backend also provisions a missing vault for the actual runtime user before
card requests, so a custom host identity needs no manual initialization.
No new password is created. The vault private key lives in the **login Keychain**
and access requires its system password dialog. Normally that password matches
the macOS account password; if the user separately changed the login Keychain
password, macOS asks for that password. Python never receives the password.

```bash
wallet vault status
wallet vault list
wallet vault show <reference>
wallet vault refresh <reference>
wallet vault reveal <reference>
wallet vault reveal <reference> --output ~/private-card.json
wallet vault remove <reference>
```

`status` inspects public local metadata. Other owner read commands require a
terminal and system authentication for each invocation; there is no persisted
unlock session. `list`, `show` and `refresh` display masked summaries with issuer
card IDs and receipt information. `reveal` displays PAN, expiration, CVV, balance
and billing address, without provider tokens. `--output` explicitly writes a new
plaintext JSON file with mode 0600 and refuses overwrites; remove it after use.
`remove` deletes only the local encrypted record after confirmation, not the
issuer card or copies in backups. Node inherits terminal IO without buffering
secret output or attaching it to installer telemetry.

The CLI resolves identity in the same order as the Codex wallet bridge:
`AGENT_WALLET_USER_ID`, `OPENCLAW_AGENT_WALLET_USER_ID`, configured OpenClaw
`plugins.entries.agent-wallet.config.userId`, then `USER`. Explicit `--user-id`
selects a different identity. `OPENCLAW_HOME` selects the wallet state home.
Never select the repository as the state home.

```bash
wallet vault reveal <reference> --user-id my-other-runtime-user
```

For source-tree development before installing this runtime:

```bash
PYTHONPATH=agent-wallet agent-wallet/.runtime-venv/bin/python -m agent_wallet.card_vault_cli status
```

The internal `provision` subcommand runs without a terminal, without reading any
private key, and with native authentication UI disabled. Repeated provisioning
checks the existing key and its ACL; it never replaces the recipient. A locked
or unavailable Keychain is reported in installation results and checked again
before card payment. Failure does not disable unrelated wallet features.
Linux and Windows system-authenticated card vaults are not implemented in this
change. Installation reports that limitation and uses no plaintext or silently
readable key fallback for cards.

## Key hierarchy and storage

The owner has a random X25519 key pair. The runtime can use its public key to
encrypt independently randomized card records through libsodium sealed boxes.
It needs no private key or owner interaction to deposit a card.
[Libsodium sealed boxes](https://libsodium.gitbook.io/doc/public-key_cryptography/sealed_boxes).

```text
~/.openclaw/card-vault/<sha256(runtime-user-id)>/
  vault.json          # v2: public key, scope, protection type, random key ID
  <random-id>.card    # encrypted issuer order, tokens, details and payment receipt
  <random-id>.update  # latest details, sealed to owner public key
  <random-id>.auth    # rotated credentials, sealed to owner public key
  <random-id>.agent   # runtime-encrypted safe metadata + pending retrieval job
  <random-id>.use     # runtime-encrypted normalized card fields for executors
  <operation-id>.operation # runtime-encrypted immutable request + authorization/outcome
  <random-id>.lock    # serializes record refresh/removal against initial capture
  .owner.lock         # serializes provisioning, migration and owner operations

macOS login Keychain:
  service = namespace derived from the stable vault directory
  account = user scope + random key ID
  secret  = 32-byte private decryption key
```

A v2 `vault.json` contains no private key or password wrapper. The original card record
remains compatible with v1. Scope, record ID and snapshot purpose are inside
authenticated ciphertext to reject cross-user, cross-record and snapshot
substitution. The original receipt is preserved when refresh writes snapshots. Files use 0600, the user
vault directory requires 0700, and reads reject symlinks, unsafe ownership,
permissive modes and oversized files. Writes use atomic replacement and fsync.
Missing Keychain entries or missing metadata for existing encrypted cards cause
an error; automatic setup does not generate a replacement key over old cards.

`card_vault_keychain.py` calls Security.framework directly through ctypes. It
uses a separate service from the wallet boot-key store: the boot-key store's
silent access policy is inappropriate for card decryption. No `security -w`
subprocess, key in argv, plaintext fallback, or extra password collection is used.

The login Keychain uses file-based ACLs. Creation sets an empty trusted-app list
and requests a password for restricted access. Existing ACLs for wildcard,
decryption and ACL modification are checked before use, and again after secret
retrieval. An allow-all or trusted-application ACL is rejected. Native creation
and readiness checks disable UI; only explicit owner unlock allows a system
dialog. Keys are not cached between CLI invocations.

On macOS 10.13.1 and later, Apple documents that the OS ignores the old prompt
selector and requires the Keychain password when prompting to trust an app;
this implementation requires that OS version and an empty trusted-app list.
Persisted prompt flags may be normalized by the framework. Choosing permanent
trust, or manually weakening the entry's ACL, causes subsequent validation to
fail closed. [Apple SecACLCopyContents](https://developer.apple.com/documentation/security/secaclcopycontents(_:_:_:_:)),
[Apple Keychain ACLs](https://developer.apple.com/documentation/security/access-control-lists).

This is a login-Keychain password implementation, not Touch ID or Secure Enclave
storage. Apple's data protection Keychain and biometric access-control mechanism
require different signing and packaging for command-line tools.
[Apple TN3137](https://developer.apple.com/documentation/technotes/tn3137-on-mac-keychains).
The file-based APIs are deprecated by Apple but remain available; migration to a
properly signed native application is a future packaging task.

## Agent catalog and delayed issuance

The tools are available through the shared wallet adapter in Codex and OpenClaw:

| Tool | Behavior |
| --- | --- |
| `list_saved_cards(limit=20, after=...)` | Cached catalog, up to 100 records per page; returns `next_cursor`. No issuer request. |
| `get_saved_card_status(vault_reference, refresh=true)` | Checks a pending order when its next permitted check is due. Set `refresh=false` for cached metadata. |
| `refresh_saved_card(vault_reference)` | Explicitly checks the saved pending order. Never creates or pays for another card. |

All three return allowlisted metadata: opaque reference, provider, card type,
status, last four digits, cached balance, `details_stored`, timestamps,
`refresh_available`, `refresh_state` and retry timing. They do not return PAN,
CVV, issuer card IDs, credentials, payment receipts or raw issuer errors. The
adapter scopes access to the current runtime user. No system password is needed
for these operations. Full owner reveal still requires system authentication.

New pending orders include a separately encrypted retrieval job in `.agent`.
A purpose- and user-scoped HMAC-SHA256 key derived from the existing sealed wallet
runtime master key protects this state with SecretBox. The job contains only
issuer card ID/type, authentication tokens and retry bookkeeping; it contains no
PAN or CVV. The runtime master key must be available before a card purchase.
The owner private key is never used by agent refresh: received details are sealed
to its public key in `.update`. Rotated credentials are saved to the runtime job
first and then to the owner-sealed `.auth` snapshot. Credentials are removed from
the active job only after details are durably saved or a terminal issuer state
or authentication rejection is confirmed.

This enables unattended delayed issuance, with a specific security tradeoff:
the backend can use pending issuer tokens to retrieve plaintext card details.
An attacker controlling that runtime or its master key can do the same while
those credentials remain valid. Laso tokens may have account-wide privileges;
fixed endpoints and card-ID checks constrain our code, not the issuer token's
cryptographic permissions. This is not owner-authenticated isolation during the
pending period. The model itself receives only the safe tool result.

Checks are driven by tool calls, with no always-running background service.
The initial US poll is bounded to five attempts three seconds apart. Subsequent
checks enforce at least three seconds for US cards and 60 seconds for
international cards; transient errors use bounded backoff up to 300 seconds.
Agents should honor `retry_after_seconds` and check in a later turn or scheduled
run. Once credentials are retired, status and balance remain cached snapshots;
these tools do not provide continuous live balance refresh for ready cards.

Pending credentials have a seven-day local lifetime. Listing reports expired
jobs as unavailable for refresh; a later refresh/status call clears their active
credentials without contacting the issuer. There is no background eraser or
remote token revocation. Backups, old ciphertext and filesystem snapshots may
retain credentials; local deletion does not invalidate them at Laso. Removal
clears the runtime job before deleting the owner-encrypted files.

Older records without an agent catalog appear as `owner_access_required`.
One authenticated owner CLI read imports their metadata and eligible pending job.
A missing runtime key does not block the owner's authenticated card reveal.

## Private use without additional owner prompts

`use_saved_card` supports `preview`, `prepare` and `execute`. One normal host
confirmation covers the exact outbound request and, optionally, new Laso card
issuance. No second permission grant, unlock session or owner Keychain prompt
is required for saving, waiting for issuance or passing fields to the executor.
Prepare requires `user_intent=true`; execute requires the normal host-issued
approval token with the existing mainnet confirmation rule. Generic HTTPS card
use does not infer a spend amount for autonomous budget authorization.

Example preview for a merchant API that accepts card details directly:

```json
{
  "mode": "preview",
  "issue_card": {"card_type": "us", "amount_usd": "20.00"},
  "purpose": "Pay the requested subscription at the agreed price",
  "request": {
    "url": "https://merchant.example/api/subscription",
    "method": "POST",
    "json": {
      "amount_cents": 2000,
      "currency": "USD",
      "card_number": "{{card.number}}",
      "cvv": "{{card.cvv}}",
      "exp_month": "{{card.exp_month}}",
      "exp_year": "{{card.exp_year}}"
    }
  }
}
```

This is an illustrative merchant contract, not a working integration for an
arbitrary subscription site. Supply `vault_reference` instead of `issue_card`
to use an existing saved card. The exact HTTPS URL, method, public headers,
request template and its digest, wallet owner/network, user scope, card
reference, expiry and optional Laso debit are bound to `confirmation_summary`.
The issuance quote is frozen; execution does not silently reprice or fall back
to a fresh unpaid probe. All template values are public or opaque field
placeholders. Card secrets are accepted only in body values, never URLs,
headers or object keys. JSON and form bodies are supported.

After the user confirms in the host, execute with the returned `operation_id`.
If issuance is delayed, `continue_vault_operation(operation_id)` resumes the
same already authorized task without a fresh token. It cannot authorize a
prepared task or alter any parameters. Authorization lasts 48 hours from
preparation. `get_vault_operation(operation_id)` reads cached state without
network access. An expired operation must be prepared/confirmed again.
`cancel_vault_operation(operation_id, user_intent=true)` stops the local task
before its next outbound action without another approval. It preserves any
already issued card and cannot reverse a sent request or refund a payment.
There is no automatic recurring payment authority or background worker.

New cards store a `.use` capsule before the pending issuer job is retired.
It contains an allowlist of normalized PAN, CVV, expiry and billing fields,
encrypted with SecretBox under a separate purpose/user-scoped HMAC-SHA256 key
derived from the existing sealed runtime master. The owner sealed receipt and
latest snapshots remain available through the authenticated CLI. Old cards
need one authenticated owner CLI read to populate their capsule. The catalog
exposes `private_use_stored`, never the field values. Local removal clears the
capsule first and serializes with execution on the card lock.

**Security tradeoff:** the runtime can now decrypt stored card capsules after
issuance is complete. Owner authentication protects the manual reveal path and
owner private key; it is no longer the only cryptographic path to the card
values. Code or an attacker possessing the runtime master and vault files can
read the capsule. This design keeps secrets out of normal agent tool results;
it does not isolate them from arbitrary same-user code that can read the runtime
master. Host confirmation cannot substitute for operating-system isolation.

The fixed HTTPS consumer has the following boundaries; Kernel is described below. It does not execute a
caller-selected program, load plugins or accept callbacks from model input.
Before sending secrets it validates all DNS answers as public addresses, pins
the connection to one address and verifies TLS against the original hostname.
Redirects, environment proxies and transport retries are disabled. It never
returns provider bodies, headers, cookies, redirects or remote error messages.
IPv4 is preferred when validated DNS answers contain both address families.
A persisted `dispatching` state precedes any outbound request. A caught
`httpx.ConnectError` or `ConnectTimeout` on this fresh, retry-free connection
returns to `authorized` with `last_attempt_not_sent=true` and a short retry hint;
`continue_vault_operation` can retry the unchanged plan under its original
unexpired authorization. This invocation does not retry automatically.
Crashes, read/write failures, cancellation and other indeterminate transport
errors remain `outcome_unknown`, with no automatic resend. Completed operations
return their stored result on replay. A stable idempotency header is sent as
an additional precaution, not as a guarantee that every merchant honors it.

Similarly, issuance is recorded before signing/payment. A crash can resume a
captured card receipt, but an uncertain issuance is never purchased again.
The operation and card locks serialize concurrent execution across processes;
authorization and terminal state survive host restarts. Lost outcome writes
leave a dispatch marker and therefore stop automatic retries.

`request_succeeded` means only that the endpoint returned a 2xx status.
`payment_confirmed` remains false because this executor does not interpret
merchant receipts. It cannot enforce a dollar ceiling independently of the
approved request's semantics; a merchant-specific consumer must verify the
actual amount/currency. Kernel checkout adds a dedicated browser consumer below.
Arbitrary secret exec, token-returning processor chains and subscription renewal
engines are not included.

## Legacy migration and backups

Older local v1 vaults contain a password-encrypted private key (Argon2id and
SecretBox). Installation reports `migration_required` without changing them.
On the first owner CLI operation, or explicitly with:

```bash
wallet vault migrate
```

The CLI asks for the **old vault password once**, saves the same private key to
the protected login Keychain, verifies it with system authentication, and only
then atomically replaces the old password wrapper with v2 public metadata.
Existing card ciphertext and public key stay identical. A denied authentication
or failed write preserves the original wrapper. The system password is never
requested through `getpass`; that input exists only for legacy migration.
`change-password` explains that system Keychain settings now manage the password.
`init` is retained as an idempotent setup alias, not a required user step.

The runtime catalog and pending jobs also depend on the sealed wallet runtime
master key. Losing that key requires an authenticated owner read to rebuild them;
it does not change how owner card ciphertext is decrypted. Executor capsules
also depend on this master key and can be rebuilt from authenticated owner reads.

Backing up only the vault directory is **insufficient** for v2: its private key
is in the system login Keychain and must be preserved through appropriate system
backup/migration. Changing the vault location changes its Keychain namespace.
There is no application recovery key or portable recovery export in this change;
missing system keys are never silently recreated. Old v1 backups still carry
their old password protection. Initialization interrupted after adding a system
key but before publishing metadata may leave an unused protected Keychain entry.

## Issuance, refresh and failures

```mermaid
sequenceDiagram
    participant I as Installer / updater
    participant A as Agent / host
    participant B as Python backend
    participant L as Laso
    participant V as Local vault
    participant K as macOS Keychain
    I->>K: Create restricted private-key entry, no secret read
    I->>V: Save public recipient metadata
    A->>B: Card preview and approved x402 execution
    B->>V: Check readiness and save encrypted request receipt
    B->>L: Pay and order
    L-->>B: Order and authentication credentials
    B->>V: Encrypt and persist immediately
    B->>L: Poll US card privately, up to 5 attempts
    L-->>B: Card details
    B->>V: Persist encrypted details
    B-->>A: Reference, status, last4
    A->>B: get_saved_card_status(reference), later
    B->>V: Read runtime-encrypted pending job
    B->>L: Retrieve saved order, refresh token if needed
    L-->>B: Card details or pending status
    B->>V: Seal details; retire completed retrieval job
    B-->>A: Masked metadata and retry timing
    Note over K: Owner later invokes wallet vault reveal
    K->>K: System password authentication
    K-->>B: Private key for owner CLI process
```

The wrapper intercepts both x402 preview and execution for fixed Laso card
routes, including unexpectedly successful previews. It replaces issuer response
bodies wholesale with an allowlisted summary, not field-by-field redaction.
Direct agent requests to `/get-card-data` are blocked. The private refresh backend uses fixed
HTTPS Laso routes, rejects redirects, bounds response sizes and suppresses
remote error bodies. Wallet preview, approval tokens and signing policy stay
in the existing wallet backend.

The initial order and credentials are on disk before polling. Nested `card` and
`auth` responses are supported. US polling is bounded to five attempts three
seconds apart. International queued orders are saved without repeated polling.
Owner and agent refresh handle expired credentials via fixed `POST /auth`, persisting
rotated tokens before retrying card retrieval; it does not buy another card.
[Laso lifecycle](https://docs.laso.finance/guides/card-lifecycle),
[Laso authentication](https://docs.laso.finance/guides/authentication).

A payment or retrieval error never triggers a second purchase. Preallocated
receipts identify uncertain execution, and provider error details are retained
encrypted where possible. A transport failure before receiving card ID/tokens,
or a disk failure after settlement, can still require issuer support. This is
not an exactly-once ordering protocol or guaranteed recovery of every paid order.

## Research and future consumer boundary

| Reference | Relevant pattern |
| --- | --- |
| [AgentCard Vault](https://agentcard.com/vault) and [privacy](https://agentcard.com/privacy) | Device encryption and separate purchase approval; saved and issued cards have different storage paths. Marketing does not establish exact internals. |
| [1Claw cards](https://docs.1claw.xyz/docs/guides/payment-cards) | Laso/x402 ordering with approval and human-gated reveal; agents cannot reveal by default. |
| [Bitwarden cards](https://bitwarden.com/help/auto-fill-card-id/) and [CLI](https://bitwarden.com/help/cli/) | Owner vault access plus an independent browser autofill consumer. |
| [Infisical Agent Vault](https://github.com/Infisical/agent-vault) | Credential use inside a controlled proxy/process rather than returning secrets to the model. |
| [botiverse agent-vault](https://github.com/botiverse/agent-vault) | Safe output shapes and explicit owner reveal. Terminal checks alone are not authentication. |

A future local Chrome autofill consumer can use an extension and native messaging
host with grants bound to card, HTTPS origin,
tab/frame and allowed fields. The model receives an opaque reference and result.
Native messaging allowlists extension IDs; it does not validate merchant origins.
[Chrome native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging).
No native messaging host or local Chrome profile manipulation is implemented.
Cloud browser checkout uses the managed Kernel consumer below.

## Security boundaries and verification

The runtime and issuer see plaintext at issuance. During owner access, the CLI
receives the private key in memory; Python cannot guarantee full zeroization.
The public recipient is trusted local state. Sealed boxes authenticate ciphertext,
not senders, so processes with write access can inject bogus encrypted records.
This does not protect against root, malicious modified local code, keyloggers or
process inspection after authentication. PTYs can be created by agents; the OS
Keychain policy, not the terminal check, is the decryption boundary. The vault
lives on the backend machine; a VPS deployment does not put it on the owner's PC.

This is not a hosted card-storage or PCI-compliance claim. Retained CVVs have
specific restrictions in merchant/concierge systems.
[PCI SSC explanation](https://www.pcisecuritystandards.org/faqs/1280/).

Offline tests cover record encryption, legacy and system access, idempotent
provisioning without key reads, system-authentication denial, migration rollback,
missing-key protection, issuer output isolation, refresh-token rotation, CLI
export and installer wiring. Catalog tests cover safe output allowlists,
user isolation, delayed issuance without owner unlock, token rotation across
sessions, rate limits, concurrent refresh, expiry, deletion, durable failure
recovery and matching Python/TypeScript tool schemas. A macOS native test uses a disposable explicitly
selected keychain to check persisted ACLs, silent-read denial and no overwrite;
it does not use the login keychain or show authentication UI. Real owner-password
dialog success and live card issuance are not exercised by these automated tests.

The supplied X post was not retrieved during initial research because MCP calls
were blocked by host approval policy. No conclusion here relies on that post.

## Kernel browser checkout

Kernel runs the browser in its cloud. No local Chromium, Playwright installation,
Kernel SDK or Vercel browser account is required; the wallet uses the fixed
`https://api.onkernel.com` REST API with the existing HTTP client.

Connect once in the owner's terminal:

```bash
wallet vault kernel-connect
wallet vault kernel-status
# Optional: remove the locally saved API key
wallet vault kernel-disconnect
```

`kernel-connect` uses hidden terminal input and validates the key with a read-only
browser listing. It merges `kernel_api_key` into the existing encrypted runtime
bundle without changing wallet/approval keys. It never accepts a key argument,
prints the key, creates a browser during connection, or stores it in host config.
`kernel-status` reports configuration only, not current API availability.
Connection is shared by the local runtime; browser state remains user scoped.
Disconnect does not revoke the key in Kernel's dashboard or cancel active tasks;
close sessions first. The commands become available after installing this revision.

### Agent workflow

1. `kernel_browser(action="open", url=..., user_intent=true)` creates a billable
   headless session with a 300-second inactivity timeout. No profile or replay is
   requested and browser telemetry capture is disabled. The model receives an
   opaque `browser_reference`, public text/field metadata and iframe metadata;
   no API key, remote session ID, CDP/live-view URL, cookies or input values.
2. Use `observe` / `inspect(selector)` to inspect public page content. `click`,
   `fill`, `select` and `press` handle ordinary public checkout setup and require
   `user_intent=true`. These are real browser interactions and can have effects;
   use them only for the user's task, never for entering card values or bypassing
   `use_saved_card`. Page content is untrusted and cannot authorize a purchase.
3. Preview `use_saved_card` with `checkout` instead of `request`, and either an
   existing `vault_reference` or `issue_card`. The exact plan enters the normal
   wallet confirmation summary, including any Laso debit. Example plan fragment:

```json
{
  "browser_reference": "<opaque 32-character reference>",
  "page_url": "https://merchant.example/checkout",
  "fields": [
    {"field": "card.number", "selector": "#card-number"},
    {"field": "card.cvv", "selector": "#cvv"},
    {"field": "card.expiry_short", "selector": "#expiry"}
  ],
  "total_selector": "#order-total",
  "expected_total": "$19.99",
  "amount_usd": "19.99",
  "submit_selector": "#pay",
  "success_selector": "#payment-success"
}
```

This example is illustrative; derive real selectors from the merchant page.
Each field may specify an exact `frame_url` for a hosted payment iframe;
otherwise it targets the main frame. Zero/multiple matching frames or fields
fail closed. Expiry formats include `card.expiry` (MM/YYYY), `card.expiry_short`
(MM/YY), separate month/year and `card.exp_year_short` (YY). Select fields match
option values. Missing billing values do not become empty fabricated addresses.
Totals currently require an unambiguous USD string such as `$19.99` or `19.99 USD`.

4. Execute with the normal host approval. The runtime reserves the session before
   issuance, checks the exact page, displayed total, field targets and initially
   absent/hidden success marker, then issues/saves/waits for the card if needed.
   Reservation disables ordinary browser inspection and interaction.
5. Resolve all requested card fields locally before setting `dispatching` or
   making the browser `private`. Missing billing/other fields terminate as
   `checkout_unavailable`, without any private fill request. Once fields are
   resolved, persist `dispatching` and set the browser to `private` before fill.
   The trusted backend sends only bound card values to a fixed Playwright script
   through Kernel. It rechecks page and displayed total after filling, clicks
   once and waits for the specified merchant success marker on the same origin.
   No arbitrary code is accepted from the model. Provider error text, stdout,
   stderr and tab details are discarded. The model receives only safe status.
6. Close/delete the browser after the attempt, including failures. If deletion
   fails, `cleanup_pending` remains in encrypted browser state; retry
   `kernel_browser(action="close", browser_reference=...)`. Ordinary access
   stays denied, and the remote inactivity timeout is a fallback. Cancellation
   and recovery of an interrupted dispatch also attempt cleanup.

`checkout_submitted` plus `merchant_confirmation_observed=true` means the chosen
merchant UI marker appeared. It is not independent evidence of a bank charge;
`payment_confirmed` remains false. Any indeterminate dispatch is
`outcome_unknown`, never automatically refilled or resubmitted. The fixed script
reports `not_started` if its checks fail before attempting the first fill; this
maps to `checkout_unavailable`, including a page/total change after preflight.
The attempt marker is set immediately before calling fill/select, since input
handlers may cause effects even if the call fails. Exceptions after that marker,
or a lost Kernel response with no reliable outcome, remain `outcome_unknown`.
A page/session that disappears before dispatch also yields
`checkout_unavailable`. Keep any issued
card; do not purchase another to repair the browser flow.

The 48-hour operation authorization does not keep a cloud browser alive for
48 hours. Delayed international issuance may outlive its five-minute inactive
session. Recreate the checkout and prepare a new exact plan with the **existing**
card reference if the old session expires. There is no background keepalive bill.
3-D Secure, CAPTCHA, redirects to a new payment origin, multi-step payment forms
and non-USD checkout are not automatically handled by this first consumer.

### Cloud trust boundary

Kernel is a trusted processor here: it receives the private fill request and
runs the browser containing real PAN/CVV. The merchant's JavaScript can access
its payment fields, and Kernel/account administrators or other unrestricted CDP
clients may be able to inspect the VM. Disabling telemetry and closing a session
does not establish deletion from all provider logs/backups. Secrets stay out of
our model-facing tools, not out of Kernel. The exact displayed total is checked;
it is not a bank-enforced limit on what a malicious merchant can charge.

Kernel's credential item specification explicitly prohibits credit-card data in
ordinary credential items. This implementation therefore does **not** upload
cards to Kernel credential vaults or integrate AgentCard. See the official
[Python SDK](https://github.com/kernel/kernel-python-sdk),
[Playwright API](https://www.kernel.sh/docs/api-reference/browser-playwright/execute-playwrighttypescript-code-against-the-browser)
and [credential guidance](https://www.kernel.sh/docs/vaults/credentials).

### Failed Laso responses

Only HTTP 200 order responses become saved cards. Quotes and explicit non-200
responses discard their provisional record and retain the original x402 status
and response, so issuer validation/rate-limit errors do not become catalog cards.
Combined issuance/use refuses to prepare an operation from a failed issuer response.
Transport exceptions still preserve an encrypted receipt for outcome review.
