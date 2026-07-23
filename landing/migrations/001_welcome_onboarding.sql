BEGIN;

CREATE TABLE IF NOT EXISTS onboarding_assessments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id text NOT NULL,
  user_id text NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
  provider text NOT NULL CHECK (provider IN ('github', 'x')),
  provider_subject_id text NOT NULL,
  rules_version text NOT NULL,
  decision text NOT NULL CHECK (decision IN ('eligible', 'ineligible', 'error')),
  reason_code text,
  account_created_at timestamptz,
  signals jsonb NOT NULL DEFAULT '{}'::jsonb,
  evaluated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (campaign_id, provider, provider_subject_id)
);

CREATE TABLE IF NOT EXISTS onboarding_invites (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id text NOT NULL,
  user_id text NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
  assessment_id uuid NOT NULL UNIQUE REFERENCES onboarding_assessments(id) ON DELETE RESTRICT,
  code_hash char(64) NOT NULL UNIQUE,
  status text NOT NULL CHECK (status IN ('issued', 'bound', 'expired', 'revoked')),
  expires_at timestamptz NOT NULL,
  base_address varchar(42),
  created_at timestamptz NOT NULL DEFAULT now(),
  bound_at timestamptz,
  UNIQUE (campaign_id, user_id),
  CHECK (base_address IS NULL OR base_address ~ '^0x[0-9a-f]{40}$'),
  CHECK (
    (status = 'bound' AND base_address IS NOT NULL AND bound_at IS NOT NULL)
    OR
    (status <> 'bound' AND base_address IS NULL AND bound_at IS NULL)
  )
);

CREATE UNIQUE INDEX IF NOT EXISTS onboarding_invites_campaign_address_unique
  ON onboarding_invites (campaign_id, lower(base_address))
  WHERE base_address IS NOT NULL;

CREATE INDEX IF NOT EXISTS onboarding_invites_status_expiry_idx
  ON onboarding_invites (campaign_id, status, expires_at);

COMMIT;
