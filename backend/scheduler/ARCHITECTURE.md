# Scheduler Architecture

## Goals

- Keep scheduling behavior unchanged while reducing `worker.py` complexity.
- Separate producer queue logic, execution logic, and task lifecycle updates.
- Keep `TaskScheduler` as orchestration entry point only.

## Current Layout

- `backend/scheduler/worker.py`
  - Scheduler loop and orchestration: init/start/tick/execute task pipeline.
- `backend/scheduler/core/queue_ops.py`
  - Redis connection self-heal, due-task enqueue, pending-task dequeue.
- `backend/scheduler/core/task_execution.py`
  - Target resolution, media resolution, send flow, rate-limit/circuit-breaker wrapping.
- `backend/scheduler/core/task_lifecycle.py`
  - Time-window check, success/failure persistence, account-wide suspension.

## Design Rules

1. `worker.py` should not hold detailed send or persistence logic.
2. Redis queue operations should only live in `queue_ops.py`.
3. Message send path should only live in `task_execution.py`.
4. Task state transitions/log writes should only live in `task_lifecycle.py`.
5. New scheduling policies should be added as helper functions, not inline in the main loop.
