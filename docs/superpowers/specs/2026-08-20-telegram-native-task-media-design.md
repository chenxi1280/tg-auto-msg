# Telegram 原生任务媒体设计 V2

日期：2026-08-21
状态：本地实现与自动化完成；生产 schema/V1 数据迁移和 Telegram 真实 E2E 尚未执行

## 1. 已确定的产品合同

### 1.1 内容类型

本期只实现 `media_copy`：把 Telegram 中已有的一份媒体复用为一条新的任务消息。

每个任务最多包含一份媒体，类型限定为：

- 一张图片 `photo`；
- 一个视频 `video`；
- 一个动图 `animation`。

新消息不显示“转发自”，不继承来源消息的 caption，使用任务自己的 caption。产品界面统一称“复用 Telegram 媒体发送”，不再使用含糊的“上传文件”或“转发文件”。

### 1.2 明确不支持

- Telegram 原生整条消息转发 `message_forward`；
- 普通文档、压缩包、PDF、音频、语音、圆形视频；
- 贴纸；
- 多图、相册或混合媒体组；
- 从 H5、本地磁盘或对象存储上传媒体；
- 将媒体下载到应用服务器后再上传；
- 媒体来源失效后降级为纯文本或其他文件；
- 在 Userbot 发送的任务消息上附加 Telegram Bot 按钮。

如果以后需要保留原发送者、原 caption 和“转发自”标记，必须新增独立的 `message_forward` 内容类型。如果以后需要普通文件，必须新增独立的 `document_copy` 类型。这两类能力不混入本期 `media_copy`。

### 1.3 发送身份与按钮

当前任务发送身份是绑定的 Telegram 用户账号，即 Userbot。Telethon 的 `buttons` 只对 Bot 登录生效，因此 V2 任务合同为：

- `sender_kind=user_account`；
- 可以发送纯文本或“一份媒体 + caption”；
- 任务启用前必须至少有文本或一份有效媒体；空任务只能作为 `enabled=false` 草稿存在；
- 不支持 inline button / reply keyboard；
- 创建、编辑和启用 V2 任务时，只要 `buttons` 非空就返回 `TASK_BUTTONS_UNSUPPORTED_FOR_USER_ACCOUNT`；
- 运行时不得先尝试按钮再静默重发无按钮消息。

未来若引入 `sender_kind=bot`，按钮能力必须在独立设计中覆盖 Bot 入群、频道管理员权限、目标可见性和发送身份，不能复用 Userbot 的目标访问事实。

## 2. 核心目标

媒体字节只存在于 Telegram。应用服务器只处理 Telegram 消息对象和定位元数据：

```text
用户使用执行账号把媒体发给系统 Bot
                    ↓
执行账号回读同一条 Bot 对话消息
                    ↓
执行账号用 message.media 原生复制到自己的 Saved Messages
                    ↓
数据库只保存 account_id + Saved Messages message_id
                    ↓
每次执行从 Saved Messages 回读并复用 media 发送到目标
```

全过程禁止 `download_media`、完整 `bytes`、`BytesIO`、`bytearray`、临时文件、上传目录和对象存储。

Saved Messages 是 Telegram 侧的长期媒体保险库，不是本项目服务器存储。创建时多一次 Telegram 内部复制，用于避免用户清理 Bot 对话或 Bot 对话自动删除后破坏所有定时任务。

## 3. 为什么不长期引用 Bot 对话原消息

Bot 对话只作为媒体采集入口，不作为任务的长期来源：

- 用户可能删除 Bot 对话消息；
- Bot 对话可能配置自动删除；
- 运行时需要持续解析系统 Bot peer；
- entity cache 丢失时，单独的 peer ID 不足以稳定构造 InputPeer；
- 同一个长期任务不应依赖管理对话的保留策略。

创建阶段由执行账号读取 Bot 对话后，立即执行：

```python
saved_message = await account_client.send_file(
    "me",
    file=source_message.media,
    caption=None,
    buttons=None,
)
```

这个调用复用 Telegram 已有媒体对象，不经过服务器文件下载。任务只持久化 `saved_message.id`。原 Bot 消息之后被删除不影响任务；Saved Messages 中的规范来源被删除时，任务明确失败。

## 4. 多账号操作合同

媒体必须由任务的执行账号本人发送到系统 Bot。

### 4.1 前置条件

一个账号可以设置媒体，当且仅当：

