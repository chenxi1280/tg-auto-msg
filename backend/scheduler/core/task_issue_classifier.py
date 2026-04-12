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
            user_message="当前账号在这个群聊或频道里没有发送权限，可能被禁言、被移出，或被管理员限制发言。",
            should_auto_suspend_target=True,
            suspension_reason="user_banned_in_channel",
        )

    if error_type == "ChannelPrivateError":
        return TaskIssueClassification(
            error_type=error_type,
            issue_category="target_inaccessible",
            user_message="当前账号无法访问这个群聊或频道，可能频道已设为私有、账号未加入，或已被移出。",
            should_auto_suspend_target=True,
            suspension_reason="channel_private",
        )

    if detail:
        detail = detail.replace("\n", " ").strip()
        if len(detail) > 120:
            detail = detail[:117] + "..."
        message = f"发送失败，系统会稍后再试。原因：{detail}"
    else:
        message = "发送失败，系统会稍后再试。"

    return TaskIssueClassification(
        error_type=error_type,
        issue_category="send_error",
        user_message=message,
        should_auto_suspend_target=False,
        suspension_reason=None,
    )
