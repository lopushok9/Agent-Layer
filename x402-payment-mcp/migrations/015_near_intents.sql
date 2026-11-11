-- NEAR Intents (1Click) swaps are NEAR transactions with their own kind, so
-- only intents_swap_execute (which checks the quote deadline and submits the
-- deposit) can execute them.
ALTER TABLE near_operations DROP CONSTRAINT IF EXISTS near_operations_kind_check;
ALTER TABLE near_operations ADD CONSTRAINT near_operations_kind_check CHECK (kind IN ('near_tx','chain_signature','intents_swap'));