- `Account.is_active=true`；
- 账号已授权且不需要重新登录；
- 当前 Bot 操作者 Telegram UID 等于 `Account.tg_user_id`；
- 该 Telegram UID 已绑定到任务所属系统用户；
- 执行账号能够读取与系统 Bot 的私聊。

### 4.2 Owner 管理多个账号

Owner 在账号 A 的 Bot 会话或 H5 中为账号 B 点击“设置媒体”时，系统不得进入一个注定失败的等待状态。系统返回：

```text
MEDIA_CAPTURE_ACCOUNT_SWITCH_REQUIRED
请切换到执行账号 B，在该账号中打开系统 Bot 并继续本次媒体设置。
```

H5 创建捕获会话后返回一个只包含不透明 `capture_token` 的 Bot deep link。用户必须使用账号 B 打开该链接。Bot 收到 token 后重新验证 actor UID、系统用户、任务、账号、revision 和过期时间；使用账号 A 打开时明确拒绝。

账号 B 从未打开系统 Bot 时，先使用账号 B 发送 `/start`。Bot 根据已存在的 `Account.tg_user_id -> Account.user_id` 关系进入 account-scoped 模式，不新建另一个系统用户，也不改变任务所有权。

## 5. 可持久媒体捕获会话

FSM 只负责展示，捕获事实必须持久化，不能只存在进程内存。

新增 `task_media_capture_sessions`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `capture_id` | UUID | 主键 |
| `token_hash` | string | 只保存 deep-link token 的 SHA-256 哈希 |
| `task_id` | UUID | 目标任务；新建流程必须先持久化 `enabled=false` 任务 |
| `user_id` | bigint | 任务所属系统用户 |
| `account_id` | UUID | 冻结的执行账号 |
| `actor_tg_user_id` | bigint | 允许提交媒体的 Telegram UID |
| `expected_task_revision` | bigint | 捕获开始时的任务版本 |
| `prompt_message_id` | bigint | Bot 媒体提示消息 ID |
| `source_message_id` | bigint nullable | 验证后的账号视角 Bot 对话消息 ID |
| `saved_message_id` | bigint nullable | 成功复制到 Saved Messages 后的消息 ID |
| `state` | string | `waiting/processing/completed/expired/cancelled/failed` |
| `error_code` | string nullable | 明确失败原因 |
| `expires_at` | timestamp | 过期时间 |
| `consumed_at` | timestamp nullable | 一次性消费时间 |
| `created_at/updated_at` | timestamp | 审计时间 |

配置常量：

```text
MEDIA_CAPTURE_TTL_SECONDS=600
```

约束：

- 同一任务最多一个 `waiting` 或 `processing` 捕获会话；
- 新建捕获会话会显式取消旧的等待会话；
- token 使用 192-bit CSPRNG 生成并编码为 base64url，原文只返回一次；
- 数据库、日志和状态接口只保存或输出 token hash，不回传 token 原文；
- token 只用于定位 capture，不代表授权，仍需验证 actor、任务、账号、revision 和 TTL；
- capture 只能从 `waiting` 原子切换到 `processing` 一次；
- 进程重启后仍可读取状态；
- 过期任务返回 `MEDIA_CAPTURE_EXPIRED`，不能继续写入。

## 6. Bot 媒体捕获流程

1. 新建流程的任务必须已经以 `enabled=false` 持久化；首次媒体设置完成前不得启用。编辑已有任务时继续由 revision CAS 防止覆盖并发修改。
2. 创建 capture，冻结 `task_id/account_id/actor_tg_user_id/expected_task_revision`。
3. Bot 发送带 capture 标识的媒体提示，并保存 `prompt_message_id`。
4. 用户必须回复这条提示消息，并发送一份媒体。
5. Bot 校验 reply anchor、capture token、actor UID、TTL 和 capture state。
6. 使用选定执行账号解析系统 Bot：优先使用配置中的 Bot username，回读后校验 Telegram Bot ID 与运行时 Bot ID 一致。
7. 执行账号按 Bot update 的消息 ID 精确回读该条消息；读不到就返回 `MEDIA_SOURCE_CORRELATION_FAILED`，不得扫描“最近一条”猜测。
8. 比较 Bot 视角与执行账号视角的 photo/document ID、类型、发送方向和 reply anchor。
9. 执行账号用 `source_message.media` 原生复制到 Saved Messages，不携带来源 caption 和按钮。
10. 立即从 Saved Messages 回读复制结果，校验媒体存在且类型一致。
11. 使用任务 revision 做 CAS，写入规范来源并递增 revision。
12. capture 标记 `completed`；任何失败均记录明确 error code，不写半成品媒体引用。

