# Batch 2 Runtime Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make scheduler health, account synchronization, and send-rate data survive normal failures and reflect real runtime state.

**Architecture:** Use the configured scheduler interval, expose a dependency-aware runtime health endpoint, replace process-local account sync state with leased PostgreSQL jobs, and record send events atomically in Redis.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, PostgreSQL, Redis Lua, Docker Compose, unittest/pytest.

---

### Task 1: Make WORKER_INTERVAL Authoritative

**Files:**
- Modify: `backend/config/core/settings.py:59-141`
- Modify: `backend/scheduler/core/worker.py:24-149`
- Modify: `tests/test_scheduler_resilience.py`

- [ ] **Step 1: Write failing interval tests**

```python
def test_settings_reject_worker_interval_below_one():
    with pytest.raises(ValidationError):
        Settings(WORKER_INTERVAL=0, **required_env())


async def test_scheduler_uses_configured_worker_interval():
    scheduler = TaskScheduler()
    with patch.object(scheduler, "tick", AsyncMock(side_effect=[None, asyncio.CancelledError()])), \
         patch("backend.scheduler.core.worker.settings.worker_interval", 37), \
         patch("backend.scheduler.core.worker.asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError)) as sleep:
        with pytest.raises(asyncio.CancelledError):
            await scheduler.start()
    sleep.assert_awaited_once_with(37)
```

- [ ] **Step 2: Confirm RED**

Run: `.venv/bin/python -m pytest tests/test_scheduler_resilience.py -q`

Expected: FAIL because `SCAN_INTERVAL=10` is still used.

- [ ] **Step 3: Remove hardcoded interval and validate settings**

Add `worker_interval >= 1` validation. Resolve the interval once at scheduler start and use it for both normal and exception sleeps and startup logging.

- [ ] **Step 4: Verify GREEN and commit**

Run: `.venv/bin/python -m pytest tests/test_scheduler_resilience.py -q`

Expected: all selected tests pass.

```bash
git add backend/config/core/settings.py backend/scheduler/core/worker.py tests/test_scheduler_resilience.py
git commit -m "fix: honor configured scheduler interval"
```

### Task 2: Add Runtime Health Endpoint

**Files:**
- Create: `backend/h5_backend/services/runtime_health.py`
- Create: `backend/h5_backend/routers/health.py`
- Modify: `backend/h5_backend/app/factory.py`
- Modify: `docker-compose.yml:50-55`
- Modify: `deploy/check-services.sh:367-433`
- Create: `tests/test_runtime_health.py`

- [ ] **Step 1: Write failing service and route tests**

```python
async def test_runtime_health_reports_stalled_scheduler():
    snapshot = await collect_runtime_health(RuntimeFixtures(
        database_ok=True, redis_ok=True, scheduler_running=True,
        last_tick_finished_at=datetime.now() - timedelta(minutes=5),
        worker_interval=10, scheduler_mode="all", sync_worker_alive=True,
    ))
    assert snapshot.status == "unhealthy"
    assert "scheduler_tick_stale" in snapshot.issues


def test_runtime_health_route_returns_503_when_unhealthy():
    response = client.get("/api/health/runtime")
    assert response.status_code == 503
```

- [ ] **Step 2: Confirm RED**

Run: `.venv/bin/python -m pytest tests/test_runtime_health.py -q`

Expected: FAIL because health service and route are missing.

- [ ] **Step 3: Implement health snapshot and route**

Use immutable `RuntimeHealthSnapshot(status, issues, checked_at)` and injected probes. The production probe checks `SELECT 1`, Redis `PING`, scheduler state/tick age, and durable sync worker heartbeat. The route returns only status, issue codes, and timestamp.

- [ ] **Step 4: Update deployment health URLs**

Change Compose and `TGMSG_APP_HEALTH_URL` defaults from `/openapi.json` to `/api/health/runtime`. Preserve the public reverse-proxy reachability check separately.

- [ ] **Step 5: Verify GREEN and commit**

Run: `.venv/bin/python -m pytest tests/test_runtime_health.py tests/test_admin_system_routes.py -q`

