# Bot Handlers Architecture

## 分层

- `backend/bot/handlers/core/`
  - 事件注册入口、命令分发、回调分发、消息分发、共用 helper。
- `backend/bot/handlers/account/`
  - 账号绑定、账号列表、资源同步、代理展示。
- `backend/bot/handlers/task/`
  - 任务列表/设置/编辑、目标选择（多选/搜索/分页）、查询与 UI 组件。

## 设计规则

1. `core/main.py` 仅做事件绑定与调度，不承载业务细节。
2. 账号相关逻辑只放 `account/`。
3. 任务相关逻辑只放 `task/`。
4. 查询函数与 UI 组装函数保持纯函数风格，不做外部副作用。
