-- Passkey (WebAuthn) sign-in. A passkey is one more identity of a user, like a
-- Google or GitHub account; wallets stay keyed by user and are unchanged.
CREATE TABLE IF NOT EXISTS passkey_credentials (
  credential_id text PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  public_key bytea NOT NULL,
  counter bigint NOT NULL DEFAULT 0,
  transports text[] NOT NULL DEFAULT '{}',
  device_type text NOT NULL CHECK(device_type IN ('singleDevice','multiDevice')),
  backed_up boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz
);
CREATE INDEX IF NOT EXISTS passkey_credentials_user ON passkey_credentials(user_id);
-- One-time ceremony challenges, bound to the login request or pending consent
-- they were issued for.
CREATE TABLE IF NOT EXISTS passkey_challenges (
  id uuid PRIMARY KEY,
  purpose text NOT NULL CHECK(purpose IN ('login','register','add')),
  challenge text NOT NULL,
  login_state uuid,
  consent_token_hash text,
  expires_at timestamptz NOT NULL
);