Expected: all selected tests pass.

```bash
git add backend/h5_backend/services/runtime_health.py backend/h5_backend/routers/health.py backend/h5_backend/app/factory.py docker-compose.yml deploy/check-services.sh tests/test_runtime_health.py
git commit -m "feat: expose runtime-aware health checks"
```

### Task 3: Add Durable Account-Sync Job Storage

**Files:**
- Modify: `backend/database/schema/models.py`
- Create: `backend/h5_backend/services/account/sync_jobs.py`
- Create: `sql/migrations/035_account_sync_jobs.sql`
- Create: `sql/migrations/rollback/035_account_sync_jobs.down.sql`
- Create: `tests/test_account_sync_jobs.py`
- Modify: `tests/test_migration_manager.py`

- [ ] **Step 1: Write failing enqueue, dedupe, claim, and lease tests**

```python
async def test_enqueue_deduplicates_active_account_job():
    first = await repository.enqueue("acc-1", 7, "manual")
    second = await repository.enqueue("acc-1", 7, "login_success")
    assert second.job_id == first.job_id


async def test_expired_running_job_is_reclaimed():
    job = await repository.insert_running("acc-1", lease_until=past_time())
    reclaimed = await repository.recover_expired(now=current_time())
    assert reclaimed == 1
    assert await repository.status(job.job_id) == "pending"
```

- [ ] **Step 2: Confirm RED**

Run: `.venv/bin/python -m pytest tests/test_account_sync_jobs.py tests/test_migration_manager.py -q`

Expected: FAIL because durable jobs do not exist.

- [ ] **Step 3: Add model and migration**

Create `AccountSyncJob` with the design columns. Add a PostgreSQL partial unique index:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_account_sync_jobs_active_account
ON account_sync_jobs(account_id)
WHERE status IN ('pending', 'running');
```

- [ ] **Step 4: Implement repository operations**

Expose `enqueue_sync_job`, `claim_next_sync_job`, `complete_sync_job`, `fail_sync_job`, `recover_expired_sync_jobs`, and `get_sync_job`. Claim uses `with_for_update(skip_locked=True)`, commits a lease, and returns an immutable job snapshot.

- [ ] **Step 5: Verify GREEN and commit**

Run: `.venv/bin/python -m pytest tests/test_account_sync_jobs.py tests/test_migration_manager.py -q`

Expected: all selected tests pass.

```bash
git add backend/database/schema/models.py backend/h5_backend/services/account/sync_jobs.py sql/migrations/035_account_sync_jobs.sql sql/migrations/rollback/035_account_sync_jobs.down.sql tests/test_account_sync_jobs.py tests/test_migration_manager.py
git commit -m "feat: persist account synchronization jobs"
```

### Task 4: Replace In-Memory Auto-Sync Queue

**Files:**
- Modify: `backend/h5_backend/services/account/auto_sync.py`
- Modify: `backend/h5_backend/services/account/service.py`
- Modify: `backend/h5_backend/services/login/service.py`
- Modify: `backend/bot/account/binding_service.py`
- Modify: `backend/bot/handlers/account/management.py`
- Modify: `tests/test_account_auto_sync.py`
- Modify: `tests/test_account_service_sync.py`

- [ ] **Step 1: Write failing restart and job-ID tests**

```python
async def test_pending_job_survives_runtime_reconstruction():
    job = await enqueue_sync_job("acc-1", 7, "manual")
    restarted = AccountAutoSyncRuntime(repository=repository)
    claimed = await restarted.run_worker_once()
    assert claimed.job_id == job.job_id


async def test_manual_enqueue_returns_durable_job_id():
    result = await service.enqueue_sync("acc-1", user_id=7)
    assert result["status"] == "pending"
    assert result["job_id"]
