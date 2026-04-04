CREATE TABLE IF NOT EXISTS user_authorizations (
    authorization_id VARCHAR(36) PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    current_account_id VARCHAR(36),
    source_card_id INTEGER REFERENCES activation_cards(id) ON DELETE SET NULL,
    total_duration_days INTEGER DEFAULT 0 NOT NULL,
    start_at TIMESTAMP NOT NULL,
    end_at TIMESTAMP NOT NULL,
    status VARCHAR(20) DEFAULT 'active' NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_authorizations_user_status ON user_authorizations(user_id, status);
CREATE INDEX IF NOT EXISTS idx_user_authorizations_account ON user_authorizations(current_account_id);
CREATE INDEX IF NOT EXISTS idx_user_authorizations_end_at ON user_authorizations(end_at);

CREATE TABLE IF NOT EXISTS user_authorization_cards (
    id SERIAL PRIMARY KEY,
    authorization_id VARCHAR(36) NOT NULL REFERENCES user_authorizations(authorization_id) ON DELETE CASCADE,
    activation_card_id INTEGER NOT NULL REFERENCES activation_cards(id) ON DELETE CASCADE,
    duration_days INTEGER NOT NULL,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_user_authorization_cards_activation_card_id UNIQUE (activation_card_id)
);

CREATE INDEX IF NOT EXISTS idx_user_authorization_cards_authorization_id ON user_authorization_cards(authorization_id);

CREATE TABLE IF NOT EXISTS user_authorization_bindings (
    id SERIAL PRIMARY KEY,
    authorization_id VARCHAR(36) NOT NULL REFERENCES user_authorizations(authorization_id) ON DELETE CASCADE,
    account_id VARCHAR(36) NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    bind_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    unbind_at TIMESTAMP,
    unbind_reason VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_user_authorization_bindings_authorization_id ON user_authorization_bindings(authorization_id);
CREATE INDEX IF NOT EXISTS idx_user_authorization_bindings_account_id ON user_authorization_bindings(account_id);

CREATE TABLE IF NOT EXISTS authorization_notice_logs (
    id SERIAL PRIMARY KEY,
    authorization_id VARCHAR(36) NOT NULL REFERENCES user_authorizations(authorization_id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    days_before INTEGER NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_authorization_notice_once UNIQUE (authorization_id, days_before)
);

CREATE INDEX IF NOT EXISTS idx_authorization_notice_user_id ON authorization_notice_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_authorization_notice_sent_at ON authorization_notice_logs(sent_at);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'user_authorizations_current_account_id_fkey'
    ) THEN
        ALTER TABLE user_authorizations
        ADD CONSTRAINT user_authorizations_current_account_id_fkey
        FOREIGN KEY (current_account_id)
        REFERENCES accounts(account_id)
        ON DELETE SET NULL;
    END IF;
END
$$;
