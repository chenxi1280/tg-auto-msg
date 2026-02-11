# H5 Backend Architecture

## Goals

- Keep API behavior unchanged while reducing coupling.
- Split monolithic `api.py` into domain routers.
- Centralize shared permission checks and task payload logic.

## Current Layout

- `backend/h5_backend/api.py`
  - App composition only: lifespan, router registration, SPA static mount.
- `backend/h5_backend/dependencies.py`
  - Shared ownership checks: task/account/proxy permission validation.
- `backend/h5_backend/services/task_helpers.py`
  - Pure helper functions: task payload normalization, media type conversion, upload limits.
- `backend/h5_backend/services/task_payload.py`
  - Task payload rules: target normalization, field validation, next-run initialization, update field application.
- `backend/h5_backend/services/task_serializers.py`
  - Task response serialization helpers (list/detail/log payloads).
- `backend/h5_backend/services/task_service.py`
  - Task domain orchestration: list/detail/create/update/delete/batch/log/media upload.
- `backend/h5_backend/services/account_service.py`
  - Account domain logic: account list, sync resources, bind code, enable/disable/delete.
- `backend/h5_backend/services/login_service.py`
  - Login domain logic: QR login lifecycle, status polling, bind action.
- `backend/h5_backend/services/proxy_service.py`
  - Proxy domain logic: list/add/check/delete/assign/unassign.
- `backend/h5_backend/services/auth_service.py`
  - Auth domain logic: password hash, JWT issue/verify, register/login/current-user resolve.
- `backend/h5_backend/routers/auth.py`
  - Thin route adapter for auth service.
- `backend/h5_backend/routers/login.py`
  - Thin route adapter for login service.
- `backend/h5_backend/routers/accounts.py`
  - Thin route adapter for account service.
- `backend/h5_backend/routers/tasks.py`
  - Thin route adapter for task service.
- `backend/h5_backend/routers/proxies.py`
  - Thin route adapter for proxy service.

## Design Rules

1. `api.py` must not contain domain endpoint logic.
2. Cross-domain checks live in `dependencies.py`, not duplicated in routers.
3. Domain business logic lives under `services/*_service.py`.
4. Pure utility/helper logic stays in `services/task_helpers.py` and `services/task_payload.py`.
5. Routers keep endpoint paths stable to avoid frontend/Bot breakage.
6. Router layer should only do parameter binding, auth injection, and response envelope.
