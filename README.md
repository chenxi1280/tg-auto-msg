# Telegram 定时消息推送管理系统

一个基于 Telegram 的定时消息推送服务，支持在群组/频道内配置定时消息任务，由 Userbot 自动执行发送。

## ✨ 功能特性

### 🤖 Bot 界面
- 📢 公告卡片（由 admin 统一配置正文和链接，Bot 内展示 TG 原生预览）
- 📢 任务列表管理（查看所有任务）
- ⚙️ 任务快速配置（启停、删除、基础设置）
- 🔘 FSM 流程式编辑（文本、媒体、按钮）
- 🌐 一键跳转 H5 控制台

### 🌐 H5 控制台
- 📝 富文本编辑器（支持 HTML）
- 🖼️ 媒体素材管理（图片、视频、贴纸）
- 🔘 可视化按钮编排（拖拽布局）
- 📊 批量操作（批量启用/停用/修改）
- 📋 发送日志查看
- 📅 高级时间控制

### ⏰ 调度功能
- 🔄 固定间隔重复发送
- 🌅 每日小时段限制发送
- 📆 开始/终止日期控制
- 🗑️ 自动删除上一条消息
- 📌 自动置顶新消息
- 🚨 失败自动重试与禁用

## 🏗️ 技术架构

### 后端
- **Python 3.10+** - 核心语言
- **Telethon** - Telegram Bot + Userbot 客户端
- **PostgreSQL** - 数据存储
- **SQLAlchemy** - ORM 框架（异步）
- **Redis** - 分布式锁 + 缓存
- **APScheduler** - 任务调度引擎
- **FastAPI** - H5 API 服务

### 前端
- **Vue 3 + TypeScript + Vite** - 统一 H5 控制台（目录：`frontend/h5/`）
- **Element Plus** - UI 组件库

## 📦 安装部署

## 📚 文档导航

- 文档索引：`docs/README.md`
- 快速上手：`docs/setup/QUICKSTART.md`
- Bot 用户手册：`docs/setup/BOT_USAGE.md`
- Bot 管理员说明：`docs/setup/BOT_ADMIN_NOTICE.md`
- 项目结构：`docs/setup/PROJECT_STRUCTURE.md`
- 数据库迁移：`docs/setup/MIGRATIONS.md`
- 生产部署：`docs/deployment/DEPLOYMENT.md`
- 线上运行目录：`docs/deployment/PRODUCTION_RUNTIME.md`
- 架构文档：`docs/architecture/`
- 发布与分支：`docs/BRANCHING_AND_RELEASES.md`
- 仓库整理约定：`docs/WORKSPACE_CONVENTIONS.md`

## 🗂️ 目录约定

- `backend/`：Python 后端业务代码
- `frontend/h5/`：H5 前端工程
- `sql/`：基线脚本与增量迁移
- `scripts/`：本地维护与辅助启动脚本
- `docker/`：Docker 构建文件
- `deploy/`：发布、回滚、巡检、Nginx、systemd 资产
- `docs/`：全部说明文档

根目录只保留高频入口与运行配置，不再新增零散说明文档。

### 1. 克隆项目
```bash
git clone <repository-url>
cd tg-auto-msg
```

### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 配置环境变量
复制 `.env.example` 为 `.env` 并填写配置：

```env
# Telegram 配置
TG_API_ID=12345678                 # 从 https://my.telegram.org 获取
TG_API_HASH=your_api_hash_here     # 从 https://my.telegram.org 获取
BOT_TOKEN=your_bot_token_here      # 从 @BotFather 获取
USERBOT_PHONE=+8613800000000       # 你的手机号

# 数据库配置
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/tg_auto_msg
REDIS_URL=redis://localhost:6379/0

# 安全配置
JWT_SECRET_KEY=change_me
ADMIN_API_TOKEN=change_me_admin_token
ADMIN_BOOTSTRAP_USERNAME=admin
ADMIN_BOOTSTRAP_PASSWORD=change_me_admin_password
ADMIN_BOOTSTRAP_DISPLAY_NAME=超级管理员

# 应用配置
LOG_LEVEL=INFO
TIMEZONE=Asia/Shanghai

# 调度配置
WORKER_INTERVAL=60
MAX_FAILURE_COUNT=5
```

### 4. 初始化数据库
```bash
# 确保已创建数据库
createdb tg_auto_msg

# 初始化表结构（会自动执行 runtime migrations）
python -m backend.database.init_db
```

后台超管初始化说明：
- 新版后台不再依赖固定默认账号密码。
- 应用启动后会自动检查当前 `PROVINCE_CODE` 下是否存在 `super_admin`。
- 如果不存在，并且 `.env` 中配置了 `ADMIN_BOOTSTRAP_USERNAME` / `ADMIN_BOOTSTRAP_PASSWORD`，系统会自动写入首个超管账号。
- 首个超管账号首次登录后会被要求修改密码。
- 如需手动补账号，仍可使用 `python scripts/init_admin_account.py <username> <password> [display_name]`。

