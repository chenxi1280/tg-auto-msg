-- Runtime schema compatibility patch
-- Apply order: lexicographic by filename
-- Statement separator: line marker '@statement'

-- @statement
CREATE TABLE IF NOT EXISTS system_sessions (
    session_key VARCHAR(64) PRIMARY KEY,
    session_encrypted TEXT NOT NULL,
    session_meta JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- @statement
CREATE INDEX IF NOT EXISTS idx_system_sessions_updated_at
ON system_sessions(updated_at);

-- @statement
ALTER TABLE IF EXISTS accounts
ADD COLUMN IF NOT EXISTS bind_code VARCHAR(6);

-- @statement
ALTER TABLE IF EXISTS accounts
ADD COLUMN IF NOT EXISTS bind_code_expires_at TIMESTAMP;

-- @statement
CREATE INDEX IF NOT EXISTS idx_accounts_bind_code
ON accounts(bind_code);

-- @statement
ALTER TABLE IF EXISTS scheduled_message_tasks
ADD COLUMN IF NOT EXISTS account_id VARCHAR(36);

-- @statement
ALTER TABLE IF EXISTS scheduled_message_tasks
ADD COLUMN IF NOT EXISTS target_peer_id BIGINT;

-- @statement
ALTER TABLE IF EXISTS scheduled_message_tasks
ADD COLUMN IF NOT EXISTS target_peer_type VARCHAR(20);

-- @statement
ALTER TABLE IF EXISTS scheduled_message_tasks
ADD COLUMN IF NOT EXISTS target_access_hash BIGINT;

-- @statement
ALTER TABLE IF EXISTS scheduled_message_tasks
ADD COLUMN IF NOT EXISTS target_peers JSON;

-- @statement
ALTER TABLE IF EXISTS scheduled_message_tasks
ADD COLUMN IF NOT EXISTS priority INTEGER DEFAULT 0;

-- @statement
ALTER TABLE IF EXISTS scheduled_message_tasks
ADD COLUMN IF NOT EXISTS delay_min_seconds INTEGER DEFAULT 0;

-- @statement
ALTER TABLE IF EXISTS scheduled_message_tasks
ADD COLUMN IF NOT EXISTS delay_max_seconds INTEGER DEFAULT 0;

-- @statement
ALTER TABLE IF EXISTS scheduled_message_tasks
ADD COLUMN IF NOT EXISTS jitter_seconds INTEGER DEFAULT 0;

-- @statement
ALTER TABLE IF EXISTS scheduled_message_tasks
ADD COLUMN IF NOT EXISTS next_run_at BIGINT;

-- @statement
ALTER TABLE IF EXISTS scheduled_message_tasks
ADD COLUMN IF NOT EXISTS media_type VARCHAR(20) DEFAULT 'none';

-- @statement
ALTER TABLE IF EXISTS scheduled_message_tasks
ADD COLUMN IF NOT EXISTS media_file_id VARCHAR(255);

-- @statement
DO $$
BEGIN
    IF to_regclass('scheduled_message_tasks') IS NOT NULL THEN
        ALTER TABLE scheduled_message_tasks
        ALTER COLUMN media_type TYPE VARCHAR(20)
        USING LOWER(media_type::text);

        ALTER TABLE scheduled_message_tasks
        ALTER COLUMN media_type SET DEFAULT 'none';
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF to_regclass('scheduled_message_tasks') IS NOT NULL THEN
        UPDATE scheduled_message_tasks
        SET media_type = 'none'
        WHERE media_type IS NULL OR TRIM(media_type) = '';

        IF EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'scheduled_message_tasks_media_type_check'
        ) THEN
            ALTER TABLE scheduled_message_tasks
            DROP CONSTRAINT scheduled_message_tasks_media_type_check;
        END IF;

        ALTER TABLE scheduled_message_tasks
        ADD CONSTRAINT scheduled_message_tasks_media_type_check
        CHECK (media_type IN ('none', 'photo', 'video', 'sticker', 'animation'));
    END IF;
END
$$;

-- @statement
CREATE INDEX IF NOT EXISTS idx_account_id
ON scheduled_message_tasks(account_id);

-- @statement
CREATE INDEX IF NOT EXISTS idx_enabled_next_run
ON scheduled_message_tasks(enabled, next_run_at);

-- @statement
DO $$
BEGIN
    IF to_regclass('account_bind_logs') IS NOT NULL THEN
        IF EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'account_bind_logs_account_id_fkey'
        ) THEN
            ALTER TABLE account_bind_logs
            DROP CONSTRAINT account_bind_logs_account_id_fkey;
        END IF;

        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'account_bind_logs_account_id_fkey'
        ) THEN
            ALTER TABLE account_bind_logs
            ADD CONSTRAINT account_bind_logs_account_id_fkey
            FOREIGN KEY (account_id)
            REFERENCES accounts(account_id)
            ON DELETE SET NULL;
        END IF;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF to_regclass('scheduled_message_tasks') IS NOT NULL THEN
        IF EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'scheduled_message_tasks_account_id_fkey'
        ) THEN
            ALTER TABLE scheduled_message_tasks
            DROP CONSTRAINT scheduled_message_tasks_account_id_fkey;
        END IF;

        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'scheduled_message_tasks_account_id_fkey'
        ) THEN
            ALTER TABLE scheduled_message_tasks
            ADD CONSTRAINT scheduled_message_tasks_account_id_fkey
            FOREIGN KEY (account_id)
            REFERENCES accounts(account_id)
            ON DELETE CASCADE;
        END IF;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF to_regclass('proxies') IS NOT NULL THEN
        IF EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'proxies_assigned_account_id_fkey'
        ) THEN
            ALTER TABLE proxies
            DROP CONSTRAINT proxies_assigned_account_id_fkey;
        END IF;

        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'proxies_assigned_account_id_fkey'
        ) THEN
            ALTER TABLE proxies
            ADD CONSTRAINT proxies_assigned_account_id_fkey
            FOREIGN KEY (assigned_account_id)
            REFERENCES accounts(account_id)
            ON DELETE SET NULL;
        END IF;
    END IF;
END
$$;
