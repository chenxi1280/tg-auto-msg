# Account Resource Sync Rotation Design

Date: 2026-08-10

## Goal

Keep every eligible Telegram account resource snapshot current without creating concurrent connection storms, and make a manual synchronization request report the real outcome instead of only reporting that work entered an in-memory queue.

## User-visible contract

- Resource search reads the persisted `resources` snapshot. It is not a live Telegram search.
- Automatic synchronization eventually visits every eligible stale account in a deterministic rotation.
- A UI button click immediately enqueues with `wait=false`, then polls an independent status endpoint until the Telegram dialog fetch and resource transaction complete.
- The compatibility `wait=true` request returns success only after the same shared completion result is available, but the UI does not depend on one long HTTP connection.
- A failed or timed-out manual synchronization returns an explicit error. The UI must not display a completed-success message for queued work.
- After a successful manual synchronization, resource selectors reload the persisted snapshot before showing the result.

## Automatic rotation

An account is eligible when it is active, online, not banned, does not require reauthentication, and its active resource snapshot is missing or at least 24 hours old.

The default scan selects all eligible accounts. `ACCOUNT_AUTO_SYNC_MAX_CANDIDATES_PER_RUN=0` means unlimited; a positive value remains an explicit operational throttle. Proxy-bound accounts participate by default. `ACCOUNT_AUTO_SYNC_SKIP_PROXY_ACCOUNTS=true` remains an explicit emergency control.

Candidates are ordered by:

1. accounts with no active resource snapshot;
2. oldest `last_sync_at`;
3. stable `account_id` tie-breaker.

The runtime still uses one worker. Accounts are synchronized sequentially, and every attempt has a six-minute total timeout. That outer budget must be greater than the account service's 30-second profile timeout plus five-minute resource timeout; it must not cancel a valid large-dialog resource fetch before the resource-layer budget expires. A failure or timeout is logged for that account and the worker continues with the next queued account.

## Queue priority and deduplication

Priority is `manual`, then `login_success`, then `auto_timer`. FIFO order is preserved inside the same priority.

Only one live queue item exists per account. If a manual request targets an account already waiting behind automatic work, the account is reprioritized instead of duplicated. Multiple waiters share the same completion result. A stale superseded queue item is ignored when popped.

## Manual completion semantics

The UI manual flow is:

1. `POST /api/accounts/{account_id}/sync?wait=false` to enqueue or reprioritize the account;
2. `GET /api/accounts/{account_id}/sync-status` until a terminal state is returned;
3. reload the persisted account/resource snapshot only after `status=completed`.

The status endpoint returns `queued`, `running`, `completed`, `failed`, or `idle`. A completed or failed result remains queryable until that account is explicitly enqueued again. `idle` after a successful enqueue means the in-process state was lost, for example because the application restarted; the UI reports this explicitly and never treats it as success.

`POST /api/accounts/{account_id}/sync?wait=true` remains a compatibility path that waits on the shared account completion result.

- success: `status=completed`, `profile_sync_ok=true`, `resource_sync_ok=true`, and the synchronized resource count;
- Telegram or persistence failure: an explicit non-2xx response with the recorded error;
- request wait timeout: HTTP 504 without cancelling the underlying shared synchronization;
- `wait=false`: `status=queued`, `running`, or `reprioritized`, never `completed`.

The all-account endpoint remains asynchronous by default and returns queue counts. It does not claim that queued accounts have completed.

## Observability

Scan logs include total selected, enqueued, reprioritized, deduplicated, and current queue size. Completion logs include the account ID, trigger source, profile result, resource result, synchronized count, and explicit error without session or credential material.

## Recovery boundary

The current hotfix keeps the existing in-process queue and does not introduce a database migration. After a process restart, the startup scan reconstructs automatic work from stale resource timestamps. A polling UI sees `idle` if its manual queue state was interrupted by restart and fails visibly; it is never reported as completed without a committed resource snapshot.

## Verification

Automated coverage must prove:

- default scans enqueue every eligible candidate;
- proxy-bound accounts are included by default;
- candidate ordering is oldest-resource-first and deterministic;
- manual work reprioritizes an already queued automatic item without duplicate execution;
- one account failure or timeout does not stop the following account;
- automatic work uses the same six-minute total budget as manual work, so a large-dialog account can use the full resource-layer timeout;
- `wait=true` observes completed and failed outcomes without cancelling shared work;
- the button path enqueues without a long request, polls queued/running to a terminal result, and rejects failed/idle/timeout states;
- resource pages reload after successful completion.

Production verification must compare a known stale account across application logs, `resources.last_sync_at`, and a read-only Telegram dialog fact. Container health alone is not completion evidence.
