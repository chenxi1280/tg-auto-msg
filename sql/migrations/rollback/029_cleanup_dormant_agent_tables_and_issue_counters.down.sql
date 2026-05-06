-- @statement
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

-- @statement
CREATE INDEX IF NOT EXISTS idx_agent_plan_prices_parent ON agent_plan_prices(parent_account_id);

-- @statement
CREATE INDEX IF NOT EXISTS idx_agent_plan_prices_child ON agent_plan_prices(child_account_id);

-- @statement
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

-- @statement
CREATE INDEX IF NOT EXISTS idx_approval_requests_subject ON approval_requests(subject_account_id);

-- @statement
CREATE INDEX IF NOT EXISTS idx_approval_requests_approver ON approval_requests(approver_account_id, status);

-- @statement
CREATE INDEX IF NOT EXISTS idx_approval_requests_created_at ON approval_requests(created_at);

-- @statement
ALTER TABLE task_target_send_issues
    DROP COLUMN IF EXISTS consecutive_failures;
