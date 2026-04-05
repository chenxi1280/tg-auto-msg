-- Rename legacy slot-based schema into single-authorization naming.
-- This migration is intentionally idempotent and safe for:
-- 1) old production databases with slot_* tables/columns
-- 2) environments where new authorization_* tables were already pre-created

-- @statement
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'users'
          AND column_name = 'bot_trial_slot_id'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'users'
          AND column_name = 'bot_trial_authorization_id'
    ) THEN
        ALTER TABLE users RENAME COLUMN bot_trial_slot_id TO bot_trial_authorization_id;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'users'
          AND column_name = 'bot_trial_slot_id'
    ) AND EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'users'
          AND column_name = 'bot_trial_authorization_id'
    ) THEN
        UPDATE users
        SET bot_trial_authorization_id = bot_trial_slot_id
        WHERE bot_trial_authorization_id IS NULL
          AND bot_trial_slot_id IS NOT NULL;

        ALTER TABLE users DROP COLUMN bot_trial_slot_id;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF to_regclass('user_license_slots') IS NOT NULL AND to_regclass('user_authorizations') IS NULL THEN
        ALTER TABLE user_license_slots RENAME TO user_authorizations;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF to_regclass('user_license_slot_cards') IS NOT NULL AND to_regclass('user_authorization_cards') IS NULL THEN
        ALTER TABLE user_license_slot_cards RENAME TO user_authorization_cards;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF to_regclass('user_license_slot_bindings') IS NOT NULL AND to_regclass('user_authorization_bindings') IS NULL THEN
        ALTER TABLE user_license_slot_bindings RENAME TO user_authorization_bindings;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF to_regclass('slot_notice_logs') IS NOT NULL AND to_regclass('authorization_notice_logs') IS NULL THEN
        ALTER TABLE slot_notice_logs RENAME TO authorization_notice_logs;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'user_authorizations'
          AND column_name = 'slot_id'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'user_authorizations'
          AND column_name = 'authorization_id'
    ) THEN
        ALTER TABLE user_authorizations RENAME COLUMN slot_id TO authorization_id;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'user_authorization_cards'
          AND column_name = 'slot_id'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'user_authorization_cards'
          AND column_name = 'authorization_id'
    ) THEN
        ALTER TABLE user_authorization_cards RENAME COLUMN slot_id TO authorization_id;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'user_authorization_bindings'
          AND column_name = 'slot_id'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'user_authorization_bindings'
          AND column_name = 'authorization_id'
    ) THEN
        ALTER TABLE user_authorization_bindings RENAME COLUMN slot_id TO authorization_id;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'authorization_notice_logs'
          AND column_name = 'slot_id'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'authorization_notice_logs'
          AND column_name = 'authorization_id'
    ) THEN
        ALTER TABLE authorization_notice_logs RENAME COLUMN slot_id TO authorization_id;
    END IF;
END
$$;

-- @statement
ALTER TABLE IF EXISTS user_authorizations
ADD COLUMN IF NOT EXISTS grant_source VARCHAR(20) DEFAULT 'card' NOT NULL;

-- @statement
UPDATE user_authorizations
SET grant_source = 'card'
WHERE COALESCE(grant_source, '') = '';

