CREATE TABLE IF NOT EXISTS task_target_send_issues (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(36) NOT NULL REFERENCES scheduled_message_tasks(task_id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id VARCHAR(36) REFERENCES accounts(account_id) ON DELETE SET NULL,
    peer_id BIGINT NOT NULL,
    peer_type VARCHAR(20) NOT NULL,
    peer_title VARCHAR(255),
    current_error_type VARCHAR(100) NOT NULL,
    current_error_message TEXT,
    issue_category VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'active' NOT NULL,
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    last_notified_at TIMESTAMP,
    muted_until TIMESTAMP,
    auto_suspended BOOLEAN DEFAULT FALSE NOT NULL,
    resolved_at TIMESTAMP,
    recovered_notified_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_task_target_send_issues_target UNIQUE (task_id, peer_type, peer_id)
);

CREATE INDEX IF NOT EXISTS idx_task_target_send_issues_status
    ON task_target_send_issues(status, last_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_task_target_send_issues_notify
    ON task_target_send_issues(status, last_notified_at, muted_until);

CREATE INDEX IF NOT EXISTS idx_task_target_send_issues_user
    ON task_target_send_issues(user_id, status);
