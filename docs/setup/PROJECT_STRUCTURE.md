# 项目结构说明

```
tg-auto-msg/
├── main.py
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── scripts/
│   ├── README.md
│   ├── reinit_db.py
│   └── start.sh
├── docker/
│   ├── README.md
│   ├── Dockerfile.backend
│   └── Dockerfile.frontend
├── docs/
│   ├── README.md
│   ├── architecture/
│   ├── deployment/
│   ├── setup/
│   └── *.md
├── deploy/
│   ├── nginx/
│   ├── systemd/
│   └── *.sh
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
├── logs/          # 运行日志（已被 git 忽略）
└── uploads/       # 上传文件（已被 git 忽略）
```

## 启动路径

- 后端入口：`main.py`
- FastAPI App：`backend.h5_backend.app.factory:app`
- 前端构建产物：`frontend/h5/dist`

## 目录职责

- `docs/`
  - 文档总入口，包含架构、部署、初始化、历史资料。
- `deploy/`
  - 发布、回滚、巡检与服务器运行资产，细节见 `deploy/README.md`。
- `scripts/`
  - 本地维护脚本与辅助启动脚本。
- `docker/`
  - Docker 构建文件，`docker-compose.yml` 作为统一运行入口。
- `sql/`
  - 数据库基线脚本与增量迁移，不把 SQL 资产散落到业务代码目录。
- `backend/`
  - 后端业务代码，按 bot / database / h5_backend / scheduler 等域拆分。
- `frontend/h5/`
  - H5 前端应用源码。

## 约束

1. 业务代码全部在 `backend/*` 子目录中分域管理，不再使用平铺兼容层文件。
2. 说明文档统一放在 `docs/` 下，不再散落在项目根目录。
3. 新功能优先放入对应子域目录（例如 `bot/account`、`h5_backend/services/task`、`scheduler/core`）。
4. 运维脚本统一放在 `deploy/`，数据库脚本统一放在 `sql/`。
