# Telegram 定时消息推送管理系统

一个基于 Telegram 的定时消息推送服务，支持在群组/频道内配置定时消息任务，由 Userbot 自动执行发送。

## ✨ 功能特性

### 🤖 Bot 界面
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
- **Vue 3 + TypeScript + Vite** - 统一 H5 控制台（目录：`h5-frontend/`）
- **Element Plus** - UI 组件库

## 📦 安装部署

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
API_ID=12345678                    # 从 https://my.telegram.org 获取
API_HASH=your_api_hash_here        # 从 https://my.telegram.org 获取
BOT_TOKEN=your_bot_token_here      # 从 @BotFather 获取
USERBOT_PHONE=+8613800000000       # 你的手机号

# 数据库配置
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/tg_auto_msg
REDIS_URL=redis://localhost:6379/0

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

# 初始化表结构
python -m database.init_db
```

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

首次运行会要求输入验证码，按照提示完成 Userbot 登录。

### 7. 配置 H5 域名
编辑 `bot/messages.py` 中的 `H5_BASE_URL`：
```python
H5_BASE_URL = "https://your-domain.com"
```

构建前端（生产环境）：
```bash
cd h5-frontend
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

### 方式三：使用 Docker
```bash
# 构建镜像
docker build -t tg-auto-msg .

# 运行容器
docker run -d \
  --name tg-auto-msg \
  -v $(pwd):/app \
  -e API_ID=12345678 \
  -e API_HASH=your_api_hash \
  -e BOT_TOKEN=your_bot_token \
  -e DATABASE_URL=postgresql+asyncpg://postgres:password@db:5432/tg_auto_msg \
  -e REDIS_URL=redis://redis:6379/0 \
  tg-auto-msg
```

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
