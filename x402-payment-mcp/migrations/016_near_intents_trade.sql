-- Solver Relay trades: a NEP-413 token_diff intent signed by the NEAR account
-- and settled on intents.near; tx_hash holds the intent hash, nonce the intent nonce.
ALTER TABLE near_operations DROP CONSTRAINT IF EXISTS near_operations_kind_check;
ALTER TABLE near_operations ADD CONSTRAINT near_operations_kind_check CHECK (kind IN ('near_tx','chain_signature','intents_swap','intents_trade'));