如果 Saved Messages 复制成功但任务 CAS 冲突，capture 标记 `failed/TASK_REVISION_CONFLICT`，日志记录孤立 `saved_message_id` 供审计；不得自动删除 Telegram 消息，也不得覆盖新任务配置。

## 7. 媒体类型判定

类型判定使用 Telethon 明确类型：

1. `MessageMediaPhoto` -> `photo`；
2. `MessageMediaDocument` 包含 `DocumentAttributeAnimated` -> `animation`；
3. `MessageMediaDocument` 包含 `DocumentAttributeVideo`，且 `round_message=false` -> `video`；
4. 其他全部拒绝。

规则：

- `animation` 优先于 `video`；
- `grouped_id` 非空时拒绝整组，不取第一项；
- 图片“作为文件发送”属于普通 document，本期拒绝；
- 不使用 `hasattr(attr, "video")` 或 `hasattr(attr, "animated")`；
- Bot 视角和执行账号视角分类结果必须一致。

## 8. 任务数据模型

`scheduled_message_tasks` 新增：

| 字段 | 类型 | 说明 |
|---|---|---|
| `content_contract_version` | smallint | 旧任务为 `1`，V2 为 `2` |
| `revision` | bigint | 每次用户可见配置变化递增 |
| `media_type` | string | `none/photo/video/animation` |
| `media_source_account_id` | UUID nullable | Saved Messages 所属账号 |
| `media_source_message_id` | bigint nullable | Saved Messages 消息 ID |
| `media_source_meta` | JSON nullable | 文件名、MIME、Telegram 声明大小、宽高、时长 |
| `media_source_state` | string | `none/valid/migration_pending/invalid` |
| `media_source_error_code` | string nullable | 最近失效或迁移原因 |
| `media_source_verified_at` | timestamp nullable | 最近成功回读时间 |

不保存 `media_source_peer_id`：V2 规范来源固定为执行账号自己的 Saved Messages，运行时使用 `InputPeerSelf` / `"me"`，不依赖 entity cache 或其他账号的 access hash。

数据库约束：

- `media_type=none` 时，来源账号和消息 ID 必须为空，state 必须为 `none`；
- `media_type!=none` 时，来源账号和消息 ID 必须齐全；
- `media_source_account_id=task.account_id`；
- V2 `media_type` 不允许 `sticker`；
- V2 `buttons` 必须为空；
- `valid` 必须有 `verified_at`；
- 元数据不能包含媒体内容、缩略图二进制、session、Bot token、access hash 或 file reference。

切换任务执行账号时，在同一 CAS 事务内：

- 清空媒体来源；
- 设置 `media_type=none`、`media_source_state=none`；
- 取消未完成 capture；
- revision 加一；
- 返回“执行账号已变更，请重新设置媒体”。

## 9. API 合同

### 9.1 删除文件上传

V2 删除：

```text
POST /api/tasks/upload-media
```

后端不再接收媒体 `UploadFile`，H5 不再发送媒体 multipart body。

### 9.2 任务编辑

任务更新必须携带 `expected_revision`。CAS 不匹配返回 HTTP 409 `TASK_REVISION_CONFLICT`。

普通任务更新 payload 不接受任何 Telegram 来源定位字段：

- 字段缺失表示保留当前媒体；
- 只有专用媒体清除接口才能清除媒体；
- 变更 `account_id` 时强制清除媒体，不受“字段缺失”规则影响；
- V2 `buttons` 非空时返回明确错误。

### 9.3 媒体接口

```text
POST   /api/tasks/{task_id}/media-captures
GET    /api/tasks/{task_id}/media-captures/{capture_id}
DELETE /api/tasks/{task_id}/media
```

创建 capture 返回：

```json
{
  "capture_id": "...",
  "state": "waiting",
  "expires_at": "...",
  "bot_deep_link": "https://t.me/<bot>?start=media_<opaque_token>",
  "required_tg_user_id": "masked"
}
```

当新任务还没有文本或媒体时，H5 先创建 `enabled=false` 草稿并停留在编辑页；媒体捕获完成后，用户再显式启用。执行账号或 caption 有未保存修改时，不允许按数据库旧值创建 capture。

