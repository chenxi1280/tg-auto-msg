-- Telegram 定时消息推送管理系统 - 基线 Schema（幂等）
-- 用途：生产/开发环境的完整建表脚本（不创建数据库）

-- ========================================
-- 1) 系统用户
-- ========================================
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    bot_initial_password_encrypted VARCHAR(1024),
    bot_initial_password_viewable BOOLEAN DEFAULT FALSE NOT NULL,
    password_changed_after_bot_registration BOOLEAN DEFAULT FALSE NOT NULL,
    bot_trial_eligible_at TIMESTAMP,
    bot_trial_granted_at TIMESTAMP,
    bot_trial_authorization_id VARCHAR(36),
    email VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_ci_not_null
ON users ((LOWER(email)))
WHERE email IS NOT NULL;

-- ========================================
-- 2) 卡密规格配置
-- ========================================
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

CREATE INDEX IF NOT EXISTS idx_pricing_plans_is_active ON pricing_plans(is_active, sort_order);

-- 默认收费信息（统一为 100 元 / 月）
INSERT INTO pricing_plans (
    plan_code,
    display_name,
    billing_cycle,
    price_cents,
    duration_days,
    is_active,
    sort_order
)
VALUES
    ('monthly', '月付卡密', 'monthly', 10000, 30, TRUE, 10)
ON CONFLICT (plan_code) DO UPDATE
SET
    display_name = EXCLUDED.display_name,
    billing_cycle = EXCLUDED.billing_cycle,
    price_cents = EXCLUDED.price_cents,
    duration_days = EXCLUDED.duration_days,
    is_active = EXCLUDED.is_active,
    sort_order = EXCLUDED.sort_order;

UPDATE pricing_plans
SET is_active = FALSE
WHERE plan_code <> 'monthly';

-- ========================================
-- 3) 激活卡密
-- ========================================
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

CREATE INDEX IF NOT EXISTS idx_activation_cards_is_used ON activation_cards(is_used, is_active);
CREATE INDEX IF NOT EXISTS idx_activation_cards_plan_code ON activation_cards(plan_code);

