# Delivery and Runtime Reliability Design

## Goal

Fix the confirmed task-delivery and runtime reliability defects without changing the existing user-facing task workflow. The work is split into two independently releasable batches: delivery correctness first, runtime durability second.

## Scope

Batch 1 covers:

- Preventing batch task updates from assigning another user's Telegram account.
- Persisting per-target delivery progress so a task-level timeout does not lose confirmed sends.
- Releasing database transactions before Telegram network calls.
- Sending the replacement message before deleting the previous message.
- Persisting `partial_success` as a first-class task-log result.
- Treating button-send failures as failures instead of silently sending without buttons.

Batch 2 covers:

- Making `WORKER_INTERVAL` the scheduler's real scan interval.
- Adding a runtime health endpoint and using it for the Docker healthcheck.
- Replacing the in-memory account-sync queue with a durable database queue.
- Recording real send events in the Redis-backed rate limiter.

The proxy ownership and visibility issue is explicitly outside this implementation scope.

## Design Principles

1. Telegram sends are external side effects and must not run inside a long database transaction.
2. A confirmed Telegram `message_id` is durable evidence and must be persisted immediately.
3. An unknown send outcome must be visible as `uncertain`; it must not be silently retried as though no send occurred.
4. API payloads use explicit schemas and field allowlists. ORM attribute discovery is not an authorization boundary.
5. Health checks must validate background work, not only HTTP reachability.
6. Queue recovery must be explicit through leases and persisted statuses.

## Batch 1 Architecture

### Typed Batch Updates and Ownership Recheck

The batch endpoint will accept a request model with:

- `task_ids: list[str]`
- `update: BatchTaskUpdate`

`BatchTaskUpdate` initially exposes only `enabled: bool`. Any unknown field is rejected. Account changes, target changes, and content changes continue to use the existing single-task update path, which performs ownership, authorization, normalization, and validation.

Task execution will add a second ownership check after loading the task and account. If `task.user_id != account.user_id`, execution fails before resolving a Telegram client and writes no send side effect.

### Delivery Run and Target Checkpoints

A new `task_delivery_attempts` table records one target within one execution:

- `id`: primary key.
- `execution_key`: stable identifier for the execution.
- `task_id`, `user_id`, `account_id`.
- `peer_type`, `peer_id`.
- `status`: `pending`, `sending`, `success`, `failed`, or `uncertain`.
- `telegram_message_id`.
- `previous_message_id`.
- `error_type`, `error_message`.
- `started_at`, `finished_at`, `created_at`, `updated_at`.

The unique key is `(execution_key, peer_type, peer_id)`. A scheduled execution key is derived from the task ID and the claimed `next_run_at`. A manual execution uses a generated UUID.

Before a target send, a short transaction creates or claims its attempt. A previously successful attempt returns its stored `telegram_message_id` without sending again. A pending attempt becomes `sending` and commits before the Telegram call.

After Telegram returns a message, a new short transaction immediately writes `status=success` and the message ID. A known exception writes `status=failed`. Cancellation or task-level timeout changes any still-sending attempts to `uncertain`. An uncertain result is reported for manual reconciliation and is not automatically resent under the same execution key.

### Transaction Boundaries

`execute_task_once()` will be split into these phases:

1. Load and validate a detached immutable execution snapshot in a short session.
2. Resolve the Telegram client outside a database session.
3. Claim each target attempt in a short session.
4. Send to Telegram without an open database transaction.
5. Persist each target result in a short session.
6. Aggregate attempts and update the task schedule and task log in a final short session.

No SQLAlchemy ORM entity will be retained as mutable shared state across network calls. Runtime target metadata will be rebuilt from persisted attempt results during finalization.

### Replacement Message Ordering

For `delete_previous=true`:

1. Send the new message.
2. Persist its successful attempt and new message ID.
3. Try to delete the previous message.
4. Record a deletion warning if deletion fails, while keeping the new send successful.

The system never deletes the previous message before the replacement is confirmed.

### Buttons and Partial Success

Button markup errors remain target failures. The sender will not retry without buttons.

`task_logs` gains:

- `total_targets`
- `success_count`
- `failed_count`
- `uncertain_count`

`result` supports `success`, `partial_success`, `failed`, `uncertain`, and `skipped`. A run is `partial_success` when at least one target succeeds and at least one target fails. Uncertain outcomes are never counted as success. Admin statistics continue to aggregate by `TaskLog.result`, so the new result values remain visible without parsing error text.

Task-level and target-level failure state remain separate. A partial success does not increment the task's all-target failure counter, but it also does not erase target issue records.

## Batch 2 Architecture

### Scheduler Interval

