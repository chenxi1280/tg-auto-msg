-- Telegram 定时消息推送管理系统 - 基线 Schema（幂等）
-- 用途：生产/开发环境的完整建表脚本（不创建数据库）

-- ========================================
-- 1) 系统用户
-- ========================================
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    email VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active);

-- ========================================
-- 2) 系统会话
-- ========================================
CREATE TABLE IF NOT EXISTS system_sessions (
    session_key VARCHAR(64) PRIMARY KEY,
    session_encrypted TEXT NOT NULL,
    session_meta JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_system_sessions_updated_at ON system_sessions(updated_at);

-- ========================================
-- 3) 代理池
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
-- 4) 账号
-- ========================================
CREATE TABLE IF NOT EXISTS accounts (
    account_id VARCHAR(36) PRIMARY KEY,

    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tg_user_id BIGINT,
    username VARCHAR(50),
    first_name VARCHAR(100),
    phone VARCHAR(20),

    string_session_encrypted TEXT NOT NULL,
    bind_code VARCHAR(6),
    bind_code_expires_at TIMESTAMP,

    proxy_id INTEGER REFERENCES proxies(proxy_id),

    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    is_banned BOOLEAN DEFAULT FALSE NOT NULL,
    health_status VARCHAR(20) DEFAULT 'online' NOT NULL,

    is_flooding BOOLEAN DEFAULT FALSE NOT NULL,
    flood_until TIMESTAMP,

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

-- ========================================
-- 5) 资源
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
-- 6) 账号绑定日志
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
-- 7) 定时任务
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
-- 8) 任务日志
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
-- 9) 循环外键补齐（proxies.assigned_account_id -> accounts）
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
END
$$;

-- ========================================
-- 10) 更新时间触发器
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
