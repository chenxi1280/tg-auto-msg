# 快速开始指南

本指南将帮助你在 10 分钟内启动 Telegram 定时消息推送管理系统。

## 🚀 3 步快速启动

### 步骤 1：准备配置

1. **获取 Telegram 凭证**
   - 访问 https://my.telegram.org 获取 `TG_API_ID` 和 `TG_API_HASH`
   - 与 @BotFather 对话创建 Bot，获取 `BOT_TOKEN`

2. **准备数据库和 Redis**
   ```bash
   # PostgreSQL
   createdb tg_auto_msg

   # Redis
   brew services start redis  # macOS
   # 或
   sudo systemctl start redis  # Linux
   ```

3. **配置环境变量**
   ```bash
   cd /Users/xida/PycharmProjects/tg-auto-msg
   cp .env.example .env
   nano .env  # 填写你的配置
   ```

### 步骤 2：安装和启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 初始化数据库
python -m backend.database.init_db

# 3. 启动应用
python main.py
```

首次启动时，程序会提示你输入验证码（发送到你的手机号）。

### 步骤 3：开始使用

1. 在 Telegram 中搜索你的 Bot（使用 Bot Token）
2. 发送 `/start` 开始使用
3. 点击「📢 进入任务列表」
4. 点击「➕ 添加任务」创建第一个任务

## 📝 创建第一个任务

### 基础任务配置

1. **任务标题**：给任务起个名字，如「每日问候」
2. **重复间隔**：选择发送频率（如 60 分钟）
3. **群组 ID**：输入目标群组/频道 ID

### 添加消息内容

1. 点击「📝 文本」输入消息内容（支持 HTML）
2. 点击「🖼️ 媒体」上传图片/视频（可选）
3. 点击「🔘 按钮」添加跳转按钮（可选）

### 设置时间控制

1. 点击「⏰ 重复」调整发送间隔
2. 点击「🌅 时段」设置每天发送时段（可选）
3. 点击「📅 开始/结束」设置日期范围（可选）

### 启用任务

1. 点击「🟢 启用」开关
2. 任务开始自动运行！

## 💡 常见任务示例

### 示例 1：每小时发送一次广告
- 重复间隔：60 分钟
- 时段：全天
- 内容：文本 + 按钮（跳转官网）

### 示例 2：工作日 9-18 点每 2 小时提醒
- 重复间隔：120 分钟
- 时段：09:00 - 18:00
- 内容：纯文本

### 示例 3：活动期间每日推送
- 重复间隔：1440 分钟（24 小时）
- 开始日期：2024-01-01 00:00
- 结束日期：2024-01-31 23:59
- 内容：图片 + 文字

## 🌐 使用 H5 高级编辑

在 Bot 任务设置页点击「🌐 H5 高级编辑」，可以：

- 📝 富文本编辑器
- 🖼️ 媒体素材管理
- 🔘 可视化按钮编排
- 📊 批量操作多个任务
- 📋 查看详细发送日志

## 🔧 故障排查

### 问题 1：Bot 无响应
- 检查 `BOT_TOKEN` 是否正确
- 查看控制台日志

### 问题 2：Userbot 登录失败
- 确认手机号格式正确（带国家代码）
- 检查验证码是否输入正确

### 问题 3：任务不执行
- 确认任务已启用（绿色开关）
- 检查时间设置是否正确
- 查看调度器日志

### 问题 4：消息发送失败
- 检查 Userbot 是否有群组权限
- 确认群组/频道 ID 正确
- 查看任务执行日志

## 📚 下一步

- 📖 阅读 [README.md](README.md) 了解完整功能
- 📖 阅读 [DEPLOYMENT.md](DEPLOYMENT.md) 了解生产部署
- 📖 阅读 [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) 了解项目结构

## 🆘 获取帮助

- 📝 查看日志文件：`logs/app_YYYY-MM-DD.log`
- 💬 提交 Issue：https://github.com/your-repo/issues
- 📚 阅读文档：https://docs.your-domain.com

---

**祝你使用愉快！** 🎉
