# Batch 1 Delivery Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent cross-tenant task execution and make every target delivery outcome durable, explicit, and safe under timeout.

**Architecture:** Add a typed batch API, execution ownership recheck, and a `task_delivery_attempts` checkpoint service. Refactor task execution into short database phases around Telegram network calls, then persist exact aggregate results in `task_logs`.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy async, PostgreSQL, Telethon, unittest/pytest.

---

### Task 1: Restrict Batch Task Updates and Recheck Account Ownership

**Files:**
- Modify: `backend/h5_backend/routers/tasks.py:1-90`
- Modify: `backend/h5_backend/services/task/service.py:350-382`
- Modify: `backend/scheduler/core/task_runner.py:258-380`
- Create: `tests/test_task_batch_security.py`

- [ ] **Step 1: Write failing API and service tests**

```python
class BatchTaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


def test_batch_request_rejects_account_id():
    with pytest.raises(ValidationError):
        BatchTaskUpdate.model_validate({"enabled": True, "account_id": "other"})


async def test_execution_rejects_task_account_owner_mismatch():
    task = task_fixture(user_id=1, account_id="account-2")
    account = account_fixture(user_id=2, account_id="account-2")
    result = await validate_fixture(task=task, account=account)
    assert result.status == "failed"
    assert "归属" in result.error_summary
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `.venv/bin/python -m pytest tests/test_task_batch_security.py -q`

Expected: FAIL because the typed request and ownership rejection do not exist.

- [ ] **Step 3: Implement strict request models and allowlisted service update**

```python
class BatchTaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class BatchTaskUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_ids: list[str] = Field(min_length=1)
    update: BatchTaskUpdate
```

Change the service signature to `batch_update_tasks(task_ids, enabled, user_id)`. Set only `task.enabled`, initialize `next_run_at` when enabling scheduled tasks, and reset `failure_count` only when transitioning from disabled to enabled.

In `_validate_and_resolve`, if an account is present and `int(account.user_id) != int(task.user_id)`, return a failed summary before `ensure_account_proxy()` or `get_client()` is called.

- [ ] **Step 4: Verify GREEN and run task service regressions**

Run: `.venv/bin/python -m pytest tests/test_task_batch_security.py tests/test_manual_shortcut_tasks.py tests/test_scheduler_resilience.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/h5_backend/routers/tasks.py backend/h5_backend/services/task/service.py backend/scheduler/core/task_runner.py tests/test_task_batch_security.py
git commit -m "fix: enforce task batch ownership boundaries"
```

### Task 2: Add Durable Per-Target Delivery Attempts

**Files:**
- Modify: `backend/database/schema/models.py:802-883`
- Create: `backend/scheduler/core/delivery_attempts.py`
- Create: `sql/migrations/034_task_delivery_attempts.sql`
- Create: `sql/migrations/rollback/034_task_delivery_attempts.down.sql`
- Create: `tests/test_task_delivery_attempts.py`
- Modify: `tests/test_migration_manager.py`

- [ ] **Step 1: Write failing model and service tests**

```python
async def test_claim_returns_confirmed_message_without_resend():
    repository = InMemoryAttemptRepository()
    service = DeliveryAttemptService(repository)
    key = DeliveryTargetKey("run-1", "channel", 1001)
    await repository.insert_success(key, telegram_message_id=77)
    claim = await service.claim(key, context_fixture())
    assert claim.should_send is False
    assert claim.telegram_message_id == 77


async def test_mark_sending_attempts_uncertain():
    repository = InMemoryAttemptRepository()
    service = DeliveryAttemptService(repository)
    await repository.insert_sending(DeliveryTargetKey("run-1", "channel", 1001))
    count = await service.mark_execution_uncertain("run-1", "task timeout")
    assert count == 1
    assert repository.rows[0].status == "uncertain"
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `.venv/bin/python -m pytest tests/test_task_delivery_attempts.py tests/test_migration_manager.py -q`

Expected: FAIL because attempt models and service are missing.

- [ ] **Step 3: Add schema and migration**

Create `TaskDeliveryAttempt` with the columns defined in the design. Add a unique constraint on `(execution_key, peer_type, peer_id)` and indexes on `(task_id, created_at)` and `(execution_key, status)`.

