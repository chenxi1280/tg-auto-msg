# SQL Layout

项目级 SQL 资产统一放在根目录 `sql/`，不放在后端代码目录中。

## 目录结构

- `init.sql`：完整基线建表脚本（幂等）。
- `init_dev.sql`：本地开发初始化脚本（包含 `DROP/CREATE DATABASE`）。
- `migrations/`
  - 运行时兼容迁移脚本，由 `backend/database/session.py` 自动加载。
  - 按文件名字典序执行。
  - 多语句文件使用 `-- @statement` 分隔。

## 运行时行为

`backend/database/session.py` 在启动/首次 DB 访问时执行：

1. `Base.metadata.create_all()`
2. 依次执行 `sql/migrations/*.sql`
3. 校验 `scheduled_message_tasks` 关键列完整性
