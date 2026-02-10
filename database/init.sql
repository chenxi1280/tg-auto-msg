-- ============================================
-- Telegram 定时消息推送管理系统 - 数据库初始化脚本
-- ============================================
-- 用途: 创建数据库和表结构
-- 执行方式: psql -U postgres -h <host> -d postgres -f init.sql
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

    -- 用户信息
    email VARCHAR(100),

    -- 状态
    is_active BOOLEAN DEFAULT TRUE,

    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_is_active ON users(is_active);

-- 注释
COMMENT ON TABLE users IS '系统用户表';
COMMENT ON COLUMN users.username IS '用户名（唯一）';
COMMENT ON COLUMN users.password_hash IS '密码哈希（bcrypt）';
COMMENT ON COLUMN users.email IS '电子邮箱';
COMMENT ON COLUMN users.is_active IS '是否激活';

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
CREATE INDEX idx_proxies_is_active ON proxies(is_active, is_healthy);
CREATE INDEX idx_proxies_assigned ON proxies(assigned_account_id);

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

-- 索引
CREATE INDEX idx_accounts_user_id ON accounts(user_id);
CREATE INDEX idx_accounts_tg_user_id ON accounts(tg_user_id);
CREATE INDEX idx_accounts_bind_code ON accounts(bind_code);
CREATE INDEX idx_accounts_health_status ON accounts(health_status);

-- 注释
COMMENT ON TABLE accounts IS 'Userbot 账号管理表';
COMMENT ON COLUMN accounts.user_id IS '归属用户 UID';
COMMENT ON COLUMN accounts.tg_user_id IS '登录后的 Telegram UID';
COMMENT ON COLUMN accounts.string_session_encrypted IS 'AES-256-GCM 加密的 StringSession';
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
CREATE INDEX idx_resources_account_id ON resources(account_id);
CREATE INDEX idx_resources_peer_type ON resources(peer_type);
CREATE INDEX idx_resources_username ON resources(username) WHERE username IS NOT NULL;
CREATE INDEX idx_resources_is_active ON resources(account_id, is_active);

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
    account_id VARCHAR(36) REFERENCES accounts(account_id),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    bind_code VARCHAR(6),
    bound_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ip_address INET
);

-- 索引
CREATE INDEX idx_bind_logs_user_id ON account_bind_logs(user_id);
CREATE INDEX idx_bind_logs_bound_at ON account_bind_logs(bound_at);

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
    account_id VARCHAR(36) REFERENCES accounts(account_id),  -- 执行账号 ID
    chat_id BIGINT,                                        -- 兼容旧数据
    title VARCHAR(100) NOT NULL,

    -- 目标 Peer 信息（新架构）
    target_peer_id BIGINT,
    target_peer_type VARCHAR(20),
    target_access_hash BIGINT,

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
    ADD COLUMN IF NOT EXISTS account_id VARCHAR(36) REFERENCES accounts(account_id);
ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS target_peer_id BIGINT;
ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS target_peer_type VARCHAR(20);
ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS target_access_hash BIGINT;
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

-- 索引
CREATE INDEX idx_scheduled_user_chat ON scheduled_message_tasks(user_id, chat_id);
CREATE INDEX idx_scheduled_account_id ON scheduled_message_tasks(account_id);
CREATE INDEX idx_scheduled_enabled_next_run ON scheduled_message_tasks(enabled, next_run_at);

-- 注释
COMMENT ON TABLE scheduled_message_tasks IS '定时消息任务表';
COMMENT ON COLUMN scheduled_message_tasks.account_id IS '执行账号 ID';
COMMENT ON COLUMN scheduled_message_tasks.chat_id IS '群组/频道 ID（兼容旧数据）';
COMMENT ON COLUMN scheduled_message_tasks.target_peer_id IS '目标 Peer ID（新架构）';
COMMENT ON COLUMN scheduled_message_tasks.target_peer_type IS '目标 Peer 类型';
COMMENT ON COLUMN scheduled_message_tasks.target_access_hash IS '目标 Access Hash';
COMMENT ON COLUMN scheduled_message_tasks.priority IS '任务优先级（越大越优先）';
COMMENT ON COLUMN scheduled_message_tasks.jitter_seconds IS '随机抖动秒数（0-300）';
COMMENT ON COLUMN scheduled_message_tasks.delay_min_seconds IS '随机延迟下限（秒）';
COMMENT ON COLUMN scheduled_message_tasks.delay_max_seconds IS '随机延迟上限（秒）';

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
CREATE INDEX idx_task_logs_task_id_send_at ON task_logs(task_id, send_at);
CREATE INDEX idx_task_logs_send_at ON task_logs(send_at);

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
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_proxies_updated_at
    BEFORE UPDATE ON proxies
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_accounts_updated_at
    BEFORE UPDATE ON accounts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_resources_updated_at
    BEFORE UPDATE ON resources
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

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
    'proxies',
    'accounts',
    'resources',
    'account_bind_logs',
    'scheduled_message_tasks',
    'task_logs'
);