媒体删除要求 `expected_revision`，只删除数据库引用，不删除 Saved Messages 原消息。删除成功后 revision 加一。

任务详情只返回展示摘要，不返回 Bot token、session、access hash 或 file reference。

## 10. 运行时发送链路

每次执行冻结任务快照，然后：

1. 校验 `content_contract_version=2`。
2. 校验 `buttons` 为空。
3. 校验媒体来源 state 为 `valid`，来源账号等于执行账号。
4. 使用执行账号调用 `get_messages("me", ids=media_source_message_id)`。
5. 校验消息存在、媒体存在、类型与任务一致。
6. 从最新消息对象取得 `source_message.media`，避免使用过期 file reference。
7. 生成最终 caption 和 entities。
8. 用 `send_file(target, file=source_message.media, caption=..., buttons=None)` 发送。
9. 记录目标消息 ID 和 typed result。

禁止：

- 本地路径和旧原始字符串 fallback；
- `download_media`；
- 文件字节缓冲；
- 来源失败后发送纯文本；
- 按钮失败后重发无按钮消息；
- 切换账号、切换来源或猜测其他消息。

## 11. Caption 合同

为所有账号使用确定性的保守产品限制，不依赖 Premium 状态：

```text
MAX_MEDIA_CAPTION_UTF16=1024
MAX_TEXT_MESSAGE_UTF16=4096
```

长度按 Telegram entity 使用的 UTF-16 code units 计算。

- 有媒体时，`text` 是 caption，最终 caption 必须不超过 1024；
- 无媒体时，最终文本不得超过 4096；
- 从无媒体切换到媒体时重新校验已有文本；
- 隐形变化必须在最终校验前生成；
- 超限返回 `MEDIA_CAPTION_TOO_LONG`，不得截断；
- 来源消息 caption 永不自动拼接。

## 12. 明确错误与目标权限

创建阶段：

```text
MEDIA_CAPTURE_ACCOUNT_SWITCH_REQUIRED
MEDIA_CAPTURE_ACCOUNT_UNAVAILABLE
MEDIA_CAPTURE_PROCESSING
MEDIA_CAPTURE_EXPIRED
MEDIA_CAPTURE_ALREADY_CONSUMED
MEDIA_CAPTURE_REPLY_REQUIRED
MEDIA_SOURCE_CORRELATION_FAILED
MEDIA_SOURCE_TYPE_UNSUPPORTED
MEDIA_SOURCE_COPY_FAILED
TASK_REVISION_CONFLICT
TASK_BUTTONS_UNSUPPORTED_FOR_USER_ACCOUNT
```

执行阶段：

```text
MEDIA_SOURCE_UNAVAILABLE
MEDIA_SOURCE_ACCOUNT_MISMATCH
MEDIA_SOURCE_TYPE_CHANGED
MEDIA_CAPTION_TOO_LONG
TARGET_PHOTO_FORBIDDEN
TARGET_VIDEO_FORBIDDEN
TARGET_ANIMATION_FORBIDDEN
TARGET_MEDIA_FORBIDDEN
```

映射 Telegram 错误时保留具体类型：

- `ChatSendPhotosForbiddenError` -> `TARGET_PHOTO_FORBIDDEN`；
- `ChatSendVideosForbiddenError` -> `TARGET_VIDEO_FORBIDDEN`；
- `ChatSendGifsForbiddenError` -> `TARGET_ANIMATION_FORBIDDEN`；
- `ChatSendMediaForbiddenError` -> `TARGET_MEDIA_FORBIDDEN`。

媒体权限错误进入现有目标问题事实链，由目标级策略决定暂停该目标；不得把媒体权限错误改写成账号离线或任务整体成功。

## 13. 并发与幂等

任务更新统一使用：

```sql
UPDATE scheduled_message_tasks
SET ..., revision = revision + 1
WHERE task_id = :task_id
  AND revision = :expected_revision
  AND account_id = :expected_account_id;
```

影响行数不是 1 就返回冲突。

其他规则：

- capture 状态通过条件更新完成 `waiting -> processing`；
- 同一 Bot update / source message ID 重复投递只产生一个处理结果；
- capture 完成后重复请求返回原完成结果，不再次复制媒体；
- 执行中使用不可变任务快照；编辑只影响下一次运行；
- 保存成功消息与任务 CAS 冲突时保留孤立消息审计，不自动删除；
- 所有 SQL 使用参数化查询。

