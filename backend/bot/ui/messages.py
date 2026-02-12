"""
Bot 消息文本模板
"""
from backend.config.core.settings import settings

# ============ 任务列表页 ============

TASK_LIST_HEADER = """📢 **定时消息推送管理系统**

设置在群组中每隔几分钟/小时重复发送的消息。

"""

TASK_EMPTY = """📭 暂无任务

点击下方「➕ 添加任务」开始创建。"""

# ============ 任务设置页 ============

TASK_SETTINGS_TEMPLATE = """⚙️ **任务设置**

📌 任务标题: {title}

📊 **状态**
• 启用状态: {enabled_status}
• 重复间隔: 每 {interval} 分钟

👤 **执行账号与目标**
• 执行账号: {account_display}
• 目标聊天: {target_display}

⏰ **时间控制**
• 发送时段: {time_range}
• 开始日期: {start_date}
• 结束日期: {end_date}

📝 **消息内容**
• 文本内容: {text_status}
• 媒体类型: {media_status}
• 按钮: {buttons_status}

⚙️ **执行选项**
• 删除上一条: {delete_status}
• 置顶消息: {pin_status}

💡 *快速操作：修改上方任意选项后返回即可生效*
💻 *高级编辑：点击下方「🌐 H5 高级编辑」进入Web控制台进行富文本、媒体管理等高级配置*
"""

# ============ 编辑页面 ============

EDIT_TEXT_PROMPT = """📝 **修改文本内容**

请输入新的文本内容（支持 HTML 格式，最多 4096 字符）：

当前内容:
```
{text}
```
"""

EDIT_MEDIA_PROMPT = """🖼️ **修改媒体内容**

请发送一张图片、视频、贴纸或动图作为新的媒体内容。

当前媒体: {current_media}
"""

EDIT_BUTTONS_PROMPT = """🔘 **修改按钮内容**

请按以下格式输入按钮（每行一个按钮，多个按钮用 && 分隔）：

格式示例：
```
官网 - https://example.com
电报群 - https://t.me/xxx && 粉丝群 - https://t.me/yyy
联系客服 - https://t.me/support
```

当前按钮:
```
{current_buttons}
```
"""

EDIT_START_AT_PROMPT = """📅 **设置开始时间**

请输入开始时间（格式: YYYY-MM-DD HH:mm，如: 2024-01-01 09:00）：
"""
EDIT_END_AT_PROMPT = """📆 **设置结束时间**

请输入结束时间（格式: YYYY-MM-DD HH:mm，如: 2024-12-31 23:59）：
"""

# ============ 错误消息 ============

ERROR_TEXT_TOO_LONG = "❌ 文本内容过长，请控制在 4096 字符以内。"
ERROR_INVALID_MEDIA = "❌ 不支持的媒体类型，请发送图片、视频、贴纸或动图。"
ERROR_INVALID_BUTTON_FORMAT = "❌ 按钮格式错误，请按「文字 - URL」格式输入。"
ERROR_INVALID_TIME_FORMAT = "❌ 时间格式错误，请使用「YYYY-MM-DD HH:mm」格式。"
ERROR_END_BEFORE_START = "❌ 结束时间不能早于开始时间。"
ERROR_TIME_IN_PAST = "❌ 时间不能早于当前时间。"

# ============ 成功消息 ============

SUCCESS_TEXT_UPDATED = "✅ 文本内容已更新！"
SUCCESS_MEDIA_UPDATED = "✅ 媒体内容已更新！"
SUCCESS_BUTTONS_UPDATED = "✅ 按钮内容已更新！"
SUCCESS_INTERVAL_UPDATED = "✅ 重复间隔已更新为 {interval} 分钟！"
SUCCESS_TIME_RANGE_UPDATED = "✅ 发送时段已更新为 {start}:00 - {end}:00！"
SUCCESS_START_AT_UPDATED = "✅ 开始时间已更新！"
SUCCESS_END_AT_UPDATED = "✅ 结束时间已更新！"
SUCCESS_TASK_ENABLED = "✅ 任务已启用！"
SUCCESS_TASK_DISABLED = "✅ 任务已禁用！"
SUCCESS_DELETE_PREVIOUS_TOGGLED = "✅ 删除上一条设置已更新！"
SUCCESS_PIN_TOGGLED = "✅ 置顶设置已更新！"
SUCCESS_TASK_CREATED = "✅ 任务已创建！"
SUCCESS_TASK_DELETED = "✅ 任务已删除！"

# ============ 选择提示 ============

SELECT_START_HOUR = "🌅 请选择每日发送起始小时："
SELECT_END_HOUR = "🌆 请选择每日发送结束小时："
SELECT_INTERVAL = "⏰ 请选择重复间隔："

# ============ 确认消息 ============

CONFIRM_DELETE = """🗑️ **确认删除任务**

确定要删除任务「{title}」吗？

此操作无法撤销！"""

# ============ 消息状态 ============

STATUS_ENABLED = "🟢 已启用"
STATUS_DISABLED = "🔴 已禁用"
STATUS_YES = "✅ 是"
STATUS_NO = "❌ 否"
STATUS_HAS = "✅ 已设置"
STATUS_NOT_SET = "❌ 未设置"

# ============ H5 跳转相关 ============

OPEN_H5_BUTTON = "🌐 H5 高级编辑"
# H5 基础 URL（从配置读取，默认本地开发地址）
H5_BASE_URL = (settings.h5_base_url or "http://localhost:8000").rstrip("/")

# ============ 账号管理页 ============

BIND_SUCCESS = """✅ 账号绑定成功！

👤 用户名: @{username}
🆔 账号ID: `{account_id}`

你现在可以在 Bot 里直接管理该账号。"""

ERROR_INVALID_BIND_CODE = "❌ 绑定失败：绑定码无效、已过期，或账号归属校验未通过。"

ACCOUNTS_LIST = """👥 **已绑定账号**（{count}）

{accounts_text}

请选择要操作的账号，或使用下方快捷功能。"""