The migration must use project statement markers and add the task-log aggregate columns:

```sql
ALTER TABLE task_logs ADD COLUMN IF NOT EXISTS total_targets INTEGER;
ALTER TABLE task_logs ADD COLUMN IF NOT EXISTS success_count INTEGER;
ALTER TABLE task_logs ADD COLUMN IF NOT EXISTS failed_count INTEGER;
ALTER TABLE task_logs ADD COLUMN IF NOT EXISTS uncertain_count INTEGER;
```

- [ ] **Step 4: Implement focused checkpoint service**

`delivery_attempts.py` must keep functions below 50 lines and expose immutable value objects:

```python
@dataclass(frozen=True)
class DeliveryTargetKey:
    execution_key: str
    peer_type: str
    peer_id: int


@dataclass(frozen=True)
class DeliveryClaim:
    should_send: bool
    telegram_message_id: int | None
    previous_message_id: int | None
```

Implement `claim_delivery_target`, `mark_delivery_success`, `mark_delivery_failure`, `mark_execution_uncertain`, and `list_execution_attempts`. Every public operation owns one short `get_async_session()` scope.

- [ ] **Step 5: Verify migration parsing and service GREEN**

Run: `.venv/bin/python -m pytest tests/test_task_delivery_attempts.py tests/test_migration_manager.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/database/schema/models.py backend/scheduler/core/delivery_attempts.py sql/migrations/034_task_delivery_attempts.sql sql/migrations/rollback/034_task_delivery_attempts.down.sql tests/test_task_delivery_attempts.py tests/test_migration_manager.py
git commit -m "feat: persist per-target delivery attempts"
```

### Task 3: Make Send Ordering Safe and Remove Button Degradation

**Files:**
- Modify: `backend/scheduler/core/task_execution.py:304-431`
- Modify: `tests/test_task_message_entities.py`

- [ ] **Step 1: Add failing ordering and button tests**

```python
async def test_replacement_is_sent_before_previous_message_is_deleted():
    client = RecordingClient(send_result=SimpleNamespace(id=200))
    task = task_fixture(delete_previous=True, buttons=None)
    result = await do_send_message(client=client, task=task, send_target=1,
                                   previous_message_id=100, media_ref_prefix="tgmsg://")
    assert result == 200
    assert client.calls == ["send", "delete:100"]


async def test_button_error_is_not_retried_without_buttons():
    client = FailingButtonClient(RuntimeError("BUTTON_URL_INVALID"))
    with pytest.raises(RuntimeError, match="BUTTON_URL_INVALID"):
        await do_send_message(client=client, task=button_task_fixture(), send_target=1,
                              previous_message_id=None, media_ref_prefix="tgmsg://")
    assert client.send_count == 1
```

- [ ] **Step 2: Confirm RED**

Run: `.venv/bin/python -m pytest tests/test_task_message_entities.py -q`

Expected: ordering test observes delete first and button test observes two sends.

- [ ] **Step 3: Implement send-first replacement semantics**

Remove `_is_button_markup_error` and the buttonless retry. Send once using configured buttons. After a non-empty message result, attempt deletion of `previous_message_id`. Keep delete failure as a warning and return the new message ID.

- [ ] **Step 4: Verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_task_message_entities.py tests/test_task_issue_notifications.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/scheduler/core/task_execution.py tests/test_task_message_entities.py
git commit -m "fix: preserve configured delivery semantics"
```

### Task 4: Execute Telegram Sends Outside Database Transactions

**Files:**
- Create: `backend/scheduler/core/execution_snapshot.py`
- Modify: `backend/scheduler/core/task_runner.py`
- Modify: `backend/scheduler/core/worker.py:249-360`
- Create: `tests/test_task_execution_transactions.py`

- [ ] **Step 1: Write failing transaction-boundary and resume tests**

```python
async def test_network_send_runs_after_snapshot_session_closes():
    tracker = SessionTracker()
    sender = AsyncMock(side_effect=lambda *_a, **_k: tracker.assert_no_open_sessions() or 88)
    summary = await execute_with_fixtures(session_tracker=tracker, sender=sender)
    assert summary.status == "success"


