ALTER TABLE users
    ADD COLUMN IF NOT EXISTS bot_initial_password_encrypted VARCHAR(1024);

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS bot_initial_password_viewable BOOLEAN DEFAULT FALSE NOT NULL;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS password_changed_after_bot_registration BOOLEAN DEFAULT FALSE NOT NULL;
