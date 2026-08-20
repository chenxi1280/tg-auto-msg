-- Normalize absent task buttons before V2 media adoption.
-- SQLAlchemy's default JSON type persisted Python None as JSON null, while the
-- V2 contract originally required SQL NULL. Both represent no buttons.
-- @statement
UPDATE scheduled_message_tasks
SET buttons = NULL
WHERE buttons IS NOT NULL
  AND buttons::text = 'null'
-- @statement
ALTER TABLE scheduled_message_tasks
    DROP CONSTRAINT IF EXISTS scheduled_task_media_v2_check
-- @statement
ALTER TABLE scheduled_message_tasks
    ADD CONSTRAINT scheduled_task_media_v2_check
    CHECK (
        content_contract_version <> 2 OR (
            media_type IN ('none', 'photo', 'video', 'animation')
            AND (buttons IS NULL OR buttons::text = 'null')
            AND (
                (
                    media_type = 'none'
                    AND media_source_account_id IS NULL
                    AND media_source_message_id IS NULL
                    AND media_source_state = 'none'
                )
                OR (
                    media_type <> 'none'
                    AND media_source_account_id IS NOT NULL
                    AND media_source_message_id IS NOT NULL
                    AND media_source_account_id = account_id
                    AND media_source_state IN ('valid', 'migration_pending', 'invalid')
                )
            )
            AND (media_source_state <> 'valid' OR media_source_verified_at IS NOT NULL)
        )
    )
