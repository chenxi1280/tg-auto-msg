# 项目结构说明

```
tg-auto-msg/
├── main.py                          # 主入口（自动注入 backend 到 sys.path）
├── reinit_db.py                     # 数据库重置脚本
├── start.sh                         # 本地快速启动脚本
├── docker-compose.yml               # Docker Compose 配置
├── Dockerfile                       # Docker 镜像构建
├── requirements.txt                 # Python 依赖
├── .env.example                     # 环境变量示例
├── sql/                             # 项目级 SQL 资产
│   ├── init.sql                     # 全量建表脚本（幂等）
│   ├── init_dev.sql                 # 本地开发初始化（含建库）
│   └── migrations/                  # 运行时兼容迁移 SQL
│
├── backend/                         # 后端代码根目录
│   ├── bot/                         # Telegram Bot / Userbot 逻辑
│   │   ├── account_manager.py           # 账号管理编排层（聚合服务）
│   │   ├── client.py                    # Telegram 客户端门面（bot/userbot/二维码登录）
│   │   ├── resource_manager.py          # 资源管理门面
│   │   ├── proxy_pool.py                # 代理池门面
│   │   ├── circuit_breaker.py           # 熔断器门面
│   │   ├── account/                     # 账号子域实现
│   │   │   ├── binding_service.py       # 账号绑定与绑定码签发逻辑
│   │   │   ├── client_runtime.py        # 账号客户端创建/代理切换/连接管理
│   │   │   └── health_selection.py      # 账号选择策略/健康状态/统计更新
│   │   ├── client_runtime/              # 系统 client 会话与二维码登录实现
│   │   │   ├── session_store.py         # 系统会话存储/恢复/清理
│   │   │   └── qr_login.py              # 二维码登录流程与刷新策略
│   │   ├── resources/                   # 资源子域实现
│   │   │   ├── sync_ops.py              # 资源全量同步流程
│   │   │   ├── query_ops.py             # 资源查询/InputPeer 构造
│   │   │   └── peer_utils.py            # Peer 类型/标题/变更判断
│   │   ├── proxy/                       # 代理子域实现
│   │   │   ├── ops.py                   # 代理 CRUD/分配逻辑
│   │   │   └── health.py                # 代理健康检测与配置构造
│   │   ├── circuit/                     # 熔断子域实现
│   │   │   ├── notify.py                # 熔断通知逻辑
│   │   │   └── recovery.py              # 熔断恢复与会话健康检查
│   │   ├── handlers/                    # Bot 对话处理层（入口/任务域/账号域/辅助模块）
│   ├── config/                      # 配置模块
│   ├── database/                    # ORM 与会话管理
│   ├── h5_backend/                  # FastAPI API + SPA 托管
│   │   ├── api.py                   # 应用装配（lifespan/router/static）
│   │   ├── dependencies.py          # 通用权限校验依赖
│   │   ├── routers/                 # 薄路由层（仅参数/鉴权/调用）
│   │   └── services/                # 业务服务层（任务/账号/登录/代理）
│   │       ├── task_service.py      # 任务流程编排
│   │       ├── task_payload.py      # 任务 payload 规则与校验
│   │       └── task_serializers.py  # 任务响应序列化
│   ├── scheduler/                   # 调度器与执行队列
│   │   ├── ARCHITECTURE.md          # 调度器模块设计说明
│   │   ├── worker.py                # 调度器主循环编排
│   │   └── core/                    # 调度器实现模块
│   │       ├── queue_ops.py         # 入队/出队/Redis 连接管理
│   │       ├── task_execution.py    # 发送链路与保护逻辑
│   │       └── task_lifecycle.py    # 任务生命周期状态更新
│   └── utils/                       # 通用工具
│
├── frontend/                        # 前端代码根目录
│   └── h5/                          # 唯一 H5 前端（Vue3 + TS + Vite）
│       ├── src/
│       ├── public/
│       ├── package.json
│       └── vite.config.ts
│
├── logs/                            # 日志目录（运行时生成）
└── uploads/                         # 上传目录（运行时生成）
```

## 模块边界

- `backend/`：所有 Python 业务代码（API、Bot、调度、数据库）  
- `frontend/h5/`：唯一 H5 控制台前端实现  
- 根目录：仅保留入口脚本、部署配置、文档与运行产物目录  

## 启动路径约定

- 后端入口：`main.py`（导入 `h5_backend.api:app`）
- API 模块：`backend/h5_backend/api.py`
- 前端构建产物目录：`frontend/h5/dist`
- 媒体上传目录：`uploads/task_media`

## 数据流

```
用户(H5/Bot)
  -> backend/h5_backend/api.py
  -> backend/database (PostgreSQL/Redis)
  -> backend/scheduler + backend/bot
  -> Telegram
```
