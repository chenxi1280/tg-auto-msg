# Telegram 原生任务媒体 V2 迁移设计

日期：2026-08-21
状态：迁移结构、只读清点和按账号串行迁移命令已实现；生产迁移尚未执行

本文是 [Telegram 原生任务媒体设计 V2](./2026-08-20-telegram-native-task-media-design.md) 的配套迁移合同。

维护入口：

```bash
# 默认只读，也可显式写 inventory
python scripts/task_media_v2_migration.py inventory

# 明确指定账号后，按该账号串行迁移一批
python scripts/task_media_v2_migration.py migrate --account-id <account_id> --limit 50
```

## 1. 总体约束

- 数据库 schema 变更与 Telegram 回读不能放在同一个同步迁移事务中。
- 迁移失败保持原任务事实，不得写成成功、猜测来源或删除媒体。
- Telegram 验证不下载文件，不删除旧字段或 Telegram 消息。
- 旧字段保留到切换门槛全部通过，历史文件清理由独立审计和授权处理。

## 2. 阶段 A：扩展结构

- 增加 revision、V2 媒体字段、capture 表和迁移状态。
- 保留旧 `media_file_id`、旧 enum/check 和旧读路径。
- 所有现有任务标记 `content_contract_version=1`。
- 新任务写 V2；过渡期同时写可推导的 `tgmsg://account/message` 兼容值，支持应用回滚。
- 扩展迁移只改 schema，不连接 Telegram。

## 3. 阶段 B：只读清点

按类别输出精确数量和 task IDs：

- 可解析的 `tgmsg://account/message`；
- `sticker`；
- 本地路径；
- 未知字符串或 file id；
- 非空 buttons；
- 启用中的 V1 媒体任务；
- media account 与 task account 不一致。

只读清点不修改任务、不连接 Telegram，并生成带时间和当前部署 SHA 的迁移清单。

## 4. 阶段 C：分批 Telegram 验证

配置：

```text
MEDIA_MIGRATION_BATCH_SIZE=50
MEDIA_MIGRATION_ACCOUNT_CONCURRENCY=1
```

规则：

- 同一账号串行回读 Saved Messages。
- 只自动迁移可解析的 `tgmsg://` 引用。
- 回读成功、类型一致、buttons 为空后，用 revision CAS 写入 V2 字段。
- 成功设置 `media_source_state=valid` 和 `media_source_verified_at`。
- 失败设置 `media_source_state=invalid` 和 typed error，但保留 V1 数据。
- 单条失败不阻断后续记录，账号授权失效时停止该账号余下批次。
- 已写为 `invalid` 的阻断记录不再占用下一批计划名额；结果分别返回 `remaining` 总 backlog 和 `blocked` 阻断数，避免旧失败记录长期饿死后续可迁移任务。
- 每批提交独立事务并记录计划数量、成功、失败、冲突和剩余数量。

## 5. 阶段 D：阻断项处理

以下任务不能自动升级：

- sticker；
- 本地路径或未知引用；
- Saved Messages 来源不存在或类型改变；
- buttons 非空；
- 执行账号不匹配；
- revision 在验证期间发生变化。

阻断任务保持 V1，进入可定位清单。系统不得静默删除按钮、替换媒体、自动停用或修改任务目标。用户或管理员必须明确选择替换媒体、删除按钮或停用任务。

V1 任务运行时也必须移除“按钮失败后重发无按钮消息”的静默路径。带按钮任务触发时返回 `TASK_BUTTONS_UNSUPPORTED_FOR_USER_ACCOUNT`，保留失败事实并通知处理；不能为了维持表面成功继续发送缺少按钮的消息。

## 6. 阶段 E：逐任务切换

- 新建和编辑只产生 V2 数据。
- V1 与 V2 运行时按 `content_contract_version` 显式分流，不做字符串猜测。
- 每个任务只有在来源验证、buttons 为空和 CAS 成功后切换为 V2。
- 切换后保留旧 `media_file_id` 兼容值直到观察期结束。
- 回滚应用只能读取仍被双写的兼容值，回滚演练必须覆盖媒体发送。

## 7. 删除兼容门槛

必须同时满足：

- 已启用 V1 媒体任务数量为 0；
- 已启用 buttons 任务数量为 0；
- V2 自动化与 Telegram E2E 通过；
- 观察期内本地媒体文件读取次数为 0；
- 迁移 backlog 和未解释冲突为 0；
- 应用与数据库回滚演练通过；
- 已生成旧路径和历史文件引用审计报告。

满足后才删除旧读取、上传 API、贴纸分支、本地路径 fallback、静默按钮降级、旧 enum/check 和旧字段。删除历史文件仍需单独授权。

## 8. 验收证据

- schema migration 成功且没有 Telegram 网络调用；
- 清点数量可以用只读 SQL 独立复算；
- 每批迁移结果与数据库状态一致；
- 失败和 CAS 冲突未覆盖任务；
- V1/V2 分流没有跨版本猜测；
- canary 的 Saved Messages 回读和目标发送真实成功；
- 切换门槛逐项有 persisted readback，而不是只看 CI 或容器健康。
