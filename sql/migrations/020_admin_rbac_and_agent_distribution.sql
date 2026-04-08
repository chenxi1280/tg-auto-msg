-- 后台账号 RBAC、多级代理、批次、审批与资金流水

CREATE TABLE IF NOT EXISTS admin_accounts (
    id SERIAL PRIMARY KEY,
    username VARCHAR(64) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role_code VARCHAR(32) NOT NULL,
    province_code VARCHAR(32) NOT NULL,
    parent_account_id INTEGER REFERENCES admin_accounts(id) ON DELETE SET NULL,
    root_master_account_id INTEGER REFERENCES admin_accounts(id) ON DELETE SET NULL,
    level_depth INTEGER DEFAULT 0 NOT NULL,
    status VARCHAR(20) DEFAULT 'active' NOT NULL,
    settlement_mode VARCHAR(20) DEFAULT 'prepaid' NOT NULL,
    is_credit_whitelisted BOOLEAN DEFAULT FALSE NOT NULL,
    credit_limit_cents BIGINT DEFAULT 0 NOT NULL,
    allocated_credit_limit_cents BIGINT DEFAULT 0 NOT NULL,
    credit_used_cents BIGINT DEFAULT 0 NOT NULL,
    balance_cents BIGINT DEFAULT 0 NOT NULL,
    force_password_change BOOLEAN DEFAULT FALSE NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    contact_name VARCHAR(100),
    contact_phone VARCHAR(50),
    created_by INTEGER,
    last_login_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_admin_accounts_role_status ON admin_accounts(role_code, status);
CREATE INDEX IF NOT EXISTS idx_admin_accounts_parent ON admin_accounts(parent_account_id);
CREATE INDEX IF NOT EXISTS idx_admin_accounts_root_master ON admin_accounts(root_master_account_id);
CREATE INDEX IF NOT EXISTS idx_admin_accounts_province_role ON admin_accounts(province_code, role_code);

CREATE TABLE IF NOT EXISTS admin_account_tg_bindings (
    id SERIAL PRIMARY KEY,
    admin_account_id INTEGER NOT NULL UNIQUE REFERENCES admin_accounts(id) ON DELETE CASCADE,
    tg_user_id BIGINT UNIQUE,
    tg_username VARCHAR(100),
    bind_status VARCHAR(20) DEFAULT 'unbound' NOT NULL,
    bind_code VARCHAR(32),
    bind_code_expires_at TIMESTAMP,
    bound_at TIMESTAMP,
    unbound_at TIMESTAMP,
    bound_by_account_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_admin_tg_bindings_account ON admin_account_tg_bindings(admin_account_id);
CREATE INDEX IF NOT EXISTS idx_admin_tg_bindings_tg_user ON admin_account_tg_bindings(tg_user_id);
CREATE INDEX IF NOT EXISTS idx_admin_tg_bindings_status ON admin_account_tg_bindings(bind_status);

CREATE TABLE IF NOT EXISTS agent_credit_limits (
    id SERIAL PRIMARY KEY,
    parent_account_id INTEGER NOT NULL REFERENCES admin_accounts(id) ON DELETE CASCADE,
    child_account_id INTEGER NOT NULL REFERENCES admin_accounts(id) ON DELETE CASCADE,
    delegated_credit_limit_cents BIGINT DEFAULT 0 NOT NULL,
    delegated_credit_used_cents BIGINT DEFAULT 0 NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    last_adjusted_by INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_agent_credit_limits_parent_child UNIQUE (parent_account_id, child_account_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_credit_limits_parent ON agent_credit_limits(parent_account_id);
CREATE INDEX IF NOT EXISTS idx_agent_credit_limits_child ON agent_credit_limits(child_account_id);

CREATE TABLE IF NOT EXISTS agent_plan_prices (
    id SERIAL PRIMARY KEY,
    parent_account_id INTEGER NOT NULL REFERENCES admin_accounts(id) ON DELETE CASCADE,
    child_account_id INTEGER NOT NULL REFERENCES admin_accounts(id) ON DELETE CASCADE,
    plan_code VARCHAR(32) NOT NULL REFERENCES pricing_plans(plan_code) ON DELETE CASCADE,
    settlement_price_cents BIGINT DEFAULT 0 NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_agent_plan_prices_parent_child_plan UNIQUE (parent_account_id, child_account_id, plan_code)
);

CREATE INDEX IF NOT EXISTS idx_agent_plan_prices_parent ON agent_plan_prices(parent_account_id);
CREATE INDEX IF NOT EXISTS idx_agent_plan_prices_child ON agent_plan_prices(child_account_id);

CREATE TABLE IF NOT EXISTS card_batches (
    batch_id VARCHAR(36) PRIMARY KEY,
    province_code VARCHAR(32) NOT NULL,
    creator_account_id INTEGER NOT NULL REFERENCES admin_accounts(id) ON DELETE RESTRICT,
    owner_account_id INTEGER NOT NULL REFERENCES admin_accounts(id) ON DELETE RESTRICT,
    direct_parent_account_id INTEGER REFERENCES admin_accounts(id) ON DELETE SET NULL,
    root_master_account_id INTEGER REFERENCES admin_accounts(id) ON DELETE SET NULL,
    current_liability_account_id INTEGER REFERENCES admin_accounts(id) ON DELETE SET NULL,
    current_counterparty_account_id INTEGER REFERENCES admin_accounts(id) ON DELETE SET NULL,
    plan_code VARCHAR(32) NOT NULL REFERENCES pricing_plans(plan_code) ON DELETE CASCADE,
    quantity INTEGER NOT NULL,
    duration_days INTEGER NOT NULL,
    unit_price_cents BIGINT NOT NULL,
    total_amount_cents BIGINT NOT NULL,
    settlement_status VARCHAR(20) DEFAULT 'pending' NOT NULL,
    payment_status VARCHAR(20) DEFAULT 'unpaid' NOT NULL,
    export_count INTEGER DEFAULT 0 NOT NULL,
    last_exported_at TIMESTAMP,
    remark TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_card_batches_owner ON card_batches(owner_account_id);
CREATE INDEX IF NOT EXISTS idx_card_batches_parent ON card_batches(direct_parent_account_id);
CREATE INDEX IF NOT EXISTS idx_card_batches_root_master ON card_batches(root_master_account_id);
CREATE INDEX IF NOT EXISTS idx_card_batches_liability ON card_batches(current_liability_account_id);
CREATE INDEX IF NOT EXISTS idx_card_batches_status ON card_batches(settlement_status, payment_status);
CREATE INDEX IF NOT EXISTS idx_card_batches_created_at ON card_batches(created_at);

ALTER TABLE card_batches
    ADD COLUMN IF NOT EXISTS current_liability_account_id INTEGER REFERENCES admin_accounts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS current_counterparty_account_id INTEGER REFERENCES admin_accounts(id) ON DELETE SET NULL;

UPDATE card_batches
SET
    current_liability_account_id = owner_account_id,
    current_counterparty_account_id = direct_parent_account_id
WHERE payment_status = 'credit'
  AND settlement_status <> 'settled'
  AND current_liability_account_id IS NULL;

CREATE TABLE IF NOT EXISTS agent_fund_ledgers (
    id SERIAL PRIMARY KEY,
    ledger_scope VARCHAR(20) NOT NULL,
    account_id INTEGER NOT NULL REFERENCES admin_accounts(id) ON DELETE CASCADE,
    counterparty_account_id INTEGER REFERENCES admin_accounts(id) ON DELETE SET NULL,
    biz_type VARCHAR(32) NOT NULL,
    direction VARCHAR(16) NOT NULL,
    amount_cents BIGINT NOT NULL,
    balance_after_cents BIGINT,
    credit_used_after_cents BIGINT,
    related_batch_id VARCHAR(36) REFERENCES card_batches(batch_id) ON DELETE SET NULL,
    related_request_id VARCHAR(36),
    remark TEXT,
    operator_account_id INTEGER REFERENCES admin_accounts(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_fund_ledgers_account ON agent_fund_ledgers(account_id);
CREATE INDEX IF NOT EXISTS idx_agent_fund_ledgers_scope ON agent_fund_ledgers(ledger_scope);
CREATE INDEX IF NOT EXISTS idx_agent_fund_ledgers_batch ON agent_fund_ledgers(related_batch_id);
CREATE INDEX IF NOT EXISTS idx_agent_fund_ledgers_created_at ON agent_fund_ledgers(created_at);

CREATE TABLE IF NOT EXISTS approval_requests (
    request_id VARCHAR(36) PRIMARY KEY,
    province_code VARCHAR(32) NOT NULL,
    request_type VARCHAR(32) NOT NULL,
    requester_account_id INTEGER NOT NULL REFERENCES admin_accounts(id) ON DELETE CASCADE,
    subject_account_id INTEGER NOT NULL REFERENCES admin_accounts(id) ON DELETE CASCADE,
    approver_account_id INTEGER NOT NULL REFERENCES admin_accounts(id) ON DELETE CASCADE,
    status VARCHAR(20) DEFAULT 'pending' NOT NULL,
    amount_cents BIGINT,
    credit_delta_cents BIGINT,
    payload_json JSONB,
    approved_at TIMESTAMP,
    rejected_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_approval_requests_subject ON approval_requests(subject_account_id);
CREATE INDEX IF NOT EXISTS idx_approval_requests_approver ON approval_requests(approver_account_id, status);
CREATE INDEX IF NOT EXISTS idx_approval_requests_created_at ON approval_requests(created_at);

ALTER TABLE activation_cards
    ADD COLUMN IF NOT EXISTS batch_id VARCHAR(36) REFERENCES card_batches(batch_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS creator_account_id INTEGER REFERENCES admin_accounts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS owner_account_id INTEGER REFERENCES admin_accounts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS direct_parent_account_id INTEGER REFERENCES admin_accounts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS root_master_account_id INTEGER REFERENCES admin_accounts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS settlement_unit_price_cents BIGINT,
    ADD COLUMN IF NOT EXISTS card_source_type VARCHAR(20) DEFAULT 'platform' NOT NULL,
    ADD COLUMN IF NOT EXISTS copy_status VARCHAR(20) DEFAULT 'new' NOT NULL;

CREATE INDEX IF NOT EXISTS idx_activation_cards_batch_id ON activation_cards(batch_id);
CREATE INDEX IF NOT EXISTS idx_activation_cards_owner_account_id ON activation_cards(owner_account_id);
