-- Bot first-bind trial slot support.

-- @statement
ALTER TABLE IF EXISTS users
ADD COLUMN IF NOT EXISTS bot_trial_eligible_at TIMESTAMP;

-- @statement
ALTER TABLE IF EXISTS users
ADD COLUMN IF NOT EXISTS bot_trial_granted_at TIMESTAMP;

-- @statement
ALTER TABLE IF EXISTS users
ADD COLUMN IF NOT EXISTS bot_trial_slot_id VARCHAR(36);

-- @statement
ALTER TABLE IF EXISTS user_license_slots
ADD COLUMN IF NOT EXISTS grant_source VARCHAR(20) DEFAULT 'card' NOT NULL;

-- @statement
UPDATE user_license_slots
SET grant_source = 'card'
WHERE COALESCE(grant_source, '') = '';
