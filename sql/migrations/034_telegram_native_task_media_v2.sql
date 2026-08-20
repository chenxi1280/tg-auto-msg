-- Telegram-native task media V2. Existing tasks remain V1 until explicitly migrated.
-- @statement
ALTER TABLE scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS content_contract_version INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS revision BIGINT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS media_source_account_id VARCHAR(36),
    ADD COLUMN IF NOT EXISTS media_source_message_id BIGINT,
    ADD COLUMN IF NOT EXISTS media_source_meta JSONB,
    ADD COLUMN IF NOT EXISTS media_source_state VARCHAR(24) NOT NULL DEFAULT 'none',
    ADD COLUMN IF NOT EXISTS media_source_error_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS media_source_verified_at TIMESTAMP
-- @statement
ALTER TABLE scheduled_message_tasks
    ALTER COLUMN content_contract_version SET DEFAULT 2,
    ALTER COLUMN revision SET DEFAULT 1,
    ALTER COLUMN media_source_state SET DEFAULT 'none'
-- @statement
ALTER TABLE scheduled_message_tasks
    ADD CONSTRAINT scheduled_task_content_contract_check
    CHECK (content_contract_version IN (1, 2))
-- @statement
ALTER TABLE scheduled_message_tasks
    ADD CONSTRAINT scheduled_task_media_source_state_check
    CHECK (media_source_state IN ('none', 'valid', 'migration_pending', 'invalid'))
-- @statement
ALTER TABLE scheduled_message_tasks
    ADD CONSTRAINT scheduled_task_media_v2_check
    CHECK (
        content_contract_version <> 2 OR (
            media_type IN ('none', 'photo', 'video', 'animation')
            AND buttons IS NULL
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
-- @statement
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = to_regclass('scheduled_message_tasks')
          AND contype = 'f'
          AND pg_get_constraintdef(oid) LIKE 'FOREIGN KEY (media_source_account_id)%'
    ) THEN
        ALTER TABLE scheduled_message_tasks
        ADD CONSTRAINT fk_task_media_source_account
        FOREIGN KEY (media_source_account_id)
        REFERENCES accounts(account_id) ON DELETE SET NULL;
    END IF;
END
$$
-- @statement
CREATE TABLE IF NOT EXISTS task_media_capture_sessions (
    capture_id VARCHAR(36) PRIMARY KEY,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    task_id VARCHAR(36) NOT NULL REFERENCES scheduled_message_tasks(task_id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id VARCHAR(36) NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    actor_tg_user_id BIGINT NOT NULL,
    expected_task_revision BIGINT NOT NULL,
    prompt_message_id BIGINT,
    source_message_id BIGINT,
    saved_message_id BIGINT,
    state VARCHAR(20) NOT NULL DEFAULT 'waiting',
    error_code VARCHAR(64),
    expires_at TIMESTAMP NOT NULL,
    consumed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT task_media_capture_state_check
        CHECK (state IN ('waiting', 'processing', 'completed', 'expired', 'cancelled', 'failed'))
)
-- @statement
ALTER TABLE task_media_capture_sessions
    ALTER COLUMN state SET DEFAULT 'waiting'
-- @statement
CREATE UNIQUE INDEX IF NOT EXISTS uq_task_media_capture_active
ON task_media_capture_sessions(task_id)
WHERE state IN ('waiting', 'processing')
-- @statement
CREATE INDEX IF NOT EXISTS idx_task_media_capture_task_state
ON task_media_capture_sessions(task_id, state)
-- @statement
CREATE INDEX IF NOT EXISTS idx_task_media_capture_actor_prompt
ON task_media_capture_sessions(actor_tg_user_id, prompt_message_id)
-- @statement
CREATE INDEX IF NOT EXISTS idx_task_media_capture_expires
ON task_media_capture_sessions(expires_at)
