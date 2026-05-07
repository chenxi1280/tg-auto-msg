-- 030: 添加性能索引
-- 1. scheduler 查询优化: (enabled, trigger_mode, next_run_at) 覆盖 queue_ops 查询
-- 2. accounts 表: (user_id, is_active) 复合索引覆盖高频查询

-- scheduler: 替换 idx_enabled_next_run 为更精确的三列索引
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_scheduler
    ON scheduled_message_tasks (enabled, trigger_mode, next_run_at);

-- accounts: 添加复合索引（保留原有 idx_accounts_user_id 供仅按 user_id 查询使用）
CREATE INDEX IF NOT EXISTS idx_accounts_user_active
    ON accounts (user_id, is_active);
