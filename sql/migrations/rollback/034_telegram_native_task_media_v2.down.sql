-- @statement
DROP TABLE IF EXISTS task_media_capture_sessions
-- @statement
ALTER TABLE scheduled_message_tasks DROP CONSTRAINT IF EXISTS fk_task_media_source_account
-- @statement
ALTER TABLE scheduled_message_tasks DROP CONSTRAINT IF EXISTS scheduled_task_media_v2_check
-- @statement
ALTER TABLE scheduled_message_tasks DROP CONSTRAINT IF EXISTS scheduled_task_media_source_state_check
-- @statement
ALTER TABLE scheduled_message_tasks DROP CONSTRAINT IF EXISTS scheduled_task_content_contract_check
-- @statement
ALTER TABLE scheduled_message_tasks
    DROP COLUMN IF EXISTS media_source_verified_at,
    DROP COLUMN IF EXISTS media_source_error_code,
    DROP COLUMN IF EXISTS media_source_state,
    DROP COLUMN IF EXISTS media_source_meta,
    DROP COLUMN IF EXISTS media_source_message_id,
    DROP COLUMN IF EXISTS media_source_account_id,
    DROP COLUMN IF EXISTS revision,
    DROP COLUMN IF EXISTS content_contract_version