-- ========================================
-- 4) 当前授权与账号绑定
-- ========================================
CREATE TABLE IF NOT EXISTS user_authorizations (
    authorization_id VARCHAR(36) PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    current_account_id VARCHAR(36),
    source_card_id INTEGER REFERENCES activation_cards(id) ON DELETE SET NULL,
    grant_source VARCHAR(20) DEFAULT 'card' NOT NULL,
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
    account_id VARCHAR(36) NOT NULL,
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

-- ========================================
-- 5) 管理员审计日志
-- ========================================
CREATE TABLE IF NOT EXISTS admin_audit_logs (
    id SERIAL PRIMARY KEY,
    actor VARCHAR(64) NOT NULL DEFAULT 'admin',
    action VARCHAR(100) NOT NULL,
    target_type VARCHAR(50),
    target_id VARCHAR(100),
    developer_app_id INTEGER,
    old_value JSONB,
    new_value JSONB,
    detail JSONB,
    ip_address VARCHAR(45),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_created_at ON admin_audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_action ON admin_audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_developer_app_id ON admin_audit_logs(developer_app_id);

-- ========================================
-- 6) 系统配置
-- ========================================
CREATE TABLE IF NOT EXISTS app_settings (
    key VARCHAR(64) PRIMARY KEY,
    value TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_app_settings_updated_at ON app_settings(updated_at);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(64) PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL,
    applied_at TIMESTAMP,
    execution_ms INTEGER,
    statements_count INTEGER DEFAULT 0 NOT NULL,
    error_message TEXT,
    rollback_file VARCHAR(255),
    rollback_applied_at TIMESTAMP,
    rollback_status VARCHAR(20),
    rollback_error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_schema_migrations_status ON schema_migrations(status, applied_at DESC);

INSERT INTO app_settings (key, value)
VALUES ('purchase_url', 'https://t.me/')
ON CONFLICT (key) DO NOTHING;

INSERT INTO app_settings (key, value)
VALUES ('purchase_button_text', '联系 Telegram 购买')
ON CONFLICT (key) DO NOTHING;

INSERT INTO app_settings (key, value)
VALUES ('default_developer_app_id', '')
ON CONFLICT (key) DO NOTHING;

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

CREATE INDEX IF NOT EXISTS idx_card_batches_liability ON card_batches(current_liability_account_id);

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

ALTER TABLE activation_cards
    ADD COLUMN IF NOT EXISTS batch_id VARCHAR(36) REFERENCES card_batches(batch_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS creator_account_id INTEGER REFERENCES admin_accounts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS owner_account_id INTEGER REFERENCES admin_accounts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS direct_parent_account_id INTEGER REFERENCES admin_accounts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS root_master_account_id INTEGER REFERENCES admin_accounts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS settlement_unit_price_cents BIGINT,
    ADD COLUMN IF NOT EXISTS card_source_type VARCHAR(20) DEFAULT 'platform' NOT NULL,
    ADD COLUMN IF NOT EXISTS copy_status VARCHAR(20) DEFAULT 'new' NOT NULL;

-- ========================================
-- 7) Telegram 开发者应用凭证池
-- ========================================
CREATE TABLE IF NOT EXISTS telegram_developer_apps (
    id SERIAL PRIMARY KEY,
    app_name VARCHAR(100) NOT NULL,
    api_id INTEGER NOT NULL UNIQUE,
    api_hash_encrypted TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    max_accounts INTEGER DEFAULT 0 NOT NULL,
    credentials_version INTEGER DEFAULT 1 NOT NULL,
    last_rotated_at TIMESTAMP,
    notes VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_telegram_developer_apps_active ON telegram_developer_apps(is_active);

DO $$
BEGIN
    IF to_regclass('admin_audit_logs') IS NOT NULL THEN
        IF EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'admin_audit_logs_developer_app_id_fkey'
        ) THEN
            ALTER TABLE admin_audit_logs
            DROP CONSTRAINT admin_audit_logs_developer_app_id_fkey;
        END IF;

        ALTER TABLE admin_audit_logs
        ADD CONSTRAINT admin_audit_logs_developer_app_id_fkey
        FOREIGN KEY (developer_app_id)
        REFERENCES telegram_developer_apps(id)
        ON DELETE SET NULL;
    END IF;
END
$$;

-- ========================================
-- 9) 系统会话
-- ========================================
CREATE TABLE IF NOT EXISTS system_sessions (
    session_key VARCHAR(64) PRIMARY KEY,
    session_encrypted TEXT NOT NULL,
    developer_app_id INTEGER REFERENCES telegram_developer_apps(id) ON DELETE SET NULL,
    session_meta JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_system_sessions_updated_at ON system_sessions(updated_at);
CREATE INDEX IF NOT EXISTS idx_system_sessions_developer_app_id ON system_sessions(developer_app_id);

-- ========================================
-- 10) 代理池
-- ========================================
CREATE TABLE IF NOT EXISTS proxies (
    proxy_id SERIAL PRIMARY KEY,
    proxy_type VARCHAR(10) NOT NULL,
    host VARCHAR(255) NOT NULL,
    port INTEGER NOT NULL,
    username VARCHAR(100),
    password_encrypted VARCHAR(255),

    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    is_healthy BOOLEAN DEFAULT TRUE NOT NULL,
    last_check_at TIMESTAMP,
    response_time_ms INTEGER,

    usage_count INTEGER DEFAULT 0 NOT NULL,
    assigned_account_id VARCHAR(36),

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,

    CONSTRAINT unique_proxy UNIQUE (proxy_type, host, port)
);

CREATE INDEX IF NOT EXISTS idx_proxies_is_active ON proxies(is_active, is_healthy);
CREATE INDEX IF NOT EXISTS idx_proxies_assigned ON proxies(assigned_account_id);