-- @statement
DO $$
BEGIN
    IF to_regclass('user_license_slots') IS NOT NULL AND to_regclass('user_authorizations') IS NOT NULL THEN
        INSERT INTO user_authorizations (
            authorization_id,
            user_id,
            current_account_id,
            source_card_id,
            grant_source,
            total_duration_days,
            start_at,
            end_at,
            status,
            created_at,
            updated_at
        )
        SELECT
            slot_id,
            user_id,
            current_account_id,
            source_card_id,
            COALESCE(NULLIF(grant_source, ''), 'card'),
            total_duration_days,
            start_at,
            end_at,
            status,
            created_at,
            updated_at
        FROM user_license_slots
        ON CONFLICT (authorization_id) DO NOTHING;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF to_regclass('user_license_slot_cards') IS NOT NULL AND to_regclass('user_authorization_cards') IS NOT NULL THEN
        INSERT INTO user_authorization_cards (
            authorization_id,
            activation_card_id,
            duration_days,
            applied_at
        )
        SELECT
            slot_id,
            activation_card_id,
            duration_days,
            applied_at
        FROM user_license_slot_cards
        ON CONFLICT (activation_card_id) DO NOTHING;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF to_regclass('user_license_slot_bindings') IS NOT NULL AND to_regclass('user_authorization_bindings') IS NOT NULL THEN
        INSERT INTO user_authorization_bindings (
            authorization_id,
            account_id,
            bind_at,
            unbind_at,
            unbind_reason
        )
        SELECT
            old.slot_id,
            old.account_id,
            old.bind_at,
            old.unbind_at,
            old.unbind_reason
        FROM user_license_slot_bindings old
        WHERE NOT EXISTS (
            SELECT 1
            FROM user_authorization_bindings cur
            WHERE cur.authorization_id = old.slot_id
              AND cur.account_id = old.account_id
              AND cur.bind_at = old.bind_at
        );
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF to_regclass('slot_notice_logs') IS NOT NULL AND to_regclass('authorization_notice_logs') IS NOT NULL THEN
        INSERT INTO authorization_notice_logs (
            authorization_id,
            user_id,
            days_before,
            sent_at
        )
        SELECT
            slot_id,
            user_id,
            days_before,
            sent_at
        FROM slot_notice_logs
        ON CONFLICT (authorization_id, days_before) DO NOTHING;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relkind = 'i' AND relname = 'idx_user_license_slots_user_status'
    ) AND NOT EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relkind = 'i' AND relname = 'idx_user_authorizations_user_status'
    ) THEN
        ALTER INDEX idx_user_license_slots_user_status RENAME TO idx_user_authorizations_user_status;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relkind = 'i' AND relname = 'idx_user_license_slots_account'
    ) AND NOT EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relkind = 'i' AND relname = 'idx_user_authorizations_account'
    ) THEN
        ALTER INDEX idx_user_license_slots_account RENAME TO idx_user_authorizations_account;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relkind = 'i' AND relname = 'idx_user_license_slots_end_at'
    ) AND NOT EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relkind = 'i' AND relname = 'idx_user_authorizations_end_at'
    ) THEN
        ALTER INDEX idx_user_license_slots_end_at RENAME TO idx_user_authorizations_end_at;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relkind = 'i' AND relname = 'idx_user_license_slot_cards_slot_id'
    ) AND NOT EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relkind = 'i' AND relname = 'idx_user_authorization_cards_authorization_id'
    ) THEN
        ALTER INDEX idx_user_license_slot_cards_slot_id RENAME TO idx_user_authorization_cards_authorization_id;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relkind = 'i' AND relname = 'idx_user_license_slot_bindings_slot_id'
    ) AND NOT EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relkind = 'i' AND relname = 'idx_user_authorization_bindings_authorization_id'
    ) THEN
        ALTER INDEX idx_user_license_slot_bindings_slot_id RENAME TO idx_user_authorization_bindings_authorization_id;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relkind = 'i' AND relname = 'idx_user_license_slot_bindings_account_id'
    ) AND NOT EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relkind = 'i' AND relname = 'idx_user_authorization_bindings_account_id'
    ) THEN
        ALTER INDEX idx_user_license_slot_bindings_account_id RENAME TO idx_user_authorization_bindings_account_id;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relkind = 'i' AND relname = 'idx_slot_notice_user_id'
    ) AND NOT EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relkind = 'i' AND relname = 'idx_authorization_notice_user_id'
    ) THEN
        ALTER INDEX idx_slot_notice_user_id RENAME TO idx_authorization_notice_user_id;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relkind = 'i' AND relname = 'idx_slot_notice_sent_at'
    ) AND NOT EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relkind = 'i' AND relname = 'idx_authorization_notice_sent_at'
    ) THEN
        ALTER INDEX idx_slot_notice_sent_at RENAME TO idx_authorization_notice_sent_at;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_user_license_slot_cards_activation_card_id'
    ) AND NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_user_authorization_cards_activation_card_id'
    ) THEN
        ALTER TABLE user_authorization_cards
        RENAME CONSTRAINT uq_user_license_slot_cards_activation_card_id TO uq_user_authorization_cards_activation_card_id;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_slot_notice_once'
    ) AND NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_authorization_notice_once'
    ) THEN
        ALTER TABLE authorization_notice_logs
        RENAME CONSTRAINT uq_slot_notice_once TO uq_authorization_notice_once;
    END IF;
END
$$;

-- @statement
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'user_license_slots_current_account_id_fkey'
    ) AND NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'user_authorizations_current_account_id_fkey'
    ) THEN
        ALTER TABLE user_authorizations
        RENAME CONSTRAINT user_license_slots_current_account_id_fkey TO user_authorizations_current_account_id_fkey;
    END IF;
END
$$;

-- @statement
DROP TABLE IF EXISTS user_license_slot_bindings;

-- @statement
DROP TABLE IF EXISTS user_license_slot_cards;

-- @statement
DROP TABLE IF EXISTS slot_notice_logs;

-- @statement
DROP TABLE IF EXISTS user_license_slots;
