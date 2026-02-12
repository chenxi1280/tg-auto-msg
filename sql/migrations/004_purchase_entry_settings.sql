-- Purchase entry settings for paid subscription flow.

-- @statement
CREATE TABLE IF NOT EXISTS app_settings (
    key VARCHAR(64) PRIMARY KEY,
    value TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- @statement
CREATE INDEX IF NOT EXISTS idx_app_settings_updated_at
ON app_settings(updated_at);

-- @statement
INSERT INTO app_settings (key, value)
VALUES ('purchase_url', 'https://t.me/')
ON CONFLICT (key) DO NOTHING;

-- @statement
INSERT INTO app_settings (key, value)
VALUES ('purchase_button_text', '联系 Telegram 购买')
ON CONFLICT (key) DO NOTHING;

-- @statement
DROP TRIGGER IF EXISTS update_app_settings_updated_at ON app_settings;

-- @statement
CREATE TRIGGER update_app_settings_updated_at
    BEFORE UPDATE ON app_settings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
