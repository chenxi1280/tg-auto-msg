CREATE TABLE IF NOT EXISTS user_license_slots (
    slot_id VARCHAR(36) PRIMARY KEY,
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

CREATE INDEX IF NOT EXISTS idx_user_license_slots_user_status ON user_license_slots(user_id, status);
CREATE INDEX IF NOT EXISTS idx_user_license_slots_account ON user_license_slots(current_account_id);
CREATE INDEX IF NOT EXISTS idx_user_license_slots_end_at ON user_license_slots(end_at);

CREATE TABLE IF NOT EXISTS user_license_slot_cards (
    id SERIAL PRIMARY KEY,
    slot_id VARCHAR(36) NOT NULL REFERENCES user_license_slots(slot_id) ON DELETE CASCADE,
    activation_card_id INTEGER NOT NULL REFERENCES activation_cards(id) ON DELETE CASCADE,
    duration_days INTEGER NOT NULL,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_user_license_slot_cards_activation_card_id UNIQUE (activation_card_id)
);

CREATE INDEX IF NOT EXISTS idx_user_license_slot_cards_slot_id ON user_license_slot_cards(slot_id);

CREATE TABLE IF NOT EXISTS user_license_slot_bindings (
    id SERIAL PRIMARY KEY,
    slot_id VARCHAR(36) NOT NULL REFERENCES user_license_slots(slot_id) ON DELETE CASCADE,
    account_id VARCHAR(36) NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    bind_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    unbind_at TIMESTAMP,
    unbind_reason VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_user_license_slot_bindings_slot_id ON user_license_slot_bindings(slot_id);
CREATE INDEX IF NOT EXISTS idx_user_license_slot_bindings_account_id ON user_license_slot_bindings(account_id);

CREATE TABLE IF NOT EXISTS slot_notice_logs (
    id SERIAL PRIMARY KEY,
    slot_id VARCHAR(36) NOT NULL REFERENCES user_license_slots(slot_id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    days_before INTEGER NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_slot_notice_once UNIQUE (slot_id, days_before)
);

CREATE INDEX IF NOT EXISTS idx_slot_notice_user_id ON slot_notice_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_slot_notice_sent_at ON slot_notice_logs(sent_at);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'user_license_slots_current_account_id_fkey'
    ) THEN
        ALTER TABLE user_license_slots
        ADD CONSTRAINT user_license_slots_current_account_id_fkey
        FOREIGN KEY (current_account_id)
        REFERENCES accounts(account_id)
        ON DELETE SET NULL;
    END IF;
END
$$;
