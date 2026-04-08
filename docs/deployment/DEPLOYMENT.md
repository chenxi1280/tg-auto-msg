# 部署指南

本文档提供详细的部署指南，包括开发环境、生产环境和 Docker 部署。

> 注意：当前线上标准发布入口已经切换为 GitHub Actions + SSH 与 `deploy/release.sh`。
> 如果你是在维护 `47.250.167.174` 的生产环境，请优先参考
> `docs/GITHUB_ACTIONS_SSH_DEPLOY.md`。另外，线上 `PostgreSQL/Redis` 已建议拆分到独立的
> `infra-compose` 项目，不再跟随 `tgmsg` 一起发版。

## 📋 前置要求

### 必须安装
- Python 3.10+
- PostgreSQL 13+
- Redis 7+
- (可选) Docker & Docker Compose

### Telegram 配置
1. 访问 https://my.telegram.org 获取 `TG_API_ID` 和 `TG_API_HASH`
2. 与 @BotFather 对话创建 Bot，获取 `BOT_TOKEN`

## 🔧 开发环境部署

### 1. 克隆项目
```bash
git clone <repository-url>
cd tg-auto-msg
```

### 2. 创建虚拟环境
```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate  # Windows
```

### 3. 安装依赖
```bash
pip install -r requirements.txt
```

### 4. 配置环境变量
```bash
cp .env.example .env
nano .env  # 编辑配置
```

### 5. 创建数据库
```bash
createdb tg_auto_msg
```

### 6. 初始化数据库
```bash
python -m backend.database.init_db
```

### 7. 启动 Redis
```bash
# macOS
brew services start redis

# Linux (Ubuntu/Debian)
sudo systemctl start redis

# Docker
docker run -d -p 6379:6379 redis:7-alpine
```

### 8. 首次启动
```bash
python main.py
```

本地开发也可以使用：

```bash
bash scripts/start.sh
```

首次启动会要求输入验证码，按照提示完成 Userbot 登录。

### 9. 使用 Bot
1. 在 Telegram 中搜索你的 Bot
2. 发送 `/start` 开始使用

## 🚀 生产环境部署

### 方式一：使用 Supervisor

#### 1. 安装 Supervisor
```bash
# Ubuntu/Debian
sudo apt-get install supervisor

# CentOS/RHEL
sudo yum install supervisor
```

#### 2. 创建配置文件
创建 `/etc/supervisor/conf.d/tg-auto-msg.conf`：
```ini
[program:tg-auto-msg]
command=/path/to/venv/bin/python /path/to/tg-auto-msg/main.py
directory=/path/to/tg-auto-msg
user=your_user
autostart=true
autorestart=true
startretries=3
stderr_logfile=/var/log/tg-auto-msg/err.log
stdout_logfile=/var/log/tg-auto-msg/out.log
environment=
    TG_API_ID="your_api_id",
    TG_API_HASH="your_api_hash",
    BOT_TOKEN="your_bot_token",
    DATABASE_URL="postgresql+asyncpg://user:password@localhost:5432/tg_auto_msg",
    REDIS_URL="redis://localhost:6379/0"
```

#### 3. 创建日志目录
```bash
sudo mkdir -p /var/log/tg-auto-msg
sudo chown your_user:your_user /var/log/tg-auto-msg
```

#### 4. 启动服务
```bash
sudo supervisorctl update
sudo supervisorctl start tg-auto-msg
```

#### 5. 查看状态
```bash
sudo supervisorctl status tg-auto-msg
sudo tail -f /var/log/tg-auto-msg/out.log
```

### 方式二：使用 Systemd

#### 1. 创建 Service 文件
创建 `/etc/systemd/system/tg-auto-msg.service`：
```ini
[Unit]
Description=Telegram Auto Message Service
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/tg-auto-msg
Environment="PATH=/path/to/venv/bin"
Environment="TG_API_ID=your_api_id"
Environment="TG_API_HASH=your_api_hash"
Environment="BOT_TOKEN=your_bot_token"
Environment="DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/tg_auto_msg"
Environment="REDIS_URL=redis://localhost:6379/0"
ExecStart=/path/to/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### 2. 启动服务
```bash
sudo systemctl daemon-reload
sudo systemctl enable tg-auto-msg
sudo systemctl start tg-auto-msg
```

#### 3. 查看状态
```bash
sudo systemctl status tg-auto-msg
sudo journalctl -u tg-auto-msg -f
```

## 🐳 Docker 部署（推荐）

### 1. 服务器目录规范
```bash
mkdir -p /data/tgmsg/{releases,shared,incoming,backups}
mkdir -p /data/tgmsg/shared/{postgres,redis,logs,uploads,nginx-logs}
```

### 2. 配置线上环境变量
```bash
cp .env.docker.example /data/tgmsg/shared/.env
nano /data/tgmsg/shared/.env
```

至少补齐下面几项，否则新版后台不会自动创建首个超管：

```env
PROVINCE_CODE=guangdong
ADMIN_BOOTSTRAP_USERNAME=admin
ADMIN_BOOTSTRAP_PASSWORD=your_strong_password
ADMIN_BOOTSTRAP_DISPLAY_NAME=超级管理员
```

### 3. 本地标准发版
```bash
bash deploy/release.sh --host 47.250.167.174
```

### 4. 服务器手工发布备用入口
```bash
# 假设 release 包已经上传到服务器
mkdir -p /data/tgmsg/releases/<release_id>
tar -xzf /data/tgmsg/incoming/<release_id>.tar.gz -C /data/tgmsg/releases/<release_id>
bash /data/tgmsg/releases/<release_id>/deploy/server-install-release.sh \
  --base-dir /data/tgmsg \
  --release-dir /data/tgmsg/releases/<release_id> \
  --release-id <release_id>
