-- Billing/subscription schema migration

-- @statement
CREATE TABLE IF NOT EXISTS pricing_plans (
    plan_code VARCHAR(32) PRIMARY KEY,
    display_name VARCHAR(100) NOT NULL,
    billing_cycle VARCHAR(20) NOT NULL,
    price_cents INTEGER NOT NULL,
    duration_days INTEGER NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    sort_order INTEGER DEFAULT 0 NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- @statement
CREATE INDEX IF NOT EXISTS idx_pricing_plans_is_active
ON pricing_plans(is_active, sort_order);

-- @statement
CREATE TABLE IF NOT EXISTS user_subscriptions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_code VARCHAR(32) REFERENCES pricing_plans(plan_code) ON DELETE SET NULL,
    source VARCHAR(20) DEFAULT 'card' NOT NULL,
    card_code VARCHAR(64),
    start_at TIMESTAMP NOT NULL,
    end_at TIMESTAMP NOT NULL,
    status VARCHAR(20) DEFAULT 'active' NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- @statement
CREATE INDEX IF NOT EXISTS idx_user_subscriptions_user_status
ON user_subscriptions(user_id, status);

-- @statement
CREATE INDEX IF NOT EXISTS idx_user_subscriptions_end_at
ON user_subscriptions(end_at);

-- @statement
CREATE TABLE IF NOT EXISTS activation_cards (
    id SERIAL PRIMARY KEY,
    card_code VARCHAR(64) NOT NULL UNIQUE,
    plan_code VARCHAR(32) REFERENCES pricing_plans(plan_code) ON DELETE SET NULL,
    duration_days INTEGER,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    is_used BOOLEAN DEFAULT FALSE NOT NULL,
    expires_at TIMESTAMP,
    used_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- @statement
CREATE INDEX IF NOT EXISTS idx_activation_cards_is_used
ON activation_cards(is_used, is_active);

-- @statement
CREATE INDEX IF NOT EXISTS idx_activation_cards_plan_code
ON activation_cards(plan_code);

-- @statement
CREATE TABLE IF NOT EXISTS admin_audit_logs (
    id SERIAL PRIMARY KEY,
    actor VARCHAR(64) NOT NULL DEFAULT 'admin',
    action VARCHAR(100) NOT NULL,
    target_type VARCHAR(50),
    target_id VARCHAR(100),
    detail JSONB,
    ip_address VARCHAR(45),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- @statement
CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_created_at
ON admin_audit_logs(created_at);

-- @statement
CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_action
ON admin_audit_logs(action);

-- @statement
INSERT INTO pricing_plans (plan_code, display_name, billing_cycle, price_cents, duration_days, is_active, sort_order)
VALUES
    ('monthly', '月付套餐', 'monthly', 5900, 30, TRUE, 10),
    ('yearly', '年付套餐', 'yearly', 65000, 365, TRUE, 20)
ON CONFLICT (plan_code) DO UPDATE
SET
    display_name = EXCLUDED.display_name,
    billing_cycle = EXCLUDED.billing_cycle,
    price_cents = EXCLUDED.price_cents,
    duration_days = EXCLUDED.duration_days,
    is_active = EXCLUDED.is_active,
    sort_order = EXCLUDED.sort_order;

-- @statement
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- @statement
DROP TRIGGER IF EXISTS update_pricing_plans_updated_at ON pricing_plans;

-- @statement
CREATE TRIGGER update_pricing_plans_updated_at
    BEFORE UPDATE ON pricing_plans
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- @statement
DROP TRIGGER IF EXISTS update_user_subscriptions_updated_at ON user_subscriptions;

-- @statement
CREATE TRIGGER update_user_subscriptions_updated_at
    BEFORE UPDATE ON user_subscriptions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- @statement
DROP TRIGGER IF EXISTS update_activation_cards_updated_at ON activation_cards;

-- @statement
CREATE TRIGGER update_activation_cards_updated_at
    BEFORE UPDATE ON activation_cards
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