-- ========================================
-- 11) 账号
-- ========================================
CREATE TABLE IF NOT EXISTS accounts (
    account_id VARCHAR(36) PRIMARY KEY,

    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tg_user_id BIGINT,
    username VARCHAR(50),
    first_name VARCHAR(100),
    phone VARCHAR(20),

    string_session_encrypted TEXT NOT NULL,
    developer_app_id INTEGER REFERENCES telegram_developer_apps(id) ON DELETE SET NULL,
    developer_app_version INTEGER DEFAULT 1 NOT NULL,
    bind_code VARCHAR(6),
    bind_code_expires_at TIMESTAMP,

    proxy_id INTEGER REFERENCES proxies(proxy_id),

    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    is_banned BOOLEAN DEFAULT FALSE NOT NULL,
    health_status VARCHAR(20) DEFAULT 'online' NOT NULL,

    is_flooding BOOLEAN DEFAULT FALSE NOT NULL,
    flood_until TIMESTAMP,
    reauth_required BOOLEAN DEFAULT FALSE NOT NULL,
    reauth_reason VARCHAR(64),
    reauth_required_at TIMESTAMP,

    weight INTEGER DEFAULT 100 NOT NULL,

    messages_sent INTEGER DEFAULT 0 NOT NULL,
    last_used_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,

    CONSTRAINT unique_bind_code UNIQUE (bind_code)
);

CREATE INDEX IF NOT EXISTS idx_accounts_user_id ON accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_accounts_tg_user_id ON accounts(tg_user_id);
CREATE INDEX IF NOT EXISTS idx_accounts_bind_code ON accounts(bind_code);
CREATE INDEX IF NOT EXISTS idx_accounts_health_status ON accounts(health_status);
CREATE INDEX IF NOT EXISTS idx_accounts_developer_app_id ON accounts(developer_app_id);
CREATE INDEX IF NOT EXISTS idx_accounts_reauth_required ON accounts(reauth_required);

-- ========================================
-- 11) 资源
-- ========================================
CREATE TABLE IF NOT EXISTS resources (
    resource_id SERIAL PRIMARY KEY,

    account_id VARCHAR(36) NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,

    peer_id BIGINT NOT NULL,
    peer_type VARCHAR(20) NOT NULL,
    access_hash BIGINT,

    title VARCHAR(255),
    username VARCHAR(100),
    description TEXT,

    is_muted BOOLEAN DEFAULT FALSE NOT NULL,
    is_archived BOOLEAN DEFAULT FALSE NOT NULL,
    is_verified BOOLEAN DEFAULT FALSE NOT NULL,
    is_scam BOOLEAN DEFAULT FALSE NOT NULL,

    participants_count INTEGER,

    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    last_sync_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,

    CONSTRAINT unique_account_peer UNIQUE (account_id, peer_id)
);

CREATE INDEX IF NOT EXISTS idx_resources_account_id ON resources(account_id);
CREATE INDEX IF NOT EXISTS idx_resources_peer_type ON resources(peer_type);
CREATE INDEX IF NOT EXISTS idx_resources_username ON resources(username);
CREATE INDEX IF NOT EXISTS idx_resources_is_active ON resources(account_id, is_active);

-- ========================================
-- 12) 账号绑定日志
-- ========================================
CREATE TABLE IF NOT EXISTS account_bind_logs (
    id SERIAL PRIMARY KEY,
    account_id VARCHAR(36) REFERENCES accounts(account_id) ON DELETE SET NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    bind_code VARCHAR(6),
    bound_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    ip_address INET
);

CREATE INDEX IF NOT EXISTS idx_bind_logs_user_id ON account_bind_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_bind_logs_bound_at ON account_bind_logs(bound_at);

-- ========================================
-- 13) 定时任务
-- ========================================
CREATE TABLE IF NOT EXISTS scheduled_message_tasks (
    task_id VARCHAR(36) PRIMARY KEY,

    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id VARCHAR(36) REFERENCES accounts(account_id) ON DELETE CASCADE,
    chat_id BIGINT,
    title VARCHAR(100) NOT NULL,

    target_peer_id BIGINT,
    target_peer_type VARCHAR(20),
    target_access_hash BIGINT,
    target_peers JSONB,

    enabled BOOLEAN DEFAULT FALSE NOT NULL,
    priority INTEGER DEFAULT 0 NOT NULL,

    repeat_interval_min INTEGER NOT NULL,
    jitter_seconds INTEGER DEFAULT 0 NOT NULL,
    delay_min_seconds INTEGER DEFAULT 0 NOT NULL,
    delay_max_seconds INTEGER DEFAULT 0 NOT NULL,

    day_start_hour INTEGER,
    day_end_hour INTEGER,

    start_at BIGINT,
    end_at BIGINT,

    text TEXT,
    media_type VARCHAR(20) DEFAULT 'none' NOT NULL,
    media_file_id VARCHAR(255),
    buttons JSONB,

    delete_previous BOOLEAN DEFAULT TRUE NOT NULL,
    pin_message BOOLEAN DEFAULT FALSE NOT NULL,

    last_sent_message_id INTEGER,
    next_run_at BIGINT,
    failure_count INTEGER DEFAULT 0 NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,

    CONSTRAINT scheduled_message_tasks_media_type_check
        CHECK (media_type IN ('none', 'photo', 'video', 'sticker', 'animation')),
    CONSTRAINT text_length_check
        CHECK (text IS NULL OR LENGTH(text) <= 4096)
);