```

- [ ] **Step 2: Confirm RED**

Run: `.venv/bin/python -m pytest tests/test_account_auto_sync.py tests/test_account_service_sync.py -q`

Expected: FAIL because runtime state is process-local and responses have no durable job ID.

- [ ] **Step 3: Refactor runtime to repository-backed worker**

Remove `_queue`, `_queued_account_ids`, and `_running_account_ids`. `enqueue_account()` writes or returns an active database job. The worker loop recovers expired leases, claims one job, runs `sync_account_snapshot()` outside the claim transaction, and persists success/failure.

Expose `last_worker_tick_at` for runtime health. Keep automatic candidate selection, but enqueue candidates as durable jobs.

- [ ] **Step 4: Update all callers and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_account_auto_sync.py tests/test_account_service_sync.py tests/test_login_session_policy.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/h5_backend/services/account/auto_sync.py backend/h5_backend/services/account/service.py backend/h5_backend/services/login/service.py backend/bot/account/binding_service.py backend/bot/handlers/account/management.py tests/test_account_auto_sync.py tests/test_account_service_sync.py
git commit -m "refactor: run account sync from durable jobs"
```

### Task 5: Record Real Rate-Limiter Send Events

**Files:**
- Modify: `backend/bot/safety/rate_limiter.py`
- Modify: `backend/scheduler/core/task_execution.py`
- Create: `tests/test_rate_limiter_send_events.py`

- [ ] **Step 1: Write failing event and lock-token tests**

```python
async def test_successful_send_records_one_event():
    limiter = RateLimiter(redis_client=fake_redis)
    result = await limiter.run_with_slot("acc-1", 1001, AsyncMock(return_value="ok"))
    assert result == "ok"
    assert await limiter.get_send_count("acc-1", 60) == 1


async def test_failed_send_records_no_event():
    limiter = RateLimiter(redis_client=fake_redis)
    with pytest.raises(RuntimeError):
        await limiter.run_with_slot("acc-1", 1001, AsyncMock(side_effect=RuntimeError("fail")))
    assert await limiter.get_send_count("acc-1", 60) == 0


async def test_release_does_not_delete_another_owner_lock():
    token = await limiter.acquire_account_lock("acc-1")
    await fake_redis.set("lock:account:acc-1", "new-owner")
    assert await limiter.release_account_lock("acc-1", token) is False
```

- [ ] **Step 2: Confirm RED**

Run: `.venv/bin/python -m pytest tests/test_rate_limiter_send_events.py -q`

Expected: FAIL because `record_send()` is empty and locks have no owner token.

- [ ] **Step 3: Implement token locks and atomic send events**

Use UUID lock tokens and compare-delete Lua. Add a sorted-set Lua script that prunes the selected window, inserts a unique event, sets expiry, and returns the count. `run_with_slot()` owns acquire/send/record/release. `send_with_protections()` calls this wrapper around the circuit-breaker send.

- [ ] **Step 4: Verify GREEN and full regression**

Run: `.venv/bin/python -m pytest tests/test_rate_limiter_send_events.py tests/test_rate_limiter_text_variation.py tests/test_task_message_entities.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/bot/safety/rate_limiter.py backend/scheduler/core/task_execution.py tests/test_rate_limiter_send_events.py
git commit -m "feat: record atomic send-rate events"
```

### Task 6: Complete Runtime Verification

**Files:**
- Modify: `docs/deployment/PRODUCTION_RUNTIME.md`
- Modify: `.env.example`
- Modify: `.env.docker.example`

- [ ] **Step 1: Update runtime documentation**

Document that `WORKER_INTERVAL` is authoritative, `/api/health/runtime` is the container health endpoint, account sync is database-backed, and rate counts represent confirmed successful sends.

- [ ] **Step 2: Run full backend verification**

Run: `.venv/bin/python -m pytest -q`

Expected: zero failures.

- [ ] **Step 3: Run frontend build and diff checks**

Run: `npm --prefix frontend/h5 run build`

Expected: `vue-tsc` and Vite build succeed.

Run: `git diff --check`

Expected: no output and exit code 0.

- [ ] **Step 4: Commit**

```bash
git add docs/deployment/PRODUCTION_RUNTIME.md .env.example .env.docker.example
git commit -m "docs: document reliable runtime behavior"
```
