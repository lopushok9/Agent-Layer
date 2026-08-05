BEGIN;

-- Payout bookkeeping for bound invites.
--
-- Without this, "who still needs paying" is only answerable by remembering when
-- the last payout ran: every bound row looks identical whether or not its bonus
-- has already been sent, so a repeated query pays the same address twice.
--
-- Written to re-run safely, because scripts/migrate-onboarding.mjs replays every
-- migration on each invocation and keeps no applied-migrations table.

ALTER TABLE onboarding_invites
  ADD COLUMN IF NOT EXISTS payout_status text NOT NULL DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS payout_tx_hash text,
  ADD COLUMN IF NOT EXISTS paid_at timestamptz,
  ADD COLUMN IF NOT EXISTS payout_note text;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'onboarding_invites_payout_status_check'
  ) THEN
    ALTER TABLE onboarding_invites
      ADD CONSTRAINT onboarding_invites_payout_status_check
      CHECK (payout_status IN ('pending', 'sent', 'failed', 'skipped'));
  END IF;

  -- Mirrors the existing status/base_address/bound_at rule: a row may not claim
  -- it was paid without carrying the transaction that proves it.
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'onboarding_invites_payout_consistency_check'
  ) THEN
    ALTER TABLE onboarding_invites
      ADD CONSTRAINT onboarding_invites_payout_consistency_check
      CHECK (
        (payout_status = 'sent' AND payout_tx_hash IS NOT NULL AND paid_at IS NOT NULL)
        OR
        (payout_status <> 'sent' AND paid_at IS NULL)
      );
  END IF;

END $$;

-- One payout per transaction hash, so a retry that reuses a hash cannot be
-- recorded as a second payout. Partial, because unpaid rows are all NULL.
CREATE UNIQUE INDEX IF NOT EXISTS onboarding_invites_payout_tx_unique
  ON onboarding_invites (campaign_id, lower(payout_tx_hash))
  WHERE payout_tx_hash IS NOT NULL;

-- Serves the payout queue query directly.
CREATE INDEX IF NOT EXISTS onboarding_invites_payout_queue_idx
  ON onboarding_invites (campaign_id, payout_status, bound_at)
  WHERE status = 'bound';

COMMIT;
