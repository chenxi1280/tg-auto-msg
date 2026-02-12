-- Multi-developer Telegram app credential pool support.

-- @statement
CREATE TABLE IF NOT EXISTS telegram_developer_apps (
    id SERIAL PRIMARY KEY,
    app_name VARCHAR(100) NOT NULL,
    api_id INTEGER NOT NULL UNIQUE,
    api_hash_encrypted TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    max_accounts INTEGER DEFAULT 0 NOT NULL,
    notes VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- @statement
CREATE INDEX IF NOT EXISTS idx_telegram_developer_apps_active
ON telegram_developer_apps(is_active);

-- @statement
ALTER TABLE IF EXISTS accounts
ADD COLUMN IF NOT EXISTS developer_app_id INTEGER;

-- @statement
ALTER TABLE IF EXISTS system_sessions
ADD COLUMN IF NOT EXISTS developer_app_id INTEGER;

-- @statement
DO $$
BEGIN
    IF to_regclass('accounts') IS NOT NULL THEN
        IF EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'accounts_developer_app_id_fkey'
        ) THEN
            ALTER TABLE accounts
            DROP CONSTRAINT accounts_developer_app_id_fkey;
        END IF;

        ALTER TABLE accounts
        ADD CONSTRAINT accounts_developer_app_id_fkey
        FOREIGN KEY (developer_app_id)
        REFERENCES telegram_developer_apps(id)
        ON DELETE SET NULL;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF to_regclass('system_sessions') IS NOT NULL THEN
        IF EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'system_sessions_developer_app_id_fkey'
        ) THEN
            ALTER TABLE system_sessions
            DROP CONSTRAINT system_sessions_developer_app_id_fkey;
        END IF;

        ALTER TABLE system_sessions
        ADD CONSTRAINT system_sessions_developer_app_id_fkey
        FOREIGN KEY (developer_app_id)
        REFERENCES telegram_developer_apps(id)
        ON DELETE SET NULL;
    END IF;
END
$$;

-- @statement
CREATE INDEX IF NOT EXISTS idx_accounts_developer_app_id
ON accounts(developer_app_id);

-- @statement
CREATE INDEX IF NOT EXISTS idx_system_sessions_developer_app_id
ON system_sessions(developer_app_id);

-- @statement
INSERT INTO app_settings (key, value)
VALUES ('default_developer_app_id', '')
ON CONFLICT (key) DO NOTHING;

-- @statement
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- @statement
DROP TRIGGER IF EXISTS update_telegram_developer_apps_updated_at ON telegram_developer_apps;

-- @statement
CREATE TRIGGER update_telegram_developer_apps_updated_at
    BEFORE UPDATE ON telegram_developer_apps
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
