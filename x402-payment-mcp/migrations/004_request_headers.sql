ALTER TABLE payment_previews ADD COLUMN IF NOT EXISTS request_headers jsonb;
ALTER TABLE payment_previews ADD COLUMN IF NOT EXISTS request_text_body text;
