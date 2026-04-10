"""Scheduler package."""

__all__ = ["TaskScheduler", "scheduler"]


def __getattr__(name):
    if name in {"TaskScheduler", "scheduler"}:
        from backend.scheduler.core.worker import TaskScheduler, scheduler

        return {"TaskScheduler": TaskScheduler, "scheduler": scheduler}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
