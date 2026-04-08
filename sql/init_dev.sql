-- ============================================
-- Telegram 定时消息推送管理系统 - 数据库初始化脚本
-- ============================================
-- 用途: 本地开发重置数据库并创建完整表结构
-- 执行方式: psql -U postgres -h <host> -d postgres -f sql/init_dev.sql
-- ============================================

-- 创建数据库
DROP DATABASE IF EXISTS tg_auto_msg;
CREATE DATABASE tg_auto_msg
    ENCODING 'UTF8'
    LC_COLLATE = 'en_US.UTF-8'
    LC_CTYPE = 'en_US.UTF-8'
    TEMPLATE template0;

-- 连接到新创建的数据库
\c tg_auto_msg

-- ============================================
-- 表: 系统用户表 (users)
-- ============================================
CREATE TABLE IF NOT EXISTS users (
    -- 主键
    id SERIAL PRIMARY KEY,

    -- 用户凭证
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    bot_initial_password_encrypted VARCHAR(1024),
    bot_initial_password_viewable BOOLEAN DEFAULT FALSE NOT NULL,
    password_changed_after_bot_registration BOOLEAN DEFAULT FALSE NOT NULL,
    bot_trial_eligible_at TIMESTAMP,
    bot_trial_granted_at TIMESTAMP,
    bot_trial_authorization_id VARCHAR(36),

    -- 用户信息
    email VARCHAR(100),

    -- 状态
    is_active BOOLEAN DEFAULT TRUE,

    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_ci_not_null
ON users ((LOWER(email)))
WHERE email IS NOT NULL;

-- 注释
COMMENT ON TABLE users IS '系统用户表';
COMMENT ON COLUMN users.username IS '用户名（唯一）';
COMMENT ON COLUMN users.password_hash IS '密码哈希（bcrypt）';
COMMENT ON COLUMN users.bot_initial_password_encrypted IS 'Bot自动注册初始密码（加密）';
COMMENT ON COLUMN users.bot_initial_password_viewable IS '是否允许在Bot中查看初始密码';
COMMENT ON COLUMN users.password_changed_after_bot_registration IS 'Bot自动注册后是否已修改密码';
COMMENT ON COLUMN users.bot_trial_eligible_at IS 'Bot首绑试用资格获得时间';
COMMENT ON COLUMN users.bot_trial_granted_at IS 'Bot首绑试用授权发放时间';
COMMENT ON COLUMN users.bot_trial_authorization_id IS 'Bot首绑试用授权ID';
COMMENT ON COLUMN users.email IS '电子邮箱';
COMMENT ON COLUMN users.is_active IS '是否激活';

-- ============================================
-- 表: 卡密规格表 (pricing_plans)
-- ============================================
CREATE TABLE IF NOT EXISTS pricing_plans (
    plan_code VARCHAR(32) PRIMARY KEY,
    display_name VARCHAR(100) NOT NULL,
    billing_cycle VARCHAR(20) NOT NULL,
    price_cents INTEGER NOT NULL,
    duration_days INTEGER NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    sort_order INTEGER DEFAULT 0 NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pricing_plans_is_active ON pricing_plans(is_active, sort_order);

INSERT INTO pricing_plans (plan_code, display_name, billing_cycle, price_cents, duration_days, is_active, sort_order)
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

COMMENT ON TABLE pricing_plans IS '卡密规格配置表';

-- ============================================
-- 表: 卡密表 (activation_cards)
-- ============================================
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_activation_cards_is_used ON activation_cards(is_used, is_active);
CREATE INDEX IF NOT EXISTS idx_activation_cards_plan_code ON activation_cards(plan_code);

COMMENT ON TABLE activation_cards IS '卡密表';

-- ============================================
-- 表: 管理员审计日志表 (admin_audit_logs)
-- ============================================
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_created_at ON admin_audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_action ON admin_audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_admin_audit_logs_developer_app_id ON admin_audit_logs(developer_app_id);

COMMENT ON TABLE admin_audit_logs IS '管理员操作审计日志表';

-- ============================================
-- 表: 系统配置表 (app_settings)
-- ============================================
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

COMMENT ON TABLE app_settings IS '系统配置键值表';
COMMENT ON COLUMN app_settings.key IS '配置键';
COMMENT ON COLUMN app_settings.value IS '配置值';

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

-- ============================================
-- 表: Telegram 开发者应用凭证池 (telegram_developer_apps)
-- ============================================
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_telegram_developer_apps_active ON telegram_developer_apps(is_active);

COMMENT ON TABLE telegram_developer_apps IS 'Telegram 开发者应用凭证池';
COMMENT ON COLUMN telegram_developer_apps.api_id IS 'Telegram API ID';
COMMENT ON COLUMN telegram_developer_apps.api_hash_encrypted IS '加密后的 API Hash';
COMMENT ON COLUMN telegram_developer_apps.max_accounts IS '可分配账号上限（0=不限）';

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

-- ============================================
-- 表: 系统会话表 (system_sessions)
-- ============================================
CREATE TABLE IF NOT EXISTS system_sessions (
    session_key VARCHAR(64) PRIMARY KEY,                -- manager_bot/global_userbot
    session_encrypted TEXT NOT NULL,                    -- 加密的 Telethon StringSession
    developer_app_id INTEGER REFERENCES telegram_developer_apps(id) ON DELETE SET NULL,
    session_meta JSONB,                                 -- 附加元数据
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_system_sessions_updated_at ON system_sessions(updated_at);
CREATE INDEX IF NOT EXISTS idx_system_sessions_developer_app_id ON system_sessions(developer_app_id);

COMMENT ON TABLE system_sessions IS '系统级 Telegram 会话表（bot/userbot）';
COMMENT ON COLUMN system_sessions.session_key IS '会话键: manager_bot/global_userbot';
COMMENT ON COLUMN system_sessions.session_encrypted IS '加密后的 Telethon StringSession';
COMMENT ON COLUMN system_sessions.developer_app_id IS '关联开发者应用凭证';
COMMENT ON COLUMN system_sessions.session_meta IS '附加元数据';

-- ============================================
-- 表: 代理池表 (proxies)
-- ============================================
CREATE TABLE IF NOT EXISTS proxies (
    -- 主键
    proxy_id SERIAL PRIMARY KEY,

    -- 代理配置
    proxy_type VARCHAR(10) NOT NULL,                    -- socks5/http/mtproto
    host VARCHAR(255) NOT NULL,
    port INTEGER NOT NULL,
    username VARCHAR(100),                              -- 代理认证用户名
    password_encrypted VARCHAR(255),                    -- 加密存储的密码

    -- 健康状态
    is_active BOOLEAN DEFAULT TRUE,
    is_healthy BOOLEAN DEFAULT TRUE,
    last_check_at TIMESTAMP,
    response_time_ms INTEGER,                           -- 响应时间（毫秒）

    -- 使用统计
    usage_count INTEGER DEFAULT 0,
    assigned_account_id VARCHAR(36),                    -- 分配给的账号

    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 唯一约束
    CONSTRAINT unique_proxy UNIQUE (proxy_type, host, port)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_proxies_is_active ON proxies(is_active, is_healthy);
CREATE INDEX IF NOT EXISTS idx_proxies_assigned ON proxies(assigned_account_id);

-- 注释
COMMENT ON TABLE proxies IS '代理池表';
COMMENT ON COLUMN proxies.proxy_type IS '代理类型: socks5/http/mtproto';
COMMENT ON COLUMN proxies.host IS '代理主机';
COMMENT ON COLUMN proxies.port IS '代理端口';
COMMENT ON COLUMN proxies.password_encrypted IS '加密存储的密码';
COMMENT ON COLUMN proxies.is_healthy IS '是否健康';
COMMENT ON COLUMN proxies.response_time_ms IS '响应时间（毫秒）';
COMMENT ON COLUMN proxies.assigned_account_id IS '分配给的账号 ID';

-- ============================================
-- 表: Userbot 账号管理表 (accounts)
-- ============================================
CREATE TABLE IF NOT EXISTS accounts (
    -- 主键
    account_id VARCHAR(36) PRIMARY KEY,

    -- 用户信息
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,  -- 关联到系统用户
    tg_user_id BIGINT,                                  -- 登录后的 Telegram UID
    username VARCHAR(50),                               -- Telegram 用户名
    first_name VARCHAR(100),                            -- 名字
    phone VARCHAR(20),                                  -- 手机号

    -- 登录凭证（加密存储）
    string_session_encrypted TEXT NOT NULL,             -- AES-256-GCM 加密的 StringSession
    developer_app_id INTEGER REFERENCES telegram_developer_apps(id) ON DELETE SET NULL,
    developer_app_version INTEGER DEFAULT 1 NOT NULL,
    bind_code VARCHAR(6),                               -- 6位绑定码
    bind_code_expires_at TIMESTAMP,                     -- 绑定码过期时间

    -- 代理配置
    proxy_id INTEGER REFERENCES proxies(proxy_id),

    -- 账号状态
    is_active BOOLEAN DEFAULT TRUE,
    is_banned BOOLEAN DEFAULT FALSE,
    health_status VARCHAR(20) DEFAULT 'online',         -- online/offline/banned

    -- 风控状态
    is_flooding BOOLEAN DEFAULT FALSE,
    flood_until TIMESTAMP,
    reauth_required BOOLEAN DEFAULT FALSE NOT NULL,
    reauth_reason VARCHAR(64),
    reauth_required_at TIMESTAMP,

    -- 负载均衡
    weight INTEGER DEFAULT 100,

    -- 统计
    messages_sent INTEGER DEFAULT 0,
    last_used_at TIMESTAMP,

    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 约束
    CONSTRAINT unique_bind_code UNIQUE (bind_code)
);

-- 兼容旧库：为已存在的 accounts 补齐绑定码字段
ALTER TABLE IF EXISTS accounts
    ADD COLUMN IF NOT EXISTS bind_code VARCHAR(6);
ALTER TABLE IF EXISTS accounts
    ADD COLUMN IF NOT EXISTS bind_code_expires_at TIMESTAMP;
ALTER TABLE IF EXISTS accounts
    ADD COLUMN IF NOT EXISTS developer_app_id INTEGER REFERENCES telegram_developer_apps(id) ON DELETE SET NULL;
ALTER TABLE IF EXISTS accounts
    ADD COLUMN IF NOT EXISTS developer_app_version INTEGER DEFAULT 1 NOT NULL;
ALTER TABLE IF EXISTS accounts
    ADD COLUMN IF NOT EXISTS reauth_required BOOLEAN DEFAULT FALSE NOT NULL;
ALTER TABLE IF EXISTS accounts
    ADD COLUMN IF NOT EXISTS reauth_reason VARCHAR(64);
ALTER TABLE IF EXISTS accounts
    ADD COLUMN IF NOT EXISTS reauth_required_at TIMESTAMP;

-- 索引
CREATE INDEX IF NOT EXISTS idx_accounts_user_id ON accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_accounts_tg_user_id ON accounts(tg_user_id);
CREATE INDEX IF NOT EXISTS idx_accounts_bind_code ON accounts(bind_code);
CREATE INDEX IF NOT EXISTS idx_accounts_health_status ON accounts(health_status);
CREATE INDEX IF NOT EXISTS idx_accounts_developer_app_id ON accounts(developer_app_id);
CREATE INDEX IF NOT EXISTS idx_accounts_reauth_required ON accounts(reauth_required);

-- 注释
COMMENT ON TABLE accounts IS 'Userbot 账号管理表';
COMMENT ON COLUMN accounts.user_id IS '归属用户 UID';
COMMENT ON COLUMN accounts.tg_user_id IS '登录后的 Telegram UID';
COMMENT ON COLUMN accounts.string_session_encrypted IS 'AES-256-GCM 加密的 StringSession';
COMMENT ON COLUMN accounts.developer_app_id IS '关联开发者应用凭证';
COMMENT ON COLUMN accounts.bind_code IS '6位绑定码';
COMMENT ON COLUMN accounts.proxy_id IS '关联代理 ID';
COMMENT ON COLUMN accounts.health_status IS '健康状态: online/offline/banned';
COMMENT ON COLUMN accounts.is_flooding IS '是否触发 FloodWait';
COMMENT ON COLUMN accounts.weight IS '权重（用于账号选择）';

-- ============================================
-- 表: Dialogs 资源表 (resources)
-- ============================================
CREATE TABLE IF NOT EXISTS resources (
    -- 主键
    resource_id SERIAL PRIMARY KEY,

    -- 归属
    account_id VARCHAR(36) NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,

    -- Peer 信息
    peer_id BIGINT NOT NULL,                            -- 群组/频道/用户 ID
    peer_type VARCHAR(20) NOT NULL,                     -- user/chat/supergroup/channel
    access_hash BIGINT,                                 -- 构造 InputPeer 必需

    -- 元数据
    title VARCHAR(255),
    username VARCHAR(100),                              -- @username
    description TEXT,

    -- 分类标记
    is_muted BOOLEAN DEFAULT FALSE,
    is_archived BOOLEAN DEFAULT FALSE,
    is_verified BOOLEAN DEFAULT FALSE,
    is_scam BOOLEAN DEFAULT FALSE,

    -- 成员数（群组/频道）
    participants_count INTEGER,

    -- 同步状态
    is_active BOOLEAN DEFAULT TRUE,
    last_sync_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 唯一约束
    CONSTRAINT unique_account_peer UNIQUE (account_id, peer_id)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_resources_account_id ON resources(account_id);
CREATE INDEX IF NOT EXISTS idx_resources_peer_type ON resources(peer_type);
CREATE INDEX IF NOT EXISTS idx_resources_username ON resources(username) WHERE username IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_resources_is_active ON resources(account_id, is_active);

-- 注释
COMMENT ON TABLE resources IS 'Dialogs 资源表';
COMMENT ON COLUMN resources.account_id IS '归属账号 ID';
COMMENT ON COLUMN resources.peer_id IS '群组/频道/用户 ID';
COMMENT ON COLUMN resources.peer_type IS 'Peer 类型: user/chat/supergroup/channel';
COMMENT ON COLUMN resources.access_hash IS '构造 InputPeer 必需';
COMMENT ON COLUMN resources.is_verified IS '是否认证';
COMMENT ON COLUMN resources.is_scam IS '是否诈骗';

-- ============================================
-- 表: 账号绑定日志表 (account_bind_logs)
-- ============================================
CREATE TABLE IF NOT EXISTS account_bind_logs (
    id SERIAL PRIMARY KEY,
    account_id VARCHAR(36) REFERENCES accounts(account_id) ON DELETE SET NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    bind_code VARCHAR(6),
    bound_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ip_address INET
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_bind_logs_user_id ON account_bind_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_bind_logs_bound_at ON account_bind_logs(bound_at);

-- 注释
COMMENT ON TABLE account_bind_logs IS '账号绑定日志表';
COMMENT ON COLUMN account_bind_logs.ip_address IS 'IP 地址';

-- ============================================
-- 表: 定时消息任务表 (scheduled_message_tasks) - 修改后的版本
-- ============================================
CREATE TABLE IF NOT EXISTS scheduled_message_tasks (
    -- 主键
    task_id VARCHAR(36) PRIMARY KEY,

    -- 基础信息
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id VARCHAR(36) REFERENCES accounts(account_id) ON DELETE CASCADE,  -- 执行账号 ID
    chat_id BIGINT,                                        -- 兼容旧数据
    title VARCHAR(100) NOT NULL,

    -- 目标 Peer 信息（新架构）
    target_peer_id BIGINT,
    target_peer_type VARCHAR(20),
    target_access_hash BIGINT,
    target_peers JSONB,

    -- 启用状态
    enabled BOOLEAN DEFAULT FALSE,
    priority INTEGER DEFAULT 0,                          -- 任务优先级（越大越优先）

    -- 重复设置
    repeat_interval_min INTEGER NOT NULL,
    jitter_seconds INTEGER DEFAULT 0,                      -- 随机抖动秒数（0-300）
    delay_min_seconds INTEGER DEFAULT 0,                   -- 随机延迟下限（秒）
    delay_max_seconds INTEGER DEFAULT 0,                   -- 随机延迟上限（秒）

    -- 每日时段限制
    day_start_hour INTEGER,
    day_end_hour INTEGER,

    -- 日期范围
    start_at BIGINT,
    end_at BIGINT,

    -- 消息内容
    text TEXT,
    media_type VARCHAR(20) DEFAULT 'none' CHECK (media_type IN ('none', 'photo', 'video', 'sticker', 'animation')),
    media_file_id VARCHAR(255),
    buttons JSONB,

    -- 执行设置
    delete_previous BOOLEAN DEFAULT TRUE,
    pin_message BOOLEAN DEFAULT FALSE,

    -- 运行状态
    last_sent_message_id INTEGER,
    next_run_at BIGINT,
    failure_count INTEGER DEFAULT 0,

    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 注释
    CONSTRAINT text_length_check CHECK (LENGTH(text) <= 4096)
);

-- 兼容旧库：为已存在的 scheduled_message_tasks 补齐新字段
ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS account_id VARCHAR(36) REFERENCES accounts(account_id) ON DELETE CASCADE;
ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS target_peer_id BIGINT;
ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS target_peer_type VARCHAR(20);
ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS target_access_hash BIGINT;
ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS target_peers JSONB;
ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS priority INTEGER DEFAULT 0;
ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS jitter_seconds INTEGER DEFAULT 0;
ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS delay_min_seconds INTEGER DEFAULT 0;
ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS delay_max_seconds INTEGER DEFAULT 0;
ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS next_run_at BIGINT;
ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS media_type VARCHAR(20) DEFAULT 'none';
ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS media_file_id VARCHAR(255);

-- 兼容旧库：media_type 可能是历史 enum 类型，统一为小写字符串并重建检查约束
DO $$
BEGIN
    IF to_regclass('scheduled_message_tasks') IS NOT NULL THEN
        ALTER TABLE scheduled_message_tasks
        ALTER COLUMN media_type TYPE VARCHAR(20)
        USING LOWER(media_type::text);

        ALTER TABLE scheduled_message_tasks
        ALTER COLUMN media_type SET DEFAULT 'none';

        UPDATE scheduled_message_tasks
        SET media_type = 'none'
        WHERE media_type IS NULL OR TRIM(media_type) = '';

        IF EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'scheduled_message_tasks_media_type_check'
        ) THEN
            ALTER TABLE scheduled_message_tasks
            DROP CONSTRAINT scheduled_message_tasks_media_type_check;
        END IF;

        ALTER TABLE scheduled_message_tasks
        ADD CONSTRAINT scheduled_message_tasks_media_type_check
        CHECK (media_type IN ('none', 'photo', 'video', 'sticker', 'animation'));
    END IF;
END
$$;

-- 索引
CREATE INDEX IF NOT EXISTS idx_scheduled_user_chat ON scheduled_message_tasks(user_id, chat_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_account_id ON scheduled_message_tasks(account_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_enabled_next_run ON scheduled_message_tasks(enabled, next_run_at);

-- 注释
COMMENT ON TABLE scheduled_message_tasks IS '定时消息任务表';
COMMENT ON COLUMN scheduled_message_tasks.account_id IS '执行账号 ID';
COMMENT ON COLUMN scheduled_message_tasks.chat_id IS '群组/频道 ID（兼容旧数据）';
COMMENT ON COLUMN scheduled_message_tasks.target_peer_id IS '目标 Peer ID（新架构）';
COMMENT ON COLUMN scheduled_message_tasks.target_peer_type IS '目标 Peer 类型';
COMMENT ON COLUMN scheduled_message_tasks.target_access_hash IS '目标 Access Hash';
COMMENT ON COLUMN scheduled_message_tasks.target_peers IS '多目标 Peer 列表';
COMMENT ON COLUMN scheduled_message_tasks.priority IS '任务优先级（越大越优先）';
COMMENT ON COLUMN scheduled_message_tasks.jitter_seconds IS '随机抖动秒数（0-300）';
COMMENT ON COLUMN scheduled_message_tasks.delay_min_seconds IS '随机延迟下限（秒）';
COMMENT ON COLUMN scheduled_message_tasks.delay_max_seconds IS '随机延迟上限（秒）';

-- 补齐循环外键：proxies.assigned_account_id -> accounts.account_id
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'proxies' AND column_name = 'assigned_account_id'
    ) AND NOT EXISTS (
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
END
$$;

-- ============================================
-- 表: 任务执行日志表 (task_logs)
-- ============================================
CREATE TABLE IF NOT EXISTS task_logs (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(36) NOT NULL,
    send_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    result VARCHAR(20) NOT NULL CHECK (result IN ('success', 'failed')),
    error_code VARCHAR(50),
    error_message TEXT,
    message_id INTEGER
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_task_logs_task_id_send_at ON task_logs(task_id, send_at);
CREATE INDEX IF NOT EXISTS idx_task_logs_send_at ON task_logs(send_at);

-- 注释
COMMENT ON TABLE task_logs IS '任务执行日志表';
COMMENT ON COLUMN task_logs.result IS '执行结果: success/failed';

-- ============================================
-- 自动更新 updated_at 触发器
-- ============================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 为所有需要的表创建触发器
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

-- ============================================
-- 完成
-- ============================================
-- 验证表创建
SELECT 'Database initialized successfully!' AS status;
SELECT COUNT(*) AS tables_created
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'users',
    'pricing_plans',
    'activation_cards',
    'admin_audit_logs',
    'app_settings',
    'schema_migrations',
    'telegram_developer_apps',
    'system_sessions',
    'proxies',
    'accounts',
    'resources',
    'account_bind_logs',
    'scheduled_message_tasks',
    'task_logs'
);
