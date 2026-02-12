# Database Architecture

## 分层

- `backend/database/schema/models.py`
  - ORM 模型与枚举定义。
- `backend/database/runtime/session.py`
  - Engine/Session 工厂、schema 初始化、SQL 迁移执行。
- `backend/database/init_db.py`
  - 初始化入口脚本。

## 设计规则

1. 表结构与 ORM 变更只修改 `schema/models.py`。
2. 连接池、会话、迁移执行策略只修改 `runtime/session.py`。
3. `sql/migrations/*.sql` 作为运行时兼容迁移输入，按文件名顺序执行。
