# Scheduler Architecture

## 分层

- `backend/scheduler/core/worker.py`
  - 调度主循环与任务编排。
- `backend/scheduler/core/queue_ops.py`
  - Redis 连接自愈、到期任务入队/出队。
- `backend/scheduler/core/task_execution.py`
  - 目标解析、媒体解析、发送链路、限流/熔断保护。
- `backend/scheduler/core/task_lifecycle.py`
  - 成功/失败状态流转、日志落库、任务暂停策略。

## 设计规则

1. 主循环只做编排，不内联具体发送细节。
2. 队列操作与生命周期操作保持独立模块。
3. 新调度策略优先落在 `core/*` 辅助函数，不在 `worker.py` 直接扩展大段逻辑。
