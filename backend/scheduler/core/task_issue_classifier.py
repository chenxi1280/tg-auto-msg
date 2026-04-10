"""Classification helpers for per-target task send issues."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskIssueClassification:
    """Normalized task issue classification result."""

    error_type: str
    issue_category: str
    user_message: str
    should_auto_suspend_target: bool
    suspension_reason: str | None = None


def classify_task_send_error(exc: Exception) -> TaskIssueClassification:
    """Map raw send exception to normalized category and user-facing summary."""
    error_type = type(exc).__name__
    detail = str(exc or "").strip()

    if error_type == "UserBannedInChannelError":
        return TaskIssueClassification(
            error_type=error_type,
            issue_category="permission_denied",
            user_message="当前账号已被该目标限制发送消息（UserBannedInChannelError）",
            should_auto_suspend_target=True,
            suspension_reason="user_banned_in_channel",
        )

    if error_type == "ChannelPrivateError":
        return TaskIssueClassification(
            error_type=error_type,
            issue_category="target_inaccessible",
            user_message="当前账号无权访问该频道或群组（ChannelPrivateError）",
            should_auto_suspend_target=True,
            suspension_reason="channel_private",
        )

    if detail:
        detail = detail.replace("\n", " ").strip()
        if len(detail) > 120:
            detail = detail[:117] + "..."
        message = f"发送失败（{error_type}）：{detail}"
    else:
        message = f"发送失败（{error_type}）"

    return TaskIssueClassification(
        error_type=error_type,
        issue_category="send_error",
        user_message=message,
        should_auto_suspend_target=False,
        suspension_reason=None,
    )
