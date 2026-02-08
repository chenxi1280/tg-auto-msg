# 部署指南

本文档提供详细的部署指南，包括开发环境、生产环境和 Docker 部署。

## 📋 前置要求

### 必须安装
- Python 3.10+
- PostgreSQL 13+
- Redis 7+
- (可选) Docker & Docker Compose

### Telegram 配置
1. 访问 https://my.telegram.org 获取 `API_ID` 和 `API_HASH`
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
python -m database.init_db
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
    API_ID="your_api_id",
    API_HASH="your_api_hash",
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
Environment="API_ID=your_api_id"
Environment="API_HASH=your_api_hash"
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

## 🐳 Docker 部署

### 1. 配置环境变量
```bash
cp .env.example .env
nano .env
```

### 2. 启动服务
```bash
docker-compose up -d
```

### 3. 查看日志
```bash
docker-compose logs -f app
```

### 4. 停止服务
```bash
docker-compose down
```

### 5. 进入容器
```bash
docker-compose exec app bash
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

### 1. 拉取最新代码
```bash
git pull origin main
```

### 2. 更新依赖
```bash
pip install -r requirements.txt --upgrade
```

### 3. 数据库迁移（如有）
```bash
python -m database.migrate
```

### 4. 重启服务
```bash
# Supervisor
sudo supervisorctl restart tg-auto-msg

# Systemd
sudo systemctl restart tg-auto-msg

# Docker
docker-compose restart app
```

## 📞 技术支持

如遇到问题，请：
1. 查看日志文件
2. 检查配置文件
3. 查阅 GitHub Issues
4. 提交 Issue 寻求帮助