SQL 文件结构：
- `sql/init.sql`：幂等全量建表脚本
- `sql/init_dev.sql`：本地开发初始化脚本
- `sql/migrations/*.sql`：运行时兼容迁移脚本

### 5. 启动 Redis
```bash
# macOS
brew services start redis

# Linux
sudo systemctl start redis

# Docker
docker run -d -p 6379:6379 redis:latest
```

### 6. 首次启动（登录 Userbot）
```bash
python main.py
```

首次运行后，通过 H5 扫码完成 Userbot 绑定与登录。

### 7. 配置 H5 域名
在 `.env` 中设置：
```env
H5_BASE_URL=https://your-domain.com
```

构建前端（生产环境）：
```bash
cd frontend/h5
npm install
npm run build
```

## 🚀 运行

### 方式一：直接运行（开发环境）
```bash
python main.py
```

### 方式二：使用 Supervisor（生产环境）
创建配置文件 `/etc/supervisor/conf.d/tg-auto-msg.conf`：
```ini
[program:tg-auto-msg]
command=/path/to/python /path/to/main.py
directory=/path/to/tg-auto-msg
user=your_user
autostart=true
autorestart=true
stdout_logfile=/var/log/tg-auto-msg/out.log
stderr_logfile=/var/log/tg-auto-msg/err.log
```

启动：
```bash
sudo supervisorctl update
sudo supervisorctl start tg-auto-msg
```

### 方式三：使用 Docker Compose（推荐上线，前后端分离）
```bash
# 1) 首次准备 shared 环境文件
cp .env.docker.example /data/tgmsg/shared/.env
# 编辑 /data/tgmsg/shared/.env，至少填写以下必填项：
# TG_API_ID TG_API_HASH BOT_TOKEN JWT_SECRET_KEY
# DATABASE_URL REDIS_URL
# ADMIN_BOOTSTRAP_USERNAME ADMIN_BOOTSTRAP_PASSWORD
# DATABASE_URL 推荐使用共享业务子账号，例如：
# postgresql+asyncpg://app_user:shared_password@postgres:5432/tgmsg

# 2) 本地统一发版（推荐）
bash deploy/release.sh --host 47.250.167.174
```

线上推荐额外启用前端自愈巡检：
```bash
# 由 deploy/server-install-release.sh 自动安装
systemctl list-timers | grep tgmsg
```

生产结构说明：
- `frontend`：独立 Nginx 容器，负责静态资源与 SPA 路由，并反向代理 `/api` 到 `app`
- `app`：FastAPI API 容器，只在 Docker 内网暴露 `8000`
- `postgres` / `redis`：由独立的 `infra-compose` 项目维护，通过 `infra_default` 外部网络提供

标准目录结构：
- `/data/tgmsg/releases/<release_id>`：每次发版的只读源码目录
- `/data/tgmsg/current`：当前正在运行的版本软链
- `/data/tgmsg/shared/.env`：线上环境变量
- `/data/tgmsg/logs`：后端应用日志
- `/data/tgmsg/uploads`：业务上传目录
- `/data/tgmsg/nginx-logs`：Nginx 日志

访问入口：
- `http://your-host/`：前端首页
- `http://your-host/api/...`：通过 Nginx 反代到后端 API

常用命令：
```bash
# 查看线上容器状态
ssh root@your-host "cd /data/tgmsg/current && docker compose --env-file /data/tgmsg/shared/.env ps"

# 回滚到指定版本
ssh root@your-host "bash /data/tgmsg/current/deploy/rollback.sh <release-id>"

# 查看巡检日志
ssh root@your-host "tail -f /data/tgmsg/shared/logs/service-health.log"
```

说明：
- 生产环境建议设置 `SERVE_FRONTEND=false`，由 Nginx 提供前端。
- `DATABASE_URL` 和 `REDIS_URL` 应指向 `infra_default` 网络里的 `postgres` / `redis` 服务。
- `DATABASE_URL` 使用共享业务子账号，发布时会自动确保 `tgmsg` 数据库存在。
- 本地开发仍可设置 `SERVE_FRONTEND=true`，继续由 FastAPI 挂载前端构建产物。
- 标准发版脚本使用 `git archive`，不会再把 `.DS_Store`、`._*` 等本地垃圾文件带到线上。
- 推荐尽快把默认发布分支统一到 `main`。详细规范见 `docs/BRANCHING_AND_RELEASES.md`。
- 当前线上真实目录、挂载和兼容说明以 `docs/deployment/PRODUCTION_RUNTIME.md` 为准。

## 📊 数据库结构

