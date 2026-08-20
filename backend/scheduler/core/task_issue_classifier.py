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


_SPECIALIZED_ERROR_CLASSIFICATIONS = {
    "ChatSendPhotosForbiddenError": TaskIssueClassification(
        error_type="TARGET_PHOTO_FORBIDDEN",
        issue_category="media_permission_denied",
        user_message="目标聊天不允许发送图片，已暂停这个目标。",
        should_auto_suspend_target=True,
        suspension_reason="target_photo_forbidden",
        auto_suspend_after_failures=1,
    ),
    "ChatSendVideosForbiddenError": TaskIssueClassification(
        error_type="TARGET_VIDEO_FORBIDDEN",
        issue_category="media_permission_denied",
        user_message="目标聊天不允许发送视频，已暂停这个目标。",
        should_auto_suspend_target=True,
        suspension_reason="target_video_forbidden",
        auto_suspend_after_failures=1,
    ),
    "ChatSendGifsForbiddenError": TaskIssueClassification(
        error_type="TARGET_ANIMATION_FORBIDDEN",
        issue_category="media_permission_denied",
        user_message="目标聊天不允许发送动图，已暂停这个目标。",
        should_auto_suspend_target=True,
        suspension_reason="target_animation_forbidden",
        auto_suspend_after_failures=1,
    ),
    "ChatSendMediaForbiddenError": TaskIssueClassification(
        error_type="TARGET_MEDIA_FORBIDDEN",
        issue_category="media_permission_denied",
        user_message="目标聊天不允许发送媒体，已暂停这个目标。",
        should_auto_suspend_target=True,
        suspension_reason="target_media_forbidden",
        auto_suspend_after_failures=1,
    ),
    "UserBannedInChannelError": TaskIssueClassification(
        error_type="UserBannedInChannelError",
        issue_category="permission_denied",
        user_message="当前账号在这个群聊或频道里没有发送权限，可能被禁言、被移出，或被管理员限制发言。",
        should_auto_suspend_target=True,
        suspension_reason="user_banned_in_channel",
        auto_suspend_after_failures=1,
    ),
    "ChatWriteForbiddenError": TaskIssueClassification(
        error_type="ChatWriteForbiddenError",
        issue_category="permission_denied",
        user_message="当前账号无法在这个群聊发送消息，可能被禁言、被移出，或群组已限制发言。",
        should_auto_suspend_target=True,
        suspension_reason="chat_write_forbidden",
        auto_suspend_after_failures=1,
    ),
    "ChatSendPlainForbiddenError": TaskIssueClassification(
        error_type="ChatSendPlainForbiddenError",
        issue_category="permission_denied",
        user_message="当前群聊不允许此任务发送纯文本消息，已暂停这个目标。",
        should_auto_suspend_target=True,
        suspension_reason="chat_send_plain_forbidden",
        auto_suspend_after_failures=1,
    ),
    "ChatRestrictedError": TaskIssueClassification(
        error_type="ChatRestrictedError",
        issue_category="permission_denied",
        user_message="当前账号无法在这个群聊或频道执行发送操作，可能权限受限或群组已限制发言。",
        should_auto_suspend_target=True,
        suspension_reason="chat_restricted",
        auto_suspend_after_failures=1,
    ),
    "ChannelPrivateError": TaskIssueClassification(
        error_type="ChannelPrivateError",
        issue_category="target_inaccessible",
        user_message="当前账号无法访问这个群聊或频道，可能频道已设为私有、账号未加入，或已被移出。",
        should_auto_suspend_target=True,
        suspension_reason="channel_private",
        auto_suspend_after_failures=1,
    ),
    "RateLimiterTimeoutError": TaskIssueClassification(
        error_type="RateLimiterTimeoutError",
        issue_category="rate_limit_timeout",
        user_message="当前目标暂时未拿到发送时间槽，系统会稍后重试。",
        should_auto_suspend_target=False,
    ),
    "RateLimiterBackendUnavailableError": TaskIssueClassification(
        error_type="RateLimiterBackendUnavailableError",
        issue_category="rate_limit_backend_unavailable",
        user_message="发送限流服务暂时不可用，当前目标已跳过，系统会稍后重试。",
        should_auto_suspend_target=False,
    ),
}


def classify_task_send_error(exc: Exception) -> TaskIssueClassification:
    """Map raw send exception to normalized category and user-facing summary."""
    error_type = type(exc).__name__
    detail = str(exc or "").strip()

    specialized = _SPECIALIZED_ERROR_CLASSIFICATIONS.get(error_type)
    if specialized is not None:
        return specialized

    domain_code = str(getattr(exc, "code", "") or "").strip()
    if domain_code:
        return TaskIssueClassification(
            error_type=domain_code,
            issue_category="task_media_contract",
            user_message=detail or "任务媒体配置无效。",
            should_auto_suspend_target=False,
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
