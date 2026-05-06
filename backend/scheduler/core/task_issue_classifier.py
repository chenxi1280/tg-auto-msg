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
    auto_suspend_after_failures: int | None = None


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
            auto_suspend_after_failures=1,
        )

    if error_type == "ChannelPrivateError":
        return TaskIssueClassification(
            error_type=error_type,
            issue_category="target_inaccessible",
            user_message="当前账号无法访问这个群聊或频道，可能频道已设为私有、账号未加入，或已被移出。",
            should_auto_suspend_target=True,
            suspension_reason="channel_private",
            auto_suspend_after_failures=1,
        )

    if error_type == "RateLimiterTimeoutError":
        return TaskIssueClassification(
            error_type=error_type,
            issue_category="rate_limit_timeout",
            user_message="当前目标暂时未拿到发送时间槽，系统会稍后重试。",
            should_auto_suspend_target=False,
            suspension_reason=None,
            auto_suspend_after_failures=None,
        )

    if error_type == "RateLimiterBackendUnavailableError":
        return TaskIssueClassification(
            error_type=error_type,
            issue_category="rate_limit_backend_unavailable",
            user_message="发送限流服务暂时不可用，当前目标已跳过，系统会稍后重试。",
            should_auto_suspend_target=False,
            suspension_reason=None,
            auto_suspend_after_failures=None,
        )

    if detail == "send_message returned empty":
        return TaskIssueClassification(
            error_type="EmptyMessageResultError",
            issue_category="empty_result",
            user_message="消息发送后未拿到回执，若连续多次出现，系统会自动暂停该目标。",
            should_auto_suspend_target=False,
            suspension_reason="empty_result",
            auto_suspend_after_failures=3,
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
        auto_suspend_after_failures=None,
    )
