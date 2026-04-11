DROP INDEX IF EXISTS uq_task_user_shortcut_slot;
DROP INDEX IF EXISTS idx_task_user_trigger_shortcut;

ALTER TABLE scheduled_message_tasks
    DROP CONSTRAINT IF EXISTS scheduled_message_tasks_trigger_mode_check,
    DROP CONSTRAINT IF EXISTS scheduled_message_tasks_shortcut_slot_check,
    DROP COLUMN IF EXISTS trigger_mode,
    DROP COLUMN IF EXISTS shortcut_slot,
    DROP COLUMN IF EXISTS shortcut_label;

ALTER TABLE task_logs
    DROP CONSTRAINT IF EXISTS task_logs_trigger_source_check,
    DROP COLUMN IF EXISTS trigger_source;
