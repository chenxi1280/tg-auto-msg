-- Rollback for 007_credentials_rotation_and_audit_enhance.sql

-- @statement
DROP INDEX IF EXISTS idx_admin_audit_logs_developer_app_id;

-- @statement
DO $$
BEGIN
    IF to_regclass('admin_audit_logs') IS NOT NULL
       AND EXISTS (
           SELECT 1 FROM pg_constraint
           WHERE conname = 'admin_audit_logs_developer_app_id_fkey'
       ) THEN
        ALTER TABLE admin_audit_logs
        DROP CONSTRAINT admin_audit_logs_developer_app_id_fkey;
    END IF;
END
$$;

-- @statement
ALTER TABLE IF EXISTS admin_audit_logs
DROP COLUMN IF EXISTS new_value;

-- @statement
ALTER TABLE IF EXISTS admin_audit_logs
DROP COLUMN IF EXISTS old_value;

-- @statement
ALTER TABLE IF EXISTS admin_audit_logs
DROP COLUMN IF EXISTS developer_app_id;

-- @statement
DROP INDEX IF EXISTS idx_accounts_reauth_required;

-- @statement
ALTER TABLE IF EXISTS accounts
DROP COLUMN IF EXISTS reauth_required_at;

-- @statement
ALTER TABLE IF EXISTS accounts
DROP COLUMN IF EXISTS reauth_reason;

-- @statement
ALTER TABLE IF EXISTS accounts
DROP COLUMN IF EXISTS reauth_required;

-- @statement
ALTER TABLE IF EXISTS accounts
DROP COLUMN IF EXISTS developer_app_version;

-- @statement
ALTER TABLE IF EXISTS telegram_developer_apps
DROP COLUMN IF EXISTS last_rotated_at;

-- @statement
ALTER TABLE IF EXISTS telegram_developer_apps
DROP COLUMN IF EXISTS credentials_version;
