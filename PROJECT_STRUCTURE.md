# 项目结构说明

```
tg-auto-msg/
├── main.py                      # 主入口文件
├── requirements.txt             # Python 依赖
├── .env.example                 # 环境变量示例
├── .gitignore                   # Git 忽略配置
├── Dockerfile                   # Docker 构建文件
├── docker-compose.yml           # Docker Compose 配置
├── start.sh                     # 快速启动脚本
│
├── config/                      # 配置模块
│   ├── __init__.py
│   └── settings.py              # 应用配置
│
├── database/                    # 数据库模块
│   ├── __init__.py
│   ├── models.py                # 数据库模型
│   ├── session.py               # 数据库会话管理
│   ├── init_db.py               # 数据库初始化脚本
│   └── schema.sql               # SQL 建表脚本
│
├── bot/                         # Bot 模块
│   ├── __init__.py
│   ├── client.py                # Telegram 客户端初始化
│   ├── fsm.py                   # FSM 状态机
│   ├── keyboards.py             # 键盘定义
│   ├── messages.py              # 消息文本模板
│   └── handlers/                # 消息处理器
│       ├── __init__.py
│       └── main.py              # 主处理器（命令/回调/消息）
│
├── scheduler/                   # 调度器模块
│   ├── __init__.py
│   └── worker.py                # 调度 Worker
│
├── h5_backend/                  # H5 后端 API（FastAPI）
│   ├── __init__.py
│   ├── api.py                   # FastAPI 服务
│   └── routers/                 # API 路由
│       └── auth.py              # 认证路由
│
├── h5-frontend/                 # H5 前端（唯一前端实现）
│   ├── src/
│   ├── public/
│   ├── package.json
│   └── vite.config.ts
│
├── logs/                        # 日志目录（运行时生成）
│
└── *.session                    # Telegram 会话文件（运行时生成）
```

## 模块说明

### main.py
主入口文件，负责：
- 初始化日志
- 初始化数据库
- 初始化 Userbot
- 启动调度器
- 运行 Bot

### config/
配置管理模块
- `settings.py`: 使用 Pydantic Settings 管理所有配置项

### database/
数据库模块
- `models.py`: SQLAlchemy ORM 模型定义
- `session.py`: 异步数据库会话管理
- `init_db.py`: 数据库初始化脚本
- `schema.sql`: 原生 SQL 建表脚本

### bot/
Bot 模块
- `client.py`: Telegram Bot + Userbot 客户端初始化
- `fsm.py`: FSM 状态机（用于输入流程）
- `keyboards.py`: InlineKeyboard 定义
- `messages.py`: 消息文本模板
- `handlers/main.py`: 消息处理器（命令、回调按钮、普通消息）

### scheduler/
调度器模块
- `worker.py`: 定时扫描和发送任务的 Worker

### h5_backend/
H5 后端 API
- `api.py`: FastAPI 服务（RESTful API + SPA 静态托管）
- `routers/auth.py`: 系统登录认证接口

### h5-frontend/
H5 前端（唯一前端）
- Vue 3 + TypeScript + Vite
- 统一承载登录、账号、资源、代理、任务页面

## 数据流

```
用户 → Bot (Telethon)
    ↓
数据库 (PostgreSQL)
    ↓
Scheduler Worker
    ↓
Userbot (Telethon)
    ↓
Telegram 群组/频道
```

## H5 控制台

```
用户 → H5 页面 (h5-frontend)
    ↓
API 接口 (h5_backend/api.py)
    ↓
数据库 (PostgreSQL)
```

## 并发控制

- **Redis 分布式锁**: 防止任务重复执行
- **异步 I/O**: 所有数据库操作都是异步的
- **连接池**: PostgreSQL 和 Redis 都使用连接池

## 日志

日志文件存储在 `logs/` 目录：
- `app_YYYY-MM-DD.log`: 应用日志（按日期轮转）

## 会话文件

Telegram 会话文件：
- `bot_session.session`: Bot 会话
- `userbot_session.session`: Userbot 会话

**注意**: 这些文件包含敏感信息，不要提交到 Git！

## 启动流程

1. 加载配置 (`config/settings.py`)
2. 初始化日志
3. 初始化数据库 (`database/init_db.py`)
4. 初始化 Userbot (`bot/client.py`)
5. 初始化调度器 (`scheduler/worker.py`)
6. 启动 Bot (`main.py`)