async def test_resume_skips_target_already_confirmed_in_same_execution():
    attempts = attempt_fixture(success_peer=1001, message_id=88)
    sender = AsyncMock(return_value=99)
    summary = await execute_with_fixtures(attempts=attempts, peers=[1001, 1002], sender=sender,
                                          execution_key="run-1")
    assert sender.await_count == 1
    assert summary.success_count == 2
```

- [ ] **Step 2: Confirm RED**

Run: `.venv/bin/python -m pytest tests/test_task_execution_transactions.py -q`

Expected: FAIL because the current runner holds one session throughout sending and has no execution key.

- [ ] **Step 3: Introduce immutable execution snapshots**

Create frozen dataclasses for task and target data. Snapshot loading performs authorization, account ownership, schedule constraints, and client eligibility in short sessions. It returns plain values, never a live ORM object.

- [ ] **Step 4: Integrate delivery checkpoints**

Add `execution_key` to `execute_task_once()`. The scheduler derives it from `task_id` and claimed `next_run_at`; manual callers generate UUIDs. For each target:

```python
claim = await claim_delivery_target(context)
if claim.should_send:
    message_id = await send_target(snapshot, target, claim.previous_message_id)
    await mark_delivery_success(context.key, message_id)
else:
    message_id = claim.telegram_message_id
```

On cancellation or timeout, the worker calls `mark_execution_uncertain(execution_key, reason)` before recording the task timeout.

- [ ] **Step 5: Verify GREEN and scheduler regressions**

Run: `.venv/bin/python -m pytest tests/test_task_execution_transactions.py tests/test_scheduler_resilience.py tests/test_task_delivery_attempts.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/scheduler/core/execution_snapshot.py backend/scheduler/core/task_runner.py backend/scheduler/core/worker.py tests/test_task_execution_transactions.py
git commit -m "refactor: checkpoint task sends outside transactions"
```

### Task 5: Persist Exact Aggregate Results and Admin Statistics

**Files:**
- Modify: `backend/scheduler/core/task_lifecycle.py`
- Modify: `backend/scheduler/core/task_runner.py`
- Modify: `backend/h5_backend/services/task/serializers.py`
- Modify: `backend/h5_backend/services/admin/user_service.py:279-340`
- Create: `tests/test_task_result_persistence.py`
- Modify: `tests/test_admin_system_service.py`

- [ ] **Step 1: Write failing partial and uncertain result tests**

```python
async def test_partial_success_persists_counts():
    log = await finalize_fixture(success=2, failed=1, uncertain=0)
    assert log.result == "partial_success"
    assert (log.total_targets, log.success_count, log.failed_count, log.uncertain_count) == (3, 2, 1, 0)


async def test_uncertain_is_not_counted_as_success():
    log = await finalize_fixture(success=0, failed=0, uncertain=1)
    assert log.result == "uncertain"
    assert log.success_count == 0
```

- [ ] **Step 2: Confirm RED**

Run: `.venv/bin/python -m pytest tests/test_task_result_persistence.py tests/test_admin_system_service.py -q`

Expected: FAIL because TaskLog lacks aggregate columns and partial results are stored as success.

- [ ] **Step 3: Implement aggregate result calculation**

Add a pure `classify_execution_result(success_count, failed_count, uncertain_count)` function. Persist exact counts in one final short transaction. Admin success aggregates count only `result == "success"`; partial and uncertain counts are returned separately.

- [ ] **Step 4: Verify GREEN and full Batch 1 suite**

Run: `.venv/bin/python -m pytest tests/test_task_result_persistence.py tests/test_admin_system_service.py tests/test_scheduler_resilience.py tests/test_task_issue_notifications.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Run complete Batch 1 verification**

Run: `.venv/bin/python -m pytest -q`

Expected: zero failures.

Run: `npm --prefix frontend/h5 run build`

Expected: `vue-tsc` and Vite build succeed.

- [ ] **Step 6: Commit**

```bash
git add backend/scheduler/core/task_lifecycle.py backend/scheduler/core/task_runner.py backend/h5_backend/services/task/serializers.py backend/h5_backend/services/admin/user_service.py tests/test_task_result_persistence.py tests/test_admin_system_service.py
git commit -m "fix: persist exact task delivery outcomes"
```
