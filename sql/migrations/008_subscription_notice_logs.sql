-- @statement
CREATE TABLE IF NOT EXISTS subscription_notice_logs (
    id SERIAL PRIMARY KEY,
    subscription_id INTEGER NOT NULL REFERENCES user_subscriptions(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    days_before INTEGER NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_subscription_notice_once UNIQUE (subscription_id, days_before)
);

-- @statement
CREATE INDEX IF NOT EXISTS idx_subscription_notice_user_id
ON subscription_notice_logs(user_id);

-- @statement
CREATE INDEX IF NOT EXISTS idx_subscription_notice_sent_at
ON subscription_notice_logs(sent_at);