CREATE INDEX IF NOT EXISTS idx_user_chat ON scheduled_message_tasks(user_id, chat_id);
CREATE INDEX IF NOT EXISTS idx_account_id ON scheduled_message_tasks(account_id);
CREATE INDEX IF NOT EXISTS idx_enabled_next_run ON scheduled_message_tasks(enabled, next_run_at);
CREATE INDEX IF NOT EXISTS idx_next_run_at ON scheduled_message_tasks(next_run_at);
CREATE INDEX IF NOT EXISTS idx_created_at ON scheduled_message_tasks(created_at DESC);

-- ========================================
-- 14) 任务日志
-- ========================================
CREATE TABLE IF NOT EXISTS task_logs (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(36) NOT NULL,
    send_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    result VARCHAR(20) NOT NULL,
    error_code VARCHAR(50),
    error_message TEXT,
    message_id INTEGER,
    CONSTRAINT task_logs_result_check CHECK (result IN ('success', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_task_id_send_at ON task_logs(task_id, send_at DESC);
CREATE INDEX IF NOT EXISTS idx_task_id ON task_logs(task_id);
CREATE INDEX IF NOT EXISTS idx_send_at ON task_logs(send_at DESC);

-- ========================================
-- 15) 单目标发送异常状态
-- ========================================
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

-- ========================================
-- 16) 循环外键补齐（proxies.assigned_account_id / user_authorizations.current_account_id -> accounts）
-- ========================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'proxies_assigned_account_id_fkey'
    ) THEN
        ALTER TABLE proxies
        ADD CONSTRAINT proxies_assigned_account_id_fkey
        FOREIGN KEY (assigned_account_id)
        REFERENCES accounts(account_id)
        ON DELETE SET NULL;
    END IF;

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

-- ========================================
-- 17) 更新时间触发器
-- ========================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_system_sessions_updated_at ON system_sessions;
CREATE TRIGGER update_system_sessions_updated_at
    BEFORE UPDATE ON system_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_app_settings_updated_at ON app_settings;
CREATE TRIGGER update_app_settings_updated_at
    BEFORE UPDATE ON app_settings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_pricing_plans_updated_at ON pricing_plans;
CREATE TRIGGER update_pricing_plans_updated_at
    BEFORE UPDATE ON pricing_plans
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_telegram_developer_apps_updated_at ON telegram_developer_apps;
CREATE TRIGGER update_telegram_developer_apps_updated_at
    BEFORE UPDATE ON telegram_developer_apps
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_activation_cards_updated_at ON activation_cards;
CREATE TRIGGER update_activation_cards_updated_at
    BEFORE UPDATE ON activation_cards
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_proxies_updated_at ON proxies;
CREATE TRIGGER update_proxies_updated_at
    BEFORE UPDATE ON proxies
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_accounts_updated_at ON accounts;
CREATE TRIGGER update_accounts_updated_at
    BEFORE UPDATE ON accounts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_resources_updated_at ON resources;
CREATE TRIGGER update_resources_updated_at
    BEFORE UPDATE ON resources
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_scheduled_message_tasks_updated_at ON scheduled_message_tasks;
CREATE TRIGGER update_scheduled_message_tasks_updated_at
    BEFORE UPDATE ON scheduled_message_tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_task_target_send_issues_updated_at ON task_target_send_issues;
CREATE TRIGGER update_task_target_send_issues_updated_at
    BEFORE UPDATE ON task_target_send_issues
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
