-- Telegram 定时消息推送管理系统 - 数据库结构
-- PostgreSQL

-- ========================================
-- 1. 创建数据库（如需要）
-- ========================================
-- CREATE DATABASE tg_auto_msg;

-- ========================================
-- 2. 任务表
-- ========================================
CREATE TABLE IF NOT EXISTS scheduled_message_tasks (
    -- 主键
    task_id VARCHAR(36) PRIMARY KEY,

    -- 基础信息
    user_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    title VARCHAR(100) NOT NULL,

    -- 启用状态
    enabled BOOLEAN DEFAULT FALSE NOT NULL,

    -- 重复设置
    repeat_interval_min INTEGER NOT NULL,

    -- 每日时段限制
    day_start_hour INTEGER,
    day_end_hour INTEGER,

    -- 日期范围
    start_at BIGINT,
    end_at BIGINT,

    -- 消息内容
    text TEXT,
    media_type VARCHAR(20) DEFAULT 'none' NOT NULL CHECK (media_type IN ('none', 'photo', 'video', 'sticker', 'animation')),
    media_file_id VARCHAR(255),
    buttons JSONB,

    -- 执行设置
    delete_previous BOOLEAN DEFAULT TRUE NOT NULL,
    pin_message BOOLEAN DEFAULT FALSE NOT NULL,

    -- 运行状态
    last_sent_message_id INTEGER,
    next_run_at BIGINT,
    failure_count INTEGER DEFAULT 0 NOT NULL,

    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_user_chat ON scheduled_message_tasks(user_id, chat_id);
CREATE INDEX IF NOT EXISTS idx_enabled_next_run ON scheduled_message_tasks(enabled, next_run_at);
CREATE INDEX IF NOT EXISTS idx_next_run_at ON scheduled_message_tasks(next_run_at);
CREATE INDEX IF NOT EXISTS idx_created_at ON scheduled_message_tasks(created_at DESC);

-- 添加注释
COMMENT ON TABLE scheduled_message_tasks IS '定时消息任务表';
COMMENT ON COLUMN scheduled_message_tasks.task_id IS '任务唯一标识（UUID）';
COMMENT ON COLUMN scheduled_message_tasks.user_id IS '归属用户 ID';
COMMENT ON COLUMN scheduled_message_tasks.chat_id IS '群组/频道 ID';
COMMENT ON COLUMN scheduled_message_tasks.title IS '显示名';
COMMENT ON COLUMN scheduled_message_tasks.enabled IS '是否启用';
COMMENT ON COLUMN scheduled_message_tasks.repeat_interval_min IS '重复间隔（分钟）';
COMMENT ON COLUMN scheduled_message_tasks.day_start_hour IS '每日发送起始小时';
COMMENT ON COLUMN scheduled_message_tasks.day_end_hour IS '每日发送结束小时';
COMMENT ON COLUMN scheduled_message_tasks.start_at IS '开始时间（Unix 时间戳）';
COMMENT ON COLUMN scheduled_message_tasks.end_at IS '终止时间（Unix 时间戳）';
COMMENT ON COLUMN scheduled_message_tasks.text IS 'HTML 文本（≤4096）';
COMMENT ON COLUMN scheduled_message_tasks.media_type IS '媒体类型（none/photo/video/sticker/animation）';
COMMENT ON COLUMN scheduled_message_tasks.media_file_id IS 'Telegram file_id';
COMMENT ON COLUMN scheduled_message_tasks.buttons IS '二维按钮数组（JSON）';
COMMENT ON COLUMN scheduled_message_tasks.delete_previous IS '删除上一条消息';
COMMENT ON COLUMN scheduled_message_tasks.pin_message IS '是否置顶消息';
COMMENT ON COLUMN scheduled_message_tasks.last_sent_message_id IS '上次发送消息 ID';
COMMENT ON COLUMN scheduled_message_tasks.next_run_at IS '下次执行时间（Unix 时间戳）';
COMMENT ON COLUMN scheduled_message_tasks.failure_count IS '失败次数';
COMMENT ON COLUMN scheduled_message_tasks.created_at IS '创建时间';
COMMENT ON COLUMN scheduled_message_tasks.updated_at IS '更新时间';

-- ========================================
-- 3. 任务日志表
-- ========================================
CREATE TABLE IF NOT EXISTS task_logs (
    -- 主键
    id SERIAL PRIMARY KEY,

    -- 关联信息
    task_id VARCHAR(36) NOT NULL,

    -- 执行信息
    send_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    result VARCHAR(20) NOT NULL CHECK (result IN ('success', 'failed')),
    error_code VARCHAR(50),
    error_message TEXT,
    message_id INTEGER
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_task_id_send_at ON task_logs(task_id, send_at DESC);
CREATE INDEX IF NOT EXISTS idx_task_id ON task_logs(task_id);
CREATE INDEX IF NOT EXISTS idx_send_at ON task_logs(send_at DESC);
CREATE INDEX IF NOT EXISTS idx_result ON task_logs(result);

-- 添加注释
COMMENT ON TABLE task_logs IS '任务执行日志表';
COMMENT ON COLUMN task_logs.id IS '日志 ID（自增）';
COMMENT ON COLUMN task_logs.task_id IS '任务 ID（关联 scheduled_message_tasks.task_id）';
COMMENT ON COLUMN task_logs.send_at IS '发送时间';
COMMENT ON COLUMN task_logs.result IS '执行结果（success/failed）';
COMMENT ON COLUMN task_logs.error_code IS '错误代码';
COMMENT ON COLUMN task_logs.error_message IS '错误信息';
COMMENT ON COLUMN task_logs.message_id IS '消息 ID';

-- ========================================
-- 4. 创建更新时间触发器
-- ========================================

-- 创建更新时间函数
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- 为 scheduled_message_tasks 表添加触发器
DROP TRIGGER IF EXISTS update_scheduled_message_tasks_updated_at ON scheduled_message_tasks;
CREATE TRIGGER update_scheduled_message_tasks_updated_at
    BEFORE UPDATE ON scheduled_message_tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ========================================
-- 5. 初始化数据（可选）
-- ========================================

-- 示例任务（注释掉，避免自动创建）
/*
INSERT INTO scheduled_message_tasks (
    task_id,
    user_id,
    chat_id,
    title,
    enabled,
    repeat_interval_min,
    day_start_hour,
    day_end_hour,
    text,
    media_type,
    delete_previous,
    pin_message
) VALUES (
    '550e8400-e29b-41d4-a716-446655440000',
    123456789,
    -1001234567890,
    '示例任务',
    FALSE,
    60,
    9,
    18,
    '<b>Hello World!</b>',
    'none',
    TRUE,
    FALSE
);
*/

-- ========================================
-- 6. 性能优化建议
-- ========================================

-- 定期清理旧日志（保留最近 30 天）
-- DELETE FROM task_logs WHERE send_at < CURRENT_TIMESTAMP - INTERVAL '30 days';

-- 禁用的任务索引优化（可选）
-- CREATE INDEX IF NOT EXISTS idx_enabled_tasks ON scheduled_message_tasks(task_id) WHERE enabled = TRUE;

-- ========================================
-- 7. 备份与恢复
-- ========================================

-- 备份
-- pg_dump -U postgres -d tg_auto_msg -f backup.sql

-- 恢复
-- psql -U postgres -d tg_auto_msg -f backup.sql

-- ========================================
-- 8. 监控查询示例
-- ========================================

-- 查看任务统计
/*
SELECT
    enabled,
    COUNT(*) as task_count
FROM scheduled_message_tasks
GROUP BY enabled;
*/

-- 查看最近失败的日志
/*
SELECT
    tl.*,
    smt.title
FROM task_logs tl
JOIN scheduled_message_tasks smt ON tl.task_id = smt.task_id
WHERE tl.result = 'failed'
ORDER BY tl.send_at DESC
LIMIT 10;
*/

-- 查看即将执行的任务
/*
SELECT
    task_id,
    title,
    next_run_at,
    enabled
FROM scheduled_message_tasks
WHERE enabled = TRUE
    AND next_run_at IS NOT NULL
    AND next_run_at <= EXTRACT(EPOCH FROM CURRENT_TIMESTAMP) + 3600
ORDER BY next_run_at;
*/
