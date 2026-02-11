# Bot Handlers Architecture

## Goals

- Keep Telegram command/callback behavior unchanged.
- Reduce `main.py` size and coupling.
- Separate domain flows from event registration and dispatch.

## Current Layout

- `backend/bot/handlers/main.py`
  - Event registration only (`/start`, `/bind`, short commands, callback, message FSM).
- `backend/bot/handlers/command_handlers.py`
  - Command domain handlers (`/start`, `/bind`, short command parser/dispatcher).
- `backend/bot/handlers/task_management.py`
  - Task list/settings/create/toggle/delete/open-H5 entry points.
- `backend/bot/handlers/task_target_selection.py`
  - Task account selection + target multi-select + search/filter/paging + selector FSM context handling.
- `backend/bot/handlers/task_editing.py`
  - Task content/time/edit toggles + FSM input handlers for text/media/buttons/time.
- `backend/bot/handlers/account_management.py`
  - Account binding/listing/resource-sync/proxy display flows.
- `backend/bot/handlers/callback_dispatch.py`
  - Callback action routing table (`action -> handler`) and argument parsing.
- `backend/bot/handlers/message_dispatch.py`
  - FSM input state routing table (`state -> handler`).
- `backend/bot/handlers/helpers.py`
  - Pure utility functions (URL validation, markdown escaping, target normalization, button parsing, display formatters).
- `backend/bot/handlers/selector_context.py`
  - Selector context read/write helpers on top of FSM storage.
- `backend/bot/handlers/task_queries.py`
  - Shared DB ownership/lookup query helpers.
- `backend/bot/handlers/task_selector_ui.py`
  - Account/target picker keyboard builders.

## Design Rules

1. `main.py` should stay as event registration and orchestration only.
2. Business flows should live in domain modules (`task_management.py`, `task_target_selection.py`, `task_editing.py`, `account_management.py`).
3. Command parsing/execution should live in `command_handlers.py`, not inline in `main.py`.
4. Action/state routing tables should live in dispatch modules, not inline `if/elif`.
5. Query helpers must be isolated from event side effects.
6. UI builder code should not access DB directly.
7. Any new task/account flow should be added to domain modules, not re-expanded in `main.py`.
