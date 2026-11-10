-- NEAR Omni Account (hackathon product). Independent of smart_wallets: a new
-- identity per user and network, never funded or signed by existing wallets.
CREATE TABLE IF NOT EXISTS near_accounts (
  user_id uuid NOT NULL REFERENCES users(id),
  network text NOT NULL CHECK (network IN ('mainnet','testnet')),
  account_id text NOT NULL,
  public_key text NOT NULL,
  signer_kind text NOT NULL CHECK (signer_kind IN ('sealed_key','cdp_solana')),
  cdp_account_name text,
  -- AES-256-GCM sealed PKCS#8 key (sealed_key only); AAD binds it to user_id.
  sealed_key text,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, network),
  UNIQUE (network, account_id),
  CHECK ((signer_kind = 'sealed_key') = (sealed_key IS NOT NULL)),
  CHECK ((signer_kind = 'cdp_solana') = (cdp_account_name IS NOT NULL))
);

-- One row per previewed NEAR transaction (kind near_tx) or Chain Signatures
-- request (kind chain_signature). Preview columns are immutable; execution
-- persists nonce and transaction hash before broadcasting.
CREATE TABLE IF NOT EXISTS near_operations (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  network text NOT NULL,
  account_id text NOT NULL,
  public_key text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('near_tx','chain_signature')),
  receiver_id text NOT NULL,
  actions jsonb NOT NULL,
  descriptions jsonb NOT NULL,
  plan jsonb,
  fingerprint text NOT NULL,
  expires_at timestamptz NOT NULL,
  status text NOT NULL DEFAULT 'prepared' CHECK (status IN ('prepared','reserved','signing','submitted','confirmed','failed','unknown')),
  purpose text,
  consumed_at timestamptz,
  nonce text,
  tx_hash text,
  signed_tx text,
  outcome jsonb,
  result jsonb,
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS near_operations_user ON near_operations(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS near_operations_pending ON near_operations(user_id, network, account_id) WHERE status IN ('reserved','signing','submitted','unknown');