## 14. 迁移合同

完整迁移状态机、批次、阻断项、回滚与切换门槛见配套文档：

[Telegram 原生任务媒体 V2 迁移设计](./2026-08-20-telegram-native-task-media-migration.md)

主合同保持：schema 变更与 Telegram 回读分离；旧任务先只读清点，再按账号串行验证和 CAS 迁移；sticker、本地路径、未知引用、非空 buttons 和账号不匹配均阻断自动升级；达到零启用 V1 媒体任务、零启用 buttons 任务、E2E 与回滚演练通过后，才能删除旧上传和本地路径兼容。

## 15. 可观测性与隐私

结构化日志只记录：

- `task_id/capture_id/account_id`；
- Bot source message ID 和 Saved Messages message ID；
- 目标 peer；
- 媒体类型；
- revision；
- capture/source/send 状态；
- typed error code。

不得记录：

- 媒体内容、缩略图或完整 caption；
- session、Bot token、验证码或密码；
- access hash、file reference；
- 完整手机号或客户数据。

进程指标至少包含 capture 成功/失败/过期数量、Saved Messages 回读失败数量、三类媒体发送结果、迁移 backlog 和孤立规范消息数量。

## 16. 验收标准

### 16.1 自动化

- photo、video、animation 分类和发送成功；
- animation 优先于普通 video；
- sticker、document、audio、voice、round video、album 全部拒绝；
- Userbot 任务配置 buttons 时创建/编辑即失败；
- 不存在按钮失败后无按钮重发；
- capture 必须回复准确 prompt，过期、重复和错误账号均失败；
- 同一 source update 只复制一次；
- Bot 消息删除后，Saved Messages 规范来源仍可发送；
- Saved Messages 来源删除后明确失败，不降级；
- 切换执行账号原子清除媒体和 capture；
- CAS 冲突不覆盖新任务；
- H5 普通编辑遗漏媒体字段时保留媒体；
- H5 不存在文件 input 和媒体 multipart API；
- 媒体链路不调用 `download_media`，不创建文件字节缓冲；
- caption 使用 UTF-16 计数并在最终变化后校验；
- 四类媒体目标权限错误保持独立；
- V1 迁移失败不会被写成成功或阻断其他任务。

### 16.2 Telegram 真实验收

使用一个授权测试账号：

1. 从同一账号回复 capture prompt，分别发送图片、视频、动图；
2. 账号成功回读 Bot 消息并原生复制到 Saved Messages；
3. 数据库只出现定位和元数据，无本地路径和文件内容；
4. 删除 Bot 原消息后，三类任务仍可发送；
5. 目标收到新媒体消息，无“转发自”，caption 正确；
6. 配置按钮在保存前明确失败；
7. 删除 Saved Messages 规范来源后任务明确失败；
8. 错误账号打开 capture deep link 时明确拒绝；
9. 目标禁止图片、视频、GIF 时得到对应 typed error；
10. 上传目录、临时目录和进程内存不存在随媒体大小增长的搬运链路。

代码、CI、容器健康和数据库引用都不能替代 Telegram 来源回读、Saved Messages 复制和真实目标发送证据。

## 17. 实施顺序

1. [x] 增加 revision、V2 字段、capture 表和迁移状态；
2. [x] 删除新流程的 buttons 能力并移除运行时静默按钮降级；
3. [x] 实现统一媒体分类、capture CAS 和同账号 Bot 回读；
4. [x] 实现 Telegram 原生复制到 Saved Messages；
5. [x] 调度链路切换为 Saved Messages 每次回读与媒体复用；
6. [x] H5 删除文件上传，补 capture deep link、状态展示和专用媒体删除；
7. [x] 提供默认只读清点和显式按账号串行批量迁移命令；生产清点和迁移尚未执行；
8. [ ] 完成单账号 canary 和 Telegram 真实 E2E；自动化已完成；
9. [ ] 达到切换门槛后删除旧字段和 V1 本地路径兼容。

当前可核验状态：

```text
design_complete=true
implementation_complete=true
automated_tests=passed
new_server_upload_path_removed=true
legacy_v1_local_path_compat=true
production_schema_migration=not_executed
production_v1_data_migration=not_executed
telegram_e2e=unproven
```