`TaskScheduler` reads `settings.worker_interval` at startup and uses that value for normal and error sleeps. Settings validation rejects values below one second. `SCAN_INTERVAL` is removed so configuration, Compose, documentation, and runtime behavior have one source of truth.

### Runtime Health

A public, non-secret `GET /api/health/runtime` endpoint returns HTTP 200 only when required components for the configured scheduler mode are healthy. It checks:

- Database connectivity.
- Redis connectivity.
- Scheduler `running` state.
- The age and result of the latest scheduler tick when consumer or producer work is enabled.
- Presence of a live account-sync worker lease loop.

Failure returns HTTP 503 with stable issue codes and no credentials, account identifiers, or task contents. The detailed authenticated admin scheduler-health endpoint remains unchanged. Docker Compose and deployment checks use `/api/health/runtime` instead of `/openapi.json`.

### Durable Account-Sync Jobs

A new `account_sync_jobs` table replaces `asyncio.Queue`:

- `job_id`: UUID primary key.
- `account_id`, `user_id`, `trigger_source`.
- `status`: `pending`, `running`, `success`, or `failed`.
- `available_at`, `lease_until`.
- `attempt_count`, `last_error`.
- `created_at`, `started_at`, `finished_at`, `updated_at`.

A partial unique index prevents more than one `pending` or `running` job for the same account. Enqueue returns the existing active job when deduplicated.

The worker claims one job using `FOR UPDATE SKIP LOCKED`, commits the running status and lease, then executes the sync outside the claim transaction. Completion is persisted in a short transaction. Expired running leases are explicitly recovered to pending during worker scans. Manual and login callers receive the durable `job_id` and current status.

Automatic timer timeouts remain visible failures and do not mark the entire application unhealthy. No job reports success unless `sync_account_snapshot()` completes and its result is persisted.

### Rate-Limiter Send Events

Actual message sending will use one rate-limiter wrapper that:

1. Acquires account and peer slots.
2. Executes the send.
3. Records a successful send event.
4. Releases only locks owned by its unique token.

Send events use Redis sorted sets keyed by account. The score is the send timestamp and the member is a unique event ID. A Lua script atomically prunes expired events, inserts the new event, sets key expiry, and returns the current count. `get_send_count(account_id, window_seconds)` prunes and counts the requested window from the same source.

Failed sends do not increment the successful-send count. Redis failure is surfaced as `RateLimiterBackendUnavailableError`; it is not silently ignored.

## Error Handling

- Validation and ownership errors fail before external side effects.
- Known Telegram failures are classified and persisted per target.
- Task cancellation marks in-flight attempts uncertain before propagating cancellation.
- Database persistence failures after a confirmed Telegram send surface as critical errors and leave the attempt visible for reconciliation; they are not converted to success.
- Health failures return explicit issue codes.
- Queue lease recovery is logged with job ID and previous lease time.

## Migration and Compatibility

Two forward migrations will be added:

1. Delivery attempts and task-log aggregate columns.
2. Durable account-sync jobs and active-job uniqueness.

Existing task logs remain valid with nullable count columns and their current `success/failed` results. Existing tasks require no data rewrite. Existing in-memory sync items cannot be migrated because they are process-local; the release sequence drains the old worker before switching implementations.

## Testing

Batch 1 tests cover:

- Batch payload rejection for `account_id` and arbitrary ORM fields.
- Execution refusal when task and account owners differ.
- A confirmed first target is not resent when the same execution resumes.
- Timeout marks an in-flight attempt uncertain.
- The replacement send occurs before previous-message deletion.
- Button errors never trigger a buttonless retry.
- Partial success persists exact aggregate counts and admin statistics.
- Telegram sends occur with no active task transaction.

Batch 2 tests cover:

- `WORKER_INTERVAL` controls scheduler sleep.
- Runtime health returns 503 for a stalled scheduler and 200 for a recent healthy tick.
- Pending sync jobs survive runtime reconstruction.
- Expired running jobs are reclaimed.
- Active job deduplication returns one job per account.
- Successful sends add Redis events; failed sends do not.
- Lock release uses token ownership.

Each behavior follows red-green-refactor. Each batch finishes with the complete backend test suite, frontend type-check/build, migration parser tests, and a clean-worktree check.

## Release Sequence

1. Deploy Batch 1 migrations and code together.
2. Verify task execution, partial-success logs, timeout/uncertain visibility, and scheduler health in the real environment.
3. Deploy Batch 2 migrations and code together.
4. Verify runtime health integration, durable sync lease recovery, and rate counts in the real environment.

No production database or deployment action is part of local implementation verification unless separately authorized.
