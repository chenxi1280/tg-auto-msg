# Bot Architecture

## 目录分层

- `backend/bot/account/`
  - 账号生命周期、绑定、健康状态、账号选择。
- `backend/bot/client_runtime/`
  - 系统级 bot/userbot 客户端启动与会话持久化、二维码登录流程。
- `backend/bot/resources/`
  - Dialog 资源同步、查询、InputPeer 构造。
- `backend/bot/proxy/`
  - 代理 CRUD、分配、健康检查。
- `backend/bot/circuit/`
  - Flood/Session 熔断、恢复、通知。
- `backend/bot/session/`
  - 登录会话状态管理（内存/Redis）。
- `backend/bot/safety/`
  - 发送限流与内容去重。
- `backend/bot/state/`
  - FSM 状态与会话状态存储。
- `backend/bot/ui/`
  - Bot 文案和键盘构造。
- `backend/bot/handlers/`
  - 对话处理逻辑（见 `BOT_HANDLERS_ARCHITECTURE.md`）。

## 约束

1. `backend/bot/` 根目录只保留 `__init__.py`，不再放平铺业务实现。
2. 新增逻辑必须进入对应子域目录，禁止回到根目录堆积。
3. 业务模块之间通过显式导入协作，不使用 wildcard 跨域导出。
