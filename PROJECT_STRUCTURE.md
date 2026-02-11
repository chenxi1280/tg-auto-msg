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
│   ├── config/                      # 配置模块
│   ├── database/                    # ORM 与会话管理
│   ├── h5_backend/                  # FastAPI API + SPA 托管
│   ├── scheduler/                   # 调度器与执行队列
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
