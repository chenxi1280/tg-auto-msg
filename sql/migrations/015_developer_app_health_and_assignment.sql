-- Developer app health and assignment strategy support.

-- @statement
ALTER TABLE IF EXISTS telegram_developer_apps
ADD COLUMN IF NOT EXISTS selection_weight INTEGER DEFAULT 100 NOT NULL;

-- @statement
ALTER TABLE IF EXISTS telegram_developer_apps
ADD COLUMN IF NOT EXISTS health_status VARCHAR(20) DEFAULT 'healthy' NOT NULL;

-- @statement
ALTER TABLE IF EXISTS telegram_developer_apps
ADD COLUMN IF NOT EXISTS last_health_check_at TIMESTAMP;

-- @statement
ALTER TABLE IF EXISTS telegram_developer_apps
ADD COLUMN IF NOT EXISTS last_health_error TEXT;

-- @statement
ALTER TABLE IF EXISTS telegram_developer_apps
ADD COLUMN IF NOT EXISTS last_health_latency_ms INTEGER;

-- @statement
ALTER TABLE IF EXISTS telegram_developer_apps
ADD COLUMN IF NOT EXISTS health_fail_count INTEGER DEFAULT 0 NOT NULL;

-- @statement
UPDATE telegram_developer_apps
SET selection_weight = COALESCE(NULLIF(selection_weight, 0), 100)
WHERE selection_weight IS NULL OR selection_weight = 0;

-- @statement
UPDATE telegram_developer_apps
SET health_status = CASE
    WHEN is_active IS TRUE THEN 'healthy'
    ELSE 'disabled'
END
WHERE COALESCE(health_status, '') = '';

-- @statement
UPDATE telegram_developer_apps
SET health_status = 'disabled'
WHERE is_active IS FALSE;

-- @statement
CREATE INDEX IF NOT EXISTS idx_telegram_developer_apps_health_status
ON telegram_developer_apps(health_status);

-- @statement
INSERT INTO app_settings (key, value)
VALUES ('developer_app_assignment_mode', 'round_robin')
ON CONFLICT (key) DO NOTHING;

-- @statement
INSERT INTO app_settings (key, value)
VALUES ('developer_app_assignment_cursor', '')
ON CONFLICT (key) DO NOTHING;

-- @statement
INSERT INTO app_settings (key, value)
VALUES ('developer_app_alert_tg_user_ids', '')
ON CONFLICT (key) DO NOTHING;
