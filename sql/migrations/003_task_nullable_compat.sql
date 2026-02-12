-- Compatibility patch for legacy task table constraints.

-- @statement
DO $$
BEGIN
    IF to_regclass('scheduled_message_tasks') IS NOT NULL THEN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'scheduled_message_tasks'
              AND column_name = 'account_id'
        ) THEN
            ALTER TABLE scheduled_message_tasks ALTER COLUMN account_id DROP NOT NULL;
        END IF;

        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'scheduled_message_tasks'
              AND column_name = 'chat_id'
        ) THEN
            ALTER TABLE scheduled_message_tasks ALTER COLUMN chat_id DROP NOT NULL;
        END IF;

        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'scheduled_message_tasks'
              AND column_name = 'target_peer_id'
        ) THEN
            ALTER TABLE scheduled_message_tasks ALTER COLUMN target_peer_id DROP NOT NULL;
        END IF;

        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'scheduled_message_tasks'
              AND column_name = 'target_peer_type'
        ) THEN
            ALTER TABLE scheduled_message_tasks ALTER COLUMN target_peer_type DROP NOT NULL;
        END IF;

        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'scheduled_message_tasks'
              AND column_name = 'target_access_hash'
        ) THEN
            ALTER TABLE scheduled_message_tasks ALTER COLUMN target_access_hash DROP NOT NULL;
        END IF;

        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'scheduled_message_tasks'
              AND column_name = 'target_peers'
        ) THEN
            ALTER TABLE scheduled_message_tasks ALTER COLUMN target_peers DROP NOT NULL;
        END IF;
    END IF;
END
$$;
