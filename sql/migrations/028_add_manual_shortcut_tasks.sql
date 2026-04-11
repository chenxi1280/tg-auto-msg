ALTER TABLE scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS trigger_mode VARCHAR(20) DEFAULT 'scheduled' NOT NULL,
    ADD COLUMN IF NOT EXISTS shortcut_slot SMALLINT,
    ADD COLUMN IF NOT EXISTS shortcut_label VARCHAR(20);

UPDATE scheduled_message_tasks
SET trigger_mode = 'scheduled'
WHERE trigger_mode IS NULL OR TRIM(trigger_mode) = '';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'scheduled_message_tasks_trigger_mode_check'
    ) THEN
        ALTER TABLE scheduled_message_tasks
            DROP CONSTRAINT scheduled_message_tasks_trigger_mode_check;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'scheduled_message_tasks_shortcut_slot_check'
    ) THEN
        ALTER TABLE scheduled_message_tasks
            DROP CONSTRAINT scheduled_message_tasks_shortcut_slot_check;
    END IF;

    ALTER TABLE scheduled_message_tasks
        ADD CONSTRAINT scheduled_message_tasks_trigger_mode_check
            CHECK (trigger_mode IN ('scheduled', 'manual_shortcut')),
        ADD CONSTRAINT scheduled_message_tasks_shortcut_slot_check
            CHECK (shortcut_slot IS NULL OR shortcut_slot BETWEEN 1 AND 3);
END
$$;

CREATE INDEX IF NOT EXISTS idx_task_user_trigger_shortcut
    ON scheduled_message_tasks(user_id, trigger_mode, shortcut_slot);

CREATE UNIQUE INDEX IF NOT EXISTS uq_task_user_shortcut_slot
    ON scheduled_message_tasks(user_id, shortcut_slot)
    WHERE shortcut_slot IS NOT NULL;

ALTER TABLE task_logs
    ADD COLUMN IF NOT EXISTS trigger_source VARCHAR(20) DEFAULT 'scheduler' NOT NULL;

UPDATE task_logs
SET trigger_source = 'scheduler'
WHERE trigger_source IS NULL OR TRIM(trigger_source) = '';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'task_logs_trigger_source_check'
    ) THEN
        ALTER TABLE task_logs
            DROP CONSTRAINT task_logs_trigger_source_check;
    END IF;

    ALTER TABLE task_logs
        ADD CONSTRAINT task_logs_trigger_source_check
            CHECK (trigger_source IN ('scheduler', 'bot_shortcut', 'api_manual'));
END
$$;
