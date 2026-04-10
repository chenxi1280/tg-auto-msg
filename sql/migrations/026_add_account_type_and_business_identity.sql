ALTER TABLE admin_accounts
    ADD COLUMN IF NOT EXISTS account_type VARCHAR(20) DEFAULT 'staff',
    ADD COLUMN IF NOT EXISTS business_identity VARCHAR(32);

UPDATE admin_accounts
SET account_type = CASE
        WHEN role_code IN ('master_agent', 'sub_agent') THEN 'agent'
        ELSE 'staff'
    END,
    business_identity = CASE
        WHEN role_code = 'master_agent' THEN 'master_agent'
        WHEN role_code = 'sub_agent' THEN 'sub_agent'
        ELSE NULL
    END
WHERE account_type IS NULL
   OR business_identity IS NULL;

ALTER TABLE admin_accounts
    ALTER COLUMN account_type SET NOT NULL,
    ALTER COLUMN account_type SET DEFAULT 'staff';

CREATE INDEX IF NOT EXISTS idx_admin_accounts_type_status ON admin_accounts(account_type, status);
CREATE INDEX IF NOT EXISTS idx_admin_accounts_business_identity ON admin_accounts(business_identity);
