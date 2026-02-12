# 项目结构说明

```
tg-auto-msg/
├── main.py
├── reinit_db.py
├── start.sh
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
├── sql/
│   ├── init.sql
│   ├── init_dev.sql
│   └── migrations/
├── backend/
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── account/
│   │   ├── circuit/
│   │   ├── client_runtime/
│   │   ├── handlers/
│   │   │   ├── core/
│   │   │   ├── account/
│   │   │   └── task/
│   │   ├── proxy/
│   │   ├── resources/
│   │   ├── safety/
│   │   ├── session/
│   │   ├── state/
│   │   └── ui/
│   ├── config/
│   │   └── core/
│   ├── database/
│   │   ├── init_db.py
│   │   ├── runtime/
│   │   └── schema/
│   ├── h5_backend/
│   │   ├── __init__.py
│   │   ├── app/
│   │   ├── dependencies.py
│   │   ├── routers/
│   │   └── services/
│   │       ├── account/
│   │       ├── auth/
│   │       ├── login/
│   │       ├── proxy/
│   │       └── task/
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── core/
│   └── utils/
│       └── security/
├── frontend/
│   └── h5/
├── logs/
├── uploads/
├── BOT_ARCHITECTURE.md
├── BOT_HANDLERS_ARCHITECTURE.md
├── DATABASE_ARCHITECTURE.md
├── H5_BACKEND_ARCHITECTURE.md
└── SCHEDULER_ARCHITECTURE.md
```

## 启动路径

- 后端入口：`main.py`
- FastAPI App：`backend.h5_backend.app.factory:app`
- 前端构建产物：`frontend/h5/dist`

## 约束

1. 业务代码全部在 `backend/*` 子目录中分域管理，不再使用平铺兼容层文件。
2. 代码目录下不放架构说明文档，所有架构文档统一放项目根目录。
3. 新功能优先放入对应子域目录（例如 `bot/account`、`h5_backend/services/task`、`scheduler/core`）。
