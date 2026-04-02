-- @statement
ALTER TABLE pricing_plans
ADD COLUMN IF NOT EXISTS max_tg_accounts INTEGER DEFAULT 0 NOT NULL;

-- @statement
UPDATE pricing_plans
SET max_tg_accounts = 0
WHERE max_tg_accounts IS NULL;

-- @statement
ALTER TABLE users
ADD COLUMN IF NOT EXISTS max_tg_accounts_override INTEGER;