### scheduled_message_tasks 表
| 字段 | 类型 | 说明 |
|------|------|------|
| task_id | UUID | 任务唯一标识（主键）|
| user_id | bigint | 归属用户 ID |
| chat_id | bigint | 群组/频道 ID |
| title | string | 显示名 |
| enabled | boolean | 是否启用 |
| repeat_interval_min | int | 重复间隔（分钟）|
| day_start_hour | int | 每日发送起始小时 |
| day_end_hour | int | 每日发送结束小时 |
| start_at | bigint | 开始时间（Unix 时间戳）|
| end_at | bigint | 终止时间（Unix 时间戳）|
| text | text | HTML 文本 |
| media_type | enum | 媒体类型 |
| media_file_id | string | Telegram file_id |
| buttons | json | 按钮数组 |
| delete_previous | boolean | 删除上一条 |
| pin_message | boolean | 是否置顶 |
| last_sent_message_id | int | 上次发送消息 ID |
| next_run_at | bigint | 下次执行时间 |
| failure_count | int | 失败次数 |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

### task_logs 表
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 日志 ID（主键）|
| task_id | string | 任务 ID |
| send_at | timestamp | 发送时间 |
| result | string | 执行结果（success/failed）|
| error_code | string | 错误代码 |
| error_message | text | 错误信息 |
| message_id | int | 消息 ID |

## 🎯 使用指南

### Bot 基础操作

1. **启动 Bot**：给 Bot 发送 `/start` 命令
2. **查看任务**：点击「📢 进入任务列表」
3. **创建任务**：点击「➕ 添加任务」
4. **快速设置**：在设置页点击对应按钮修改
5. **高级编辑**：点击「🌐 H5 高级编辑」进入控制台

### H5 控制台操作

1. **富文本编辑**：在文本框中输入 HTML 格式内容
2. **媒体上传**：点击「📤 上传媒体」选择图片/视频
3. **按钮编排**：点击「+ 添加按钮行」添加按钮
4. **批量操作**：在任务列表页选择多个任务进行批量操作
5. **查看日志**：滚动到底部查看发送历史

### 管理员卡密后台（非用户 H5）

说明：
- 用户端 H5 只负责“卡密激活”，不提供卡密生成和管理。
- 新版管理员后台使用“后台账号 + 密码 + JWT”登录，不再使用固定 `X-Admin-Token` 作为后台主入口。
- 访问地址：`http://localhost:8000/admin/login`
- 首次部署时，如果当前省份不存在 `super_admin`，系统会读取 `.env` 中的 `ADMIN_BOOTSTRAP_USERNAME` / `ADMIN_BOOTSTRAP_PASSWORD` 自动创建首个超管账号。
- 登录成功后进入统一后台。
- `super_admin` 除了省级总代、多级代理、充值审批、卡密批次、统一价格外，还拥有旧 admin 系统能力：
  - 购买入口配置
  - Bot 公告栏配置
  - 开发者应用池
  - 系统代理池
  - 旧卡密规格与卡密总览
  - 用户、TG 账号、历史授权与统一审计
- `master_agent` / `sub_agent` 只保留分销链路相关菜单，看不到系统级配置模块。

示例：
```bash
# 启动服务后打开后台登录页
open http://localhost:8000/admin/login

# 如需手动补建超管账号（可选）
python scripts/init_admin_account.py admin StrongPass123 超级管理员
```

说明：
- `ADMIN_API_TOKEN` 仅用于旧版管理员接口兼容，不再作为新版分销后台的登录方式。
- 新版后台推荐完全使用 `/admin/login` 入口。

### 时间设置示例

**每天 9:00-18:00 每小时发送：**
- 重复间隔：60 分钟
- 时段：09:00 - 18:00
- 开始/结束日期：留空

**跨天时段（22:00-02:00）：**
- 重复间隔：120 分钟
- 时段：22:00 - 02:00

**活动期间发送：**
- 重复间隔：30 分钟
- 时段：全天
- 开始日期：2024-01-01 00:00
- 结束日期：2024-01-07 23:59

## 🔒 安全说明

1. **JWT 认证**：H5 API 使用 Bearer Token 认证
2. **用户隔离**：任务/账号/代理接口按系统用户权限校验
3. **分布式锁**：使用 Redis 锁防止任务重复执行
4. **权限检测**：自动检测置顶/删除权限，失败时记录日志

## 🐛 常见问题

### 1. Userbot 无法登录
- 检查手机号格式（带国家代码）
- 确保没有被 Telegram 封禁

### 2. 消息发送失败
- 检查 Userbot 是否有群组/频道权限
- 查看日志中的错误信息
- 检查网络连接

### 3. H5 页面无法访问
- 检查 FastAPI 服务是否启动
- 检查域名配置和 Nginx 反向代理

### 4. 任务不执行
- 检查任务是否启用
- 检查时间设置是否正确
- 查看 Worker 日志

## 📝 API 文档

启动后访问 `http://localhost:8000/docs` 查看 FastAPI 自动生成的 API 文档。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

## 🙏 致谢

- [Telethon](https://github.com/LonamiWebs/Telethon) - Python Telegram 客户端
- [FastAPI](https://fastapi.tiangolo.com/) - 现代 Web 框架
- [SQLAlchemy](https://www.sqlalchemy.org/) - Python SQL 工具包
