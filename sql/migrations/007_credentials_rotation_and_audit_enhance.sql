-- Credential rotation + audit enhancement migration.

-- @statement
ALTER TABLE IF EXISTS telegram_developer_apps
ADD COLUMN IF NOT EXISTS credentials_version INTEGER DEFAULT 1 NOT NULL;

-- @statement
ALTER TABLE IF EXISTS telegram_developer_apps
ADD COLUMN IF NOT EXISTS last_rotated_at TIMESTAMP;

-- @statement
ALTER TABLE IF EXISTS accounts
ADD COLUMN IF NOT EXISTS developer_app_version INTEGER DEFAULT 1 NOT NULL;

-- @statement
ALTER TABLE IF EXISTS accounts
ADD COLUMN IF NOT EXISTS reauth_required BOOLEAN DEFAULT FALSE NOT NULL;

-- @statement
ALTER TABLE IF EXISTS accounts
ADD COLUMN IF NOT EXISTS reauth_reason VARCHAR(64);

-- @statement
ALTER TABLE IF EXISTS accounts
ADD COLUMN IF NOT EXISTS reauth_required_at TIMESTAMP;

-- @statement
UPDATE accounts AS a
SET developer_app_version = COALESCE(t.credentials_version, 1)
FROM telegram_developer_apps AS t
WHERE a.developer_app_id = t.id
  AND COALESCE(a.developer_app_version, 0) <= 0;

-- @statement
UPDATE accounts
SET developer_app_version = 1
WHERE COALESCE(developer_app_version, 0) <= 0;

-- @statement
CREATE INDEX IF NOT EXISTS idx_accounts_reauth_required
ON accounts(reauth_required);

-- @statement
ALTER TABLE IF EXISTS admin_audit_logs
ADD COLUMN IF NOT EXISTS developer_app_id INTEGER;

-- @statement
ALTER TABLE IF EXISTS admin_audit_logs
ADD COLUMN IF NOT EXISTS old_value JSONB;

-- @statement
ALTER TABLE IF EXISTS admin_audit_logs
ADD COLUMN IF NOT EXISTS new_value JSONB;

-- @statement
DO $$
BEGIN
    IF to_regclass('admin_audit_logs') IS NOT NULL THEN
        IF EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'admin_audit_logs_developer_app_id_fkey'
        ) THEN
            ALTER TABLE admin_audit_logs
            DROP CONSTRAINT admin_audit_logs_developer_app_id_fkey;
        END IF;

        ALTER TABLE admin_audit_logs
        ADD CONSTRAINT admin_audit_logs_developer_app_id_fkey
        FOREIGN KEY (developer_app_id)
        REFERENCES telegram_developer_apps(id)
        ON DELETE SET NULL;
    END IF;
END
$$;

-- @statement
CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_developer_app_id
ON admin_audit_logs(developer_app_id);