```

### 5. 回滚
```bash
bash /data/tgmsg/current/deploy/rollback.sh <release_id>
```

### 6. 目录说明
- `/data/tgmsg/releases/<release_id>`：每次发版的只读源码
- `/data/tgmsg/current`：当前生效版本软链
- `/data/tgmsg/shared/.env`：线上环境变量
- `/data/tgmsg/shared/postgres`：数据库数据
- `/data/tgmsg/shared/redis`：Redis 数据
- `/data/tgmsg/shared/logs`：应用日志
- `/data/tgmsg/shared/uploads`：上传目录
- `/data/tgmsg/shared/nginx-logs`：Nginx 日志

### 7. 前端自愈巡检
```bash
# server-install-release.sh 会自动安装
systemctl list-timers | grep tgmsg
tail -f /data/tgmsg/shared/logs/frontend-watchdog.log
```

### 8. 线上常用命令
```bash
# 当前版本
readlink -f /data/tgmsg/current

# 容器状态
cd /data/tgmsg/current
docker compose --env-file /data/tgmsg/shared/.env ps

# 查看后端日志
docker compose --env-file /data/tgmsg/shared/.env logs -f app
```

## 🌐 Nginx 反向代理（H5）

配置 Nginx 反向代理到 H5 API：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

配置 HTTPS（使用 Let's Encrypt）：

```bash
sudo apt-get install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

## 🔒 安全建议

### 1. 环境变量
- 不要将 `.env` 文件提交到 Git
- 使用强密码
- 定期更换密钥

### 2. 数据库
- 创建专用数据库用户，限制权限
- 启用 SSL 连接
- 定期备份

### 3. Redis
- 设置密码
- 限制访问 IP
- 不要暴露到公网

### 4. Bot Token
- 不要泄露 Bot Token
- 定期更换
- 使用 @BotFather 禁用旧 Token

### 5. Userbot
- 不要在公共服务器上使用
- 定期检查登录状态
- 如有异常立即改密

## 📊 监控建议

### 1. 日志监控
- 使用 `loguru` 配置日志轮转
- 监控错误日志
- 设置告警

### 2. 数据库监控
- 监控连接数
- 监控慢查询
- 定期 VACUUM

### 3. Redis 监控
- 监控内存使用
- 监控连接数
- 检查慢命令

### 4. 应用监控
- 监控任务执行次数
- 监控失败率
- 监控响应时间

## 🔄 备份策略

### 数据库备份
```bash
# 每日备份
0 2 * * * pg_dump -U postgres tg_auto_msg | gzip > /backup/tg_auto_msg_$(date +\%Y\%m\%d).sql.gz

# 保留最近 30 天
0 3 * * * find /backup -name "tg_auto_msg_*.sql.gz" -mtime +30 -delete
```

### Redis 备份
Redis 默认启用 RDB 和 AOF，无需额外配置。

## 🐛 故障排查

### 1. Bot 无响应
- 检查 Bot Token 是否正确
- 检查网络连接
- 查看应用日志

### 2. 任务不执行
- 检查任务是否启用
- 检查时间设置
- 查看调度器日志

### 3. 消息发送失败
- 检查 Userbot 权限
- 检查群组/频道 ID
- 查看任务日志

### 4. H5 页面无法访问
- 检查 FastAPI 服务
- 检查 Nginx 配置
- 检查防火墙规则

## 📝 更新部署

### 1. 创建发布分支或合并到主干
```bash
git checkout main
git pull origin main
```

### 2. 本地统一发版
```bash
bash deploy/release.sh --host 47.250.167.174
```

说明：
- 新方案不再推荐直接 `git pull` 到线上源码目录。
- 生产发布统一走 `deploy/release.sh`，服务切换统一走 `current` 软链。
- 若仓库暂未从 `master` 迁移到 `main`，可短期兼容，但建议尽快统一。
sudo systemctl restart tg-auto-msg

# Docker
docker compose restart app
```

## 📞 技术支持

如遇到问题，请：
1. 查看日志文件
2. 检查配置文件
3. 查阅 GitHub Issues
4. 提交 Issue 寻求帮助
