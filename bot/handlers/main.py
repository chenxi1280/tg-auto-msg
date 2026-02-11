"""
Bot 主处理器：命令、回调按钮、消息处理
"""
from datetime import datetime
from typing import Optional, Any
import re
import ipaddress
from urllib.parse import urlparse
from loguru import logger

from telethon import events, Button
from telethon.errors.rpcerrorlist import MessageNotModifiedError
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
from sqlalchemy import select

from bot.client import bot_client
from bot.fsm import fsm_storage, FSMState
from bot.keyboards import (
    get_task_list_keyboard, get_task_settings_keyboard,
    get_interval_keyboard, get_hour_select_keyboard,
    get_confirm_delete_keyboard, get_cancel_keyboard
)
from bot.messages import *
from database.session import get_async_session
from database.models import ScheduledMessageTask, MediaType, Account, User, Resource

_LOCAL_BUTTON_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
_TASK_SELECTOR_KEY = "task_selector_ctx"
_TARGET_PAGE_SIZE = 8
_SUPPORTED_PEER_TYPES = {"user", "chat", "supergroup", "channel"}
_TARGET_FILTER_TYPES = {"all", "user", "group", "channel"}


def _should_edit_event(event) -> bool:
    """仅回调按钮事件允许 edit；普通消息事件使用 respond。"""
    return isinstance(event, events.CallbackQuery.Event)


def _normalize_h5_base_url() -> str:
    base = (H5_BASE_URL or "").strip()
    if not base:
        return ""
    if not base.startswith(("http://", "https://")):
        base = "http://" + base
    return base.rstrip("/")


def _build_h5_login_url() -> str:
    base = _normalize_h5_base_url()
    return f"{base}/login" if base else ""


def _is_valid_button_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = (parsed.hostname or "").lower()
    if host in _LOCAL_BUTTON_HOSTS:
        return False
    # Telegram URL 按钮不接受内网/保留地址，避免触发 ButtonUrlInvalidError
    try:
        ip = ipaddress.ip_address(host)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    except ValueError:
        # 不是 IP，按域名继续放行
        pass
    return True


def _build_login_buttons(label: str = "🔐 扫码登录"):
    login_url = _build_h5_login_url()
    if _is_valid_button_url(login_url):
        return [[Button.url(label, login_url)]]
    return [[Button.inline("🔐 登录指引", data="show_login_help")]]


def _login_help_text() -> str:
    login_url = _build_h5_login_url() or "http://localhost:8000/login"
    return (
        "当前 H5 地址不可作为 Telegram URL 按钮（本地/内网地址）。\n"
        f"请在浏览器手动打开: {login_url}"
    )


async def _resolve_db_user_id(session, actor_user_id: int) -> Optional[int]:
    """
    将 Telegram 发送者 ID 映射为系统用户 ID。
    - 新链路：通过已绑定账号的 tg_user_id 找到 owner user_id
    - 兼容链路：如果 actor_user_id 本身是系统用户 ID，则直接返回
    """
    account_result = await session.execute(
        select(Account.user_id)
        .where(Account.tg_user_id == actor_user_id)
        .order_by(Account.created_at.desc())
        .limit(1)
    )
    mapped_user_id = account_result.scalar_one_or_none()
    if mapped_user_id is not None:
        return int(mapped_user_id)

    legacy_user = await session.execute(
        select(User.id).where(User.id == actor_user_id)
    )
    legacy_user_id = legacy_user.scalar_one_or_none()
    if legacy_user_id is not None:
        return int(legacy_user_id)

    return None


async def _require_db_user_id(event, actor_user_id: int, *, alert: bool = False) -> Optional[int]:
    """获取并校验系统用户 ID，不存在时给出统一提示。"""
    async with get_async_session() as session:
        db_user_id = await _resolve_db_user_id(session, actor_user_id)

    if db_user_id is not None:
        return db_user_id

    msg = (
        "当前 Telegram 账号还未绑定系统用户。\n"
        "请先打开 H5 完成系统登录与扫码绑定，再发送 /bind <绑定码>。"
    )
    if alert and hasattr(event, "answer"):
        await event.answer(msg, alert=True)
    else:
        await event.respond(
            "⚠️ 当前 Telegram 账号还未绑定系统用户。\n\n"
            "请先在 H5 登录并扫码绑定，然后发送 `/bind <绑定码>`。",
            parse_mode="markdown",
            buttons=_build_login_buttons("🔐 前往 H5 登录")
        )
    return None


def _peer_meta(peer_type: str) -> tuple[str, str]:
    peer_type = str(peer_type or "").lower()
    if peer_type == "user":
        return "👤", "个人"
    if peer_type in {"chat", "supergroup"}:
        return "👥", "群组"
    if peer_type == "channel":
        return "📢", "频道"
    return "💬", peer_type or "未知"


def _truncate_text(text: str, max_len: int = 24) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _normalize_target_filter(value: Optional[str]) -> str:
    filter_value = str(value or "").strip().lower()
    return filter_value if filter_value in _TARGET_FILTER_TYPES else "all"


def _target_filter_label(filter_value: str) -> str:
    filter_value = _normalize_target_filter(filter_value)
    if filter_value == "user":
        return "👤 个人"
    if filter_value == "group":
        return "👥 群聊"
    if filter_value == "channel":
        return "📢 频道"
    return "🌐 全部"


def _resource_matches_filter(resource: Resource, peer_filter: str) -> bool:
    peer_filter = _normalize_target_filter(peer_filter)
    peer_type = str(resource.peer_type or "").lower()
    if peer_filter == "all":
        return True
    if peer_filter == "user":
        return peer_type == "user"
    if peer_filter == "group":
        return peer_type in {"chat", "supergroup"}
    if peer_filter == "channel":
        return peer_type == "channel"
    return True


def _filter_target_resources(
    resources: list[Resource],
    *,
    peer_filter: str,
    search_query: str,
) -> list[Resource]:
    peer_filter = _normalize_target_filter(peer_filter)
    keyword = (search_query or "").strip().lower()
    normalized_keyword = keyword.lstrip("@")

    filtered: list[Resource] = []
    for resource in resources:
        if not _resource_matches_filter(resource, peer_filter):
            continue

        if keyword:
            title = str(resource.title or "").lower()
            username = str(resource.username or "").lower()
            peer_id_str = str(resource.peer_id)
            if (
                keyword not in title
                and keyword not in username
                and normalized_keyword not in username
                and keyword not in peer_id_str
            ):
                continue

        filtered.append(resource)

    return filtered


def _escape_markdown(text: str) -> str:
    text = str(text or "")
    return (
        text.replace("\\", "\\\\")
        .replace("_", "\\_")
        .replace("*", "\\*")
        .replace("`", "\\`")
    )


def _normalize_task_targets(task: ScheduledMessageTask) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []

    raw_targets = getattr(task, "target_peers", None)
    if isinstance(raw_targets, list):
        for item in raw_targets:
            if not isinstance(item, dict):
                continue
            try:
                peer_id = int(item.get("peer_id"))
            except Exception:
                continue
            peer_type = str(item.get("peer_type") or "").strip().lower()
            if peer_type not in _SUPPORTED_PEER_TYPES:
                continue
            access_hash = item.get("access_hash")
            if access_hash not in (None, ""):
                try:
                    access_hash = int(access_hash)
                except Exception:
                    access_hash = None
            targets.append({
                "peer_id": peer_id,
                "peer_type": peer_type,
                "access_hash": access_hash,
            })

    if not targets:
        raw_peer_id = task.target_peer_id or task.chat_id
        if raw_peer_id:
            peer_type = str(task.target_peer_type or "user").strip().lower()
            if peer_type not in _SUPPORTED_PEER_TYPES:
                peer_type = "user"
            targets.append({
                "peer_id": int(raw_peer_id),
                "peer_type": peer_type,
                "access_hash": task.target_access_hash,
            })

    deduped: list[dict[str, Any]] = []
    seen = set()
    for target in targets:
        key = (target["peer_type"], target["peer_id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(target)
    return deduped


def _apply_task_targets(task: ScheduledMessageTask, targets: list[dict[str, Any]]) -> None:
    task.target_peers = targets if targets else None
    if targets:
        primary = targets[0]
        task.target_peer_id = int(primary["peer_id"])
        task.target_peer_type = str(primary["peer_type"])
        task.target_access_hash = primary.get("access_hash")
        task.chat_id = int(primary["peer_id"])
    else:
        task.target_peer_id = None
        task.target_peer_type = None
        task.target_access_hash = None
        task.chat_id = None


def _set_selector_context(
    user_id: int,
    *,
    task_id: str,
    account_id: Optional[str] = None,
    page: int = 0,
    peer_filter: str = "all",
    search: str = "",
    expect_search: bool = False,
) -> None:
    fsm_storage.update_data(
        user_id,
        **{
            _TASK_SELECTOR_KEY: {
                "task_id": task_id,
                "account_id": account_id,
                "page": max(0, int(page)),
                "peer_filter": _normalize_target_filter(peer_filter),
                "search": str(search or "").strip(),
                "expect_search": bool(expect_search),
            }
        }
    )


def _get_selector_context(user_id: int) -> Optional[dict[str, Any]]:
    data = fsm_storage.get_data(user_id)
    ctx = data.get(_TASK_SELECTOR_KEY)
    if isinstance(ctx, dict) and ctx.get("task_id"):
        return ctx
    return None


def _clear_selector_context(user_id: int) -> None:
    fsm_storage.update_data(user_id, **{_TASK_SELECTOR_KEY: None})


# ============ 命令处理 ============

@bot_client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    """开始命令"""
    actor_user_id = event.sender_id
    fsm_storage.reset_state(actor_user_id)

    async with get_async_session() as session:
        db_user_id = await _resolve_db_user_id(session, actor_user_id)

    from bot.account_manager import get_account_manager
    account_manager = get_account_manager()
    accounts = await account_manager.get_accounts(db_user_id, is_active=False) if db_user_id else []

    # 当前 Telegram 用户未绑定任何执行账号
    if not accounts:
        text = """👋 欢迎使用 **定时消息推送管理系统**！

⚠️ **需要先登录 Userbot**

Userbot 负责实际发送消息到群组/频道。请先完成登录：

**登录步骤：**
1. 点击下方「🔐 扫码登录」按钮
2. 在打开的页面中使用 Telegram 扫描二维码
3. 登录成功后返回 Bot 即可

💡 Userbot 登录一次即可长期使用，无需重复登录。
"""
        # 使用 WebApp URL 或直接发送链接
        keyboard = _build_login_buttons("🔐 扫码登录")
        await event.respond(text, buttons=keyboard, parse_mode='markdown')
        return

    # 已有绑定账号，显示正常欢迎消息
    text = """👋 欢迎使用 **定时消息推送管理系统**！

本系统可以帮助你在 Telegram 群组/频道中自动发送定时消息。

**主要功能：**
• 📢 定时推送消息（支持文本、媒体、按钮）
• ⏰ 灵活的时间控制（重复间隔、时段限制、起止日期）
• 🗑️ 自动删除上一条消息
• 📌 自动置顶新消息
• 🌐 H5 控制台（高级编辑）

点击下方按钮开始使用：
"""
    keyboard = [[Button.inline("📢 进入任务列表", data="task_list")]]

    await event.respond(text, buttons=keyboard, parse_mode='markdown')


@bot_client.on(events.NewMessage(pattern='/tasks'))
async def tasks_handler(event):
    """任务列表命令"""
    user_id = event.sender_id
    fsm_storage.reset_state(user_id)
    if await _require_db_user_id(event, user_id) is None:
        return
    await show_task_list(event, user_id)


@bot_client.on(events.NewMessage(func=lambda e: bool((e.raw_text or "").strip().startswith("/"))))
async def command_trace_handler(event):
    """记录收到的命令，便于定位 Bot 不回包问题。"""
    if getattr(event, "out", False):
        return
    text = (event.raw_text or "").strip().replace("\n", "\\n")
    if len(text) > 120:
        text = text[:117] + "..."
    logger.info(
        f"收到命令: sender={event.sender_id}, chat={event.chat_id}, text={text!r}"
    )


@bot_client.on(events.NewMessage())
async def bind_handler(event):
    """绑定账号命令 /bind <code>"""
    try:
        actor_tg_user_id = event.sender_id

        # 兼容全角斜杠、前导空白等输入差异
        text = (event.raw_text or event.message.message or "")
        normalized = text.replace("／", "/").strip()
        if not normalized:
            return

        # 只处理 bind 指令，避免影响其他命令
        if not normalized.lower().startswith("/bind"):
            return

        logger.info(f"收到 /bind 命令: sender={actor_tg_user_id}, text={normalized!r}")

        # 支持: /bind 123456  或 /bind@YourBot 123456
        match = re.match(r"(?i)^/bind(?:@[\w\d_]+)?(?:\s+([0-9]{6}))?(?:\s+.*)?$", normalized)
        if not match:
            await event.respond(
                "📝 **使用方法：**`/bind <6位绑定码>`\n\n"
                "示例：`/bind 123456`",
                parse_mode="markdown"
            )
            return

        bind_code = (match.group(1) or "").strip()
        if not bind_code:
            await event.respond("❌ 请输入 6 位绑定码，例如：`/bind 123456`", parse_mode="markdown")
            return

        # 若 Telegram 发送者已映射系统用户，优先用系统用户身份绑定；
        # 失败时会在 bind_account 内部回退到 Telegram 发送者身份。
        bind_user_id = actor_tg_user_id
        async with get_async_session() as session:
            mapped_db_user_id = await _resolve_db_user_id(session, actor_tg_user_id)
            if mapped_db_user_id is not None:
                bind_user_id = int(mapped_db_user_id)

        # 执行绑定
        await bind_account(event, bind_user_id, bind_code, actor_tg_user_id=actor_tg_user_id)
    except Exception as e:
        logger.exception(f"/bind 处理失败: {type(e).__name__}: {e!r}")
        await event.respond("❌ 绑定处理异常，请稍后重试")


@bot_client.on(events.NewMessage(pattern='/accounts'))
async def accounts_handler(event):
    """账号列表命令 /accounts"""
    user_id = event.sender_id
    if await _require_db_user_id(event, user_id) is None:
        return
    await show_accounts_list(event, user_id)


@bot_client.on(events.NewMessage(pattern='/sync'))
async def sync_handler(event):
    """同步资源命令 /sync [account_id]"""
    user_id = event.sender_id
    text = event.message.message.strip()
    parts = text.split(maxsplit=1)

    account_id = None
    if len(parts) >= 2:
        account_id = parts[1].strip()

    if await _require_db_user_id(event, user_id) is None:
        return
    await sync_account_resources(event, user_id, account_id)


@bot_client.on(events.NewMessage(pattern='/proxy'))
async def proxy_handler(event):
    """代理管理命令 /proxy"""
    user_id = event.sender_id
    if await _require_db_user_id(event, user_id) is None:
        return
    await show_proxy_management(event, user_id)


# ============ 账号绑定功能 ============

async def bind_account(event, user_id: int, bind_code: str, actor_tg_user_id: Optional[int] = None):
    """绑定账号"""
    from bot.account_manager import get_account_manager

    account_manager = get_account_manager()

    try:
        account = await account_manager.bind_account(user_id, bind_code)
        if not account and actor_tg_user_id and actor_tg_user_id != user_id:
            logger.info(
                f"绑定首次失败，回退 Telegram 身份重试: bind_user_id={user_id}, actor_tg_user_id={actor_tg_user_id}"
            )
            account = await account_manager.bind_account(actor_tg_user_id, bind_code)

        if account:
            text = f"""✅ **账号绑定成功！**

🔑 **账号信息**
• 用户名：@{account.username or account.account_id[:8]}
• 手机号：{account.phone or '未设置'}
• 状态：{'在线' if account.health_status == 'online' else '离线'}

• 系统正在自动同步您的群组/频道列表...
• 同步完成后即可在任务中使用该账号发送消息。

💡 您可以绑定多个账号，系统会自动选择合适的账号发送消息。"""

            keyboard = [[Button.inline("📢 查看我的账号", data="accounts_list")],
                       [Button.inline("📋 进入任务列表", data="task_list")]]
            await event.respond(text, buttons=keyboard, parse_mode='markdown')
        else:
            await event.respond(
                "❌ 绑定失败：绑定码无效或已过期\n\n"
                "请重新扫码登录获取新的绑定码，或确认发送 /bind 的 Telegram 账号正确。"
            )
    except Exception as e:
        logger.error(f"绑定账号失败: {e}")
        await event.respond(f"❌ 绑定失败：{str(e)}")


# ============ 账号管理功能 ============

async def show_accounts_list(event, user_id: int):
    """显示账号列表"""
    from bot.account_manager import get_account_manager
    from database.models import HealthStatus

    db_user_id = await _require_db_user_id(event, user_id)
    if db_user_id is None:
        return

    account_manager = get_account_manager()
    accounts = await account_manager.get_accounts(db_user_id)

    if not accounts:
        text = """📱 **我的账号**

您还没有绑定任何 Userbot 账号。

**绑定步骤：**
1. 点击「🔐 扫码登录」
2. 使用 Telegram 扫描二维码
3. 获得绑定码后，使用 `/bind <绑定码>` 命令绑定

💡 绑定后即可在任务中使用该账号发送消息。"""
        keyboard = _build_login_buttons("🔐 扫码登录")
    else:
        # 构建账号列表
        account_lines = []
        for acc in accounts:
            status_emoji = {
                HealthStatus.ONLINE: "🟢",
                HealthStatus.OFFLINE: "🔴",
                HealthStatus.BANNED: "⛔"
            }.get(acc.health_status, "⚪")

            flooding_info = " [⏱ FloodWait]" if acc.is_flooding else ""

            account_lines.append(
                f"{status_emoji} @{acc.username or acc.account_id[:8]}{flooding_info}\n"
                f"  已发送: {acc.messages_sent} 条"
            )

        accounts_text = "\n\n".join(account_lines)
        text = f"""📱 **我的账号** ({len(accounts)})

{accounts_text}

💡 提示：
• 点击下方「🔄 同步资源」可更新账号的群组列表
• 点击「➕ 添加账号」可绑定更多账号"""

        keyboard = [
            _build_login_buttons("🔐 扫码登录")[0],
            [Button.inline("🔄 同步资源", data="sync_all")],
            [Button.inline("📋 进入任务列表", data="task_list")]
        ]

    await event.respond(text, buttons=keyboard, parse_mode='markdown')


# ============ 资源同步功能 ============

async def sync_account_resources(event, user_id: int, account_id: Optional[str]):
    """同步账号资源"""
    from bot.account_manager import get_account_manager
    from bot.resource_manager import get_resource_manager

    db_user_id = await _require_db_user_id(event, user_id)
    if db_user_id is None:
        return

    account_manager = get_account_manager()
    resource_manager = get_resource_manager()

    # 如果没有指定账号，获取用户的第一个账号
    if not account_id:
        accounts = await account_manager.get_accounts(db_user_id)
        if not accounts:
            await event.respond(
                "❌ 您还没有绑定任何账号\n\n"
                "请先使用 `/accounts` 查看账号列表，"
                "或使用「🔐 扫码登录」绑定账号。"
            )
            return
        account_id = accounts[0].account_id

    try:
        # 发送同步中消息
        status_msg = await event.respond("⏳ 正在同步资源，请稍候...")

        # 执行同步
        result = await resource_manager.full_sync(account_id)

        # 构建结果消息
        text = f"""📊 **资源同步完成**

**同步统计：**
• 总计：{result.synced} 个
• 新增：{result.new} 个
• 更新：{result.updated} 个
• 删除：{result.deleted} 个"""

        if result.error:
            text += f"\n⚠️ 错误：{result.error}"

        # 更新消息
        await status_msg.edit(text, parse_mode='markdown')

    except Exception as e:
        logger.error(f"同步资源失败: {e}")
        await event.respond(f"❌ 同步失败：{str(e)}")


# ============ 代理管理功能 ============

async def show_proxy_management(event, user_id: int):
    """显示代理管理"""
    from bot.proxy_pool import get_proxy_pool

    proxy_pool = get_proxy_pool()
    proxies = await proxy_pool.get_proxies(is_active=True, is_healthy=None)

    if not proxies:
        text = """🌐 **代理管理**

当前没有配置任何代理。

**代理功能：**
• 为每个 Userbot 账号分配独立代理
• 避免 IP 关联，提高账号安全性
• 自动健康检查和故障切换

**添加代理：**
请联系管理员添加代理配置。"""
        keyboard = [[Button.inline("📋 进入任务列表", data="task_list")]]
    else:
        # 构建代理列表
        proxy_lines = []
        for p in proxies:
            status_emoji = "🟢" if p.is_healthy else "🔴"
            assigned_info = f" → 已分配" if p.assigned_account_id else ""
            proxy_lines.append(
                f"{status_emoji} {p.proxy_type}://{p.host}:{p.port}{assigned_info}\n"
                f"  响应时间: {p.response_time_ms or '-'} ms | "
                f"使用次数: {p.usage_count}"
            )

        proxies_text = "\n\n".join(proxy_lines)
        text = f"""🌐 **代理管理** ({len(proxies)})

{proxies_text}

💡 提示：
• 健康代理会自动分配给新绑定的账号
• 系统会定期检查代理健康状态"""

        keyboard = [[Button.inline("📋 进入任务列表", data="task_list")]]

    await event.respond(text, buttons=keyboard, parse_mode='markdown')


# ============ 新增回调处理 ============

@bot_client.on(events.CallbackQuery())
async def callback_handler(event):
    """回调按钮处理"""
    try:
        user_id = event.sender_id
        data = event.data.decode()

        # 重置 FSM 状态
        current_state = fsm_storage.get_state(user_id)

        # 如果不在 FSM 等待状态，则处理回调
        if current_state == FSMState.NONE:
            await handle_callback(event, user_id, data)
        else:
            # 在等待输入状态，只允许取消
            if data.startswith("settings:"):
                fsm_storage.reset_state(user_id)
                task_id = data.split(":")[1]
                await show_task_settings(event, user_id, task_id)
            elif current_state == FSMState.WAIT_TARGET_SEARCH and data.startswith("pick_"):
                fsm_storage.set_state(user_id, FSMState.NONE)
                await handle_callback(event, user_id, data)
            else:
                await event.answer("请先完成当前输入，或点击取消", alert=True)
    except MessageNotModifiedError:
        # 点击刷新/重复点击同一选项时，内容可能完全一致。
        # Telethon 会抛 MessageNotModifiedError，这不是业务错误。
        try:
            await event.answer("已是最新内容")
        except Exception:
            pass
    except Exception as e:
        logger.exception(f"回调处理失败: {type(e).__name__}: {e!r}")
        await event.answer("操作失败，请稍后重试", alert=True)


async def handle_callback(event, user_id: int, data: str):
    """处理所有回调按钮"""
    parts = data.split(":")
    action = parts[0]

    if await _require_db_user_id(event, user_id, alert=True) is None:
        return

    # ============ 新增回调 ============
    if action == "accounts_list":
        await show_accounts_list(event, user_id)

    elif action == "show_login_help":
        await event.answer(_login_help_text(), alert=True)

    elif action == "sync_all":
        # 同步所有账号的资源
        await sync_account_resources(event, user_id, None)

    # ============ 列表页操作 ============
    elif action == "task_list":
        await show_task_list(event, user_id)

    elif action == "refresh":
        await show_task_list(event, user_id)

    elif action == "add_task":
        await create_new_task(event, user_id)

    elif action == "view":
        task_id = parts[1]
        await show_task_settings(event, user_id, task_id)

    elif action == "toggle":
        task_id = parts[1]
        await toggle_task(event, user_id, task_id)

    elif action == "delete":
        task_id = parts[1]
        await confirm_delete_task(event, user_id, task_id)

    elif action == "confirm_delete":
        task_id = parts[1]
        await delete_task(event, user_id, task_id)

    elif action == "back_to_list":
        await show_task_list(event, user_id)

    # ============ 设置页操作 ============
    elif action == "settings":
        task_id = parts[1]
        await show_task_settings(event, user_id, task_id)

    elif action == "edit_account":
        task_id = parts[1]
        await start_select_task_account(event, user_id, task_id)

    elif action == "edit_targets":
        task_id = parts[1]
        await start_select_task_targets(event, user_id, task_id, page=0)

    elif action == "set_enable":
        task_id = parts[1]
        await update_task_enabled(event, user_id, task_id, True)

    elif action == "set_disable":
        task_id = parts[1]
        await update_task_enabled(event, user_id, task_id, False)

    elif action == "toggle_delete":
        task_id = parts[1]
        await toggle_delete_previous(event, user_id, task_id)

    elif action == "toggle_pin":
        task_id = parts[1]
        await toggle_pin_message(event, user_id, task_id)

    elif action == "edit_text":
        task_id = parts[1]
        await start_edit_text(event, user_id, task_id)

    elif action == "edit_media":
        task_id = parts[1]
        await start_edit_media(event, user_id, task_id)

    elif action == "edit_buttons":
        task_id = parts[1]
        await start_edit_buttons(event, user_id, task_id)

    elif action == "edit_interval":
        task_id = parts[1]
        await show_interval_selection(event, user_id, task_id)

    elif action == "edit_hours":
        task_id = parts[1]
        await start_edit_hours(event, user_id, task_id)

    elif action == "edit_start":
        task_id = parts[1]
        await start_edit_start_at(event, user_id, task_id)

    elif action == "edit_end":
        task_id = parts[1]
        await start_edit_end_at(event, user_id, task_id)

    elif action == "open_h5":
        task_id = parts[1]
        await open_h5_webapp(event, user_id, task_id)

    # ============ 时间选择操作 ============
    elif action == "set_interval":
        task_id = parts[1]
        interval = int(parts[2])
        await set_interval(event, user_id, task_id, interval)

    elif action == "set_hour":
        task_id = parts[1]
        is_start = parts[2] == "True"
        hour = int(parts[3])
        await set_hour(event, user_id, task_id, is_start, hour)

    # ============ 账号/目标选择 ============
    elif action == "pick_acc":
        if len(parts) < 2:
            await event.answer("参数错误", alert=True)
            return
        await _handle_pick_account(event, user_id, parts[1])

    elif action == "pick_res":
        if len(parts) < 2:
            await event.answer("参数错误", alert=True)
            return
        await _handle_pick_resource(event, user_id, int(parts[1]))

    elif action == "pick_page":
        if len(parts) < 2:
            await event.answer("参数错误", alert=True)
            return
        ctx = _get_selector_context(user_id)
        if not ctx:
            await event.answer("会话已过期，请重新进入任务设置", alert=True)
            return
        task_id = str(ctx["task_id"])
        page = max(0, int(parts[1]))
        _set_selector_context(
            user_id,
            task_id=task_id,
            account_id=ctx.get("account_id"),
            page=page,
            peer_filter=str(ctx.get("peer_filter") or "all"),
            search=str(ctx.get("search") or ""),
            expect_search=bool(ctx.get("expect_search")),
        )
        await start_select_task_targets(event, user_id, task_id, page=page)

    elif action == "pick_type":
        if len(parts) < 2:
            await event.answer("参数错误", alert=True)
            return
        ctx = _get_selector_context(user_id)
        if not ctx:
            await event.answer("会话已过期，请重新进入任务设置", alert=True)
            return
        peer_filter = _normalize_target_filter(parts[1])
        task_id = str(ctx["task_id"])
        _set_selector_context(
            user_id,
            task_id=task_id,
            account_id=ctx.get("account_id"),
            page=0,
            peer_filter=peer_filter,
            search=str(ctx.get("search") or ""),
            expect_search=False,
        )
        await start_select_task_targets(event, user_id, task_id, page=0)

    elif action == "pick_search":
        ctx = _get_selector_context(user_id)
        if not ctx:
            await event.answer("会话已过期，请重新进入任务设置", alert=True)
            return
        fsm_storage.set_state(user_id, FSMState.WAIT_TARGET_SEARCH)
        _set_selector_context(
            user_id,
            task_id=str(ctx["task_id"]),
            account_id=ctx.get("account_id"),
            page=int(ctx.get("page") or 0),
            peer_filter=str(ctx.get("peer_filter") or "all"),
            search=str(ctx.get("search") or ""),
            expect_search=True,
        )
        fsm_storage.update_data(user_id, task_id=str(ctx["task_id"]))
        await event.respond(
            "🔎 请输入搜索关键词（支持名称/@username/ID）\n"
            "发送 `clear` 可清空搜索，发送 `/cancel` 取消输入。",
            buttons=[[Button.inline("取消搜索输入", data="pick_search_cancel")]],
            parse_mode="markdown",
        )

    elif action == "pick_search_clear":
        ctx = _get_selector_context(user_id)
        if not ctx:
            await event.answer("会话已过期，请重新进入任务设置", alert=True)
            return
        task_id = str(ctx["task_id"])
        _set_selector_context(
            user_id,
            task_id=task_id,
            account_id=ctx.get("account_id"),
            page=0,
            peer_filter=str(ctx.get("peer_filter") or "all"),
            search="",
            expect_search=False,
        )
        await start_select_task_targets(event, user_id, task_id, page=0)

    elif action == "pick_search_cancel":
        fsm_storage.set_state(user_id, FSMState.NONE)
        ctx = _get_selector_context(user_id)
        if not ctx:
            await event.answer("会话已过期，请重新进入任务设置", alert=True)
            return
        task_id = str(ctx["task_id"])
        _set_selector_context(
            user_id,
            task_id=task_id,
            account_id=ctx.get("account_id"),
            page=int(ctx.get("page") or 0),
            peer_filter=str(ctx.get("peer_filter") or "all"),
            search=str(ctx.get("search") or ""),
            expect_search=False,
        )
        await start_select_task_targets(event, user_id, task_id, page=int(ctx.get("page") or 0))

    elif action == "pick_clear":
        await _handle_pick_clear(event, user_id)

    elif action == "pick_done":
        await _handle_pick_done(event, user_id)

    elif action == "pick_noop":
        await event.answer("使用上下页切换资源列表")


# ============ 消息处理（FSM 输入） ============

@bot_client.on(events.NewMessage(func=lambda e: e.sender_id))
async def message_handler(event):
    """处理用户输入消息（FSM 状态）"""
    user_id = event.sender_id
    state = fsm_storage.get_state(user_id)

    if state == FSMState.NONE:
        # 容错：如果搜索输入状态丢失，但选择器上下文仍在，继续按搜索词处理
        selector_ctx = _get_selector_context(user_id)
        if selector_ctx and selector_ctx.get("expect_search"):
            await handle_target_search_input(event, user_id, event.message.message or "")
        return

    # 根据状态处理输入
    data = fsm_storage.get_data(user_id)
    task_id = data.get("task_id")

    if state == FSMState.WAIT_TEXT:
        await handle_text_input(event, user_id, task_id, event.message.message)

    elif state == FSMState.WAIT_MEDIA:
        await handle_media_input(event, user_id, task_id, event.message.media)

    elif state == FSMState.WAIT_BUTTONS:
        await handle_buttons_input(event, user_id, task_id, event.message.message)

    elif state == FSMState.WAIT_START_AT:
        await handle_start_at_input(event, user_id, task_id, event.message.message)

    elif state == FSMState.WAIT_END_AT:
        await handle_end_at_input(event, user_id, task_id, event.message.message)

    elif state == FSMState.WAIT_TARGET_SEARCH:
        await handle_target_search_input(event, user_id, event.message.message or "")


# ============ 任务列表展示 ============

async def _get_user_task(session, task_id: str, user_id: int) -> Optional[ScheduledMessageTask]:
    """按用户范围获取任务"""
    db_user_id = await _resolve_db_user_id(session, user_id)
    if db_user_id is None:
        return None

    result = await session.execute(
        select(ScheduledMessageTask).where(
            ScheduledMessageTask.task_id == task_id,
            ScheduledMessageTask.user_id == db_user_id
        )
    )
    return result.scalar_one_or_none()


async def show_task_list(event, user_id: int):
    """显示任务列表"""
    _clear_selector_context(user_id)
    async with get_async_session() as session:
        db_user_id = await _resolve_db_user_id(session, user_id)
        if db_user_id is None:
            if hasattr(event, "answer"):
                await event.answer(
                    "当前 Telegram 账号未绑定系统用户，请先在 H5 登录并绑定。",
                    alert=True
                )
            else:
                await event.respond(
                    "⚠️ 当前 Telegram 账号未绑定系统用户。\n\n"
                    "请先在 H5 登录并扫码绑定，再使用任务功能。",
                    buttons=_build_login_buttons("🔐 前往 H5 登录")
                )
            return

        result = await session.execute(
            select(ScheduledMessageTask)
            .where(ScheduledMessageTask.user_id == db_user_id)
            .order_by(ScheduledMessageTask.created_at.desc())
        )
        tasks = result.scalars().all()

    if not tasks:
        text = TASK_LIST_HEADER + TASK_EMPTY
        keyboard = [[Button.inline("➕ 添加任务", data="add_task")]]
    else:
        # 构建任务列表数据
        task_data = []
        for task in tasks:
            task_data.append((
                task.task_id,
                task.enabled,
                task.repeat_interval_min,
                task.media_type != MediaType.NONE,
                bool(task.buttons),
                bool(task.text),
                task.title[:30] + "..." if len(task.title) > 30 else task.title
            ))

        text = TASK_LIST_HEADER + f"📊 共 {len(tasks)} 个任务\n"
        keyboard = get_task_list_keyboard(task_data)

    if _should_edit_event(event):
        await event.edit(text, buttons=keyboard, parse_mode='markdown')
    else:
        await event.respond(text, buttons=keyboard, parse_mode='markdown')


# ============ 任务设置展示 ============

async def show_task_settings(event, user_id: int, task_id: str):
    """显示任务设置页"""
    _clear_selector_context(user_id)
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        account = None
        resources_by_key: dict[tuple[str, int], Resource] = {}

        if task and task.account_id:
            account_result = await session.execute(
                select(Account).where(Account.account_id == task.account_id)
            )
            account = account_result.scalar_one_or_none()

            targets = _normalize_task_targets(task)
            peer_ids = list({int(t["peer_id"]) for t in targets})
            if peer_ids:
                resource_result = await session.execute(
                    select(Resource).where(
                        Resource.account_id == task.account_id,
                        Resource.peer_id.in_(peer_ids),
                        Resource.is_active == True,
                    )
                )
                for resource in resource_result.scalars().all():
                    resources_by_key[(str(resource.peer_type), int(resource.peer_id))] = resource

    if not task:
        await event.answer("任务不存在", alert=True)
        return

    account_display = "未设置"
    if account:
        if account.username:
            account_display = f"@{account.username}"
        elif account.phone:
            account_display = account.phone
        else:
            account_display = account.account_id[:8]
    elif task.account_id:
        account_display = task.account_id[:8]

    targets = _normalize_task_targets(task)
    if targets:
        target_items: list[str] = []
        for target in targets[:3]:
            peer_type = str(target["peer_type"])
            peer_id = int(target["peer_id"])
            icon, _ = _peer_meta(peer_type)
            resource = resources_by_key.get((peer_type, peer_id))
            if resource:
                name = resource.title or (f"@{resource.username}" if resource.username else str(peer_id))
            else:
                name = str(peer_id)
            target_items.append(f"{icon}{_truncate_text(name, 16)}")
        target_display = "、".join(target_items)
        if len(targets) > 3:
            target_display += f" 等{len(targets)}个"
    else:
        target_display = "未设置"

    # 构建设置页面文本
    text = TASK_SETTINGS_TEMPLATE.format(
        title=_escape_markdown(task.title),
        enabled_status=STATUS_ENABLED if task.enabled else STATUS_DISABLED,
        interval=task.repeat_interval_min,
        account_display=_escape_markdown(account_display),
        target_display=_escape_markdown(target_display),
        time_range=f"{task.day_start_hour or '-'}:00 - {task.day_end_hour or '-'}:00",
        start_date=_format_timestamp(task.start_at),
        end_date=_format_timestamp(task.end_at),
        text_status=STATUS_HAS if task.text else STATUS_NOT_SET,
        media_status=task.media_type.value if task.media_type != MediaType.NONE else "无",
        buttons_status=STATUS_HAS if task.buttons else STATUS_NOT_SET,
        delete_status=STATUS_YES if task.delete_previous else STATUS_NO,
        pin_status=STATUS_YES if task.pin_message else STATUS_NO,
    )

    keyboard = get_task_settings_keyboard(task)
    keyboard.append([Button.inline(OPEN_H5_BUTTON, data=f"open_h5:{task_id}")])

    if _should_edit_event(event):
        await event.edit(text, buttons=keyboard, parse_mode='markdown')
    else:
        await event.respond(text, buttons=keyboard, parse_mode='markdown')


# ============ 账号/目标选择 ============

def _build_account_picker_keyboard(
    *,
    task_id: str,
    accounts: list[Account],
    current_account_id: Optional[str],
) -> list:
    buttons = []
    for account in accounts:
        checked = "✅" if account.account_id == current_account_id else "▫️"
        display_name = (
            f"@{account.username}"
            if account.username
            else (account.phone or account.account_id[:8])
        )
        label = f"{checked} {_truncate_text(display_name, 24)}"
        buttons.append([Button.inline(label, data=f"pick_acc:{account.account_id}")])

    buttons.append([Button.inline("⬅️ 返回设置", data=f"settings:{task_id}")])
    return buttons


def _build_target_picker_keyboard(
    *,
    task_id: str,
    resources: list[Resource],
    selected_keys: set[tuple[str, int]],
    page: int,
    peer_filter: str,
    search_query: str,
) -> tuple[list, int, int]:
    total_pages = max(1, (len(resources) + _TARGET_PAGE_SIZE - 1) // _TARGET_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * _TARGET_PAGE_SIZE
    end = start + _TARGET_PAGE_SIZE
    page_items = resources[start:end]

    buttons = []
    peer_filter = _normalize_target_filter(peer_filter)

    filter_row = []
    filter_items = [
        ("all", "🌐 全部"),
        ("user", "👤 个人"),
        ("group", "👥 群聊"),
        ("channel", "📢 频道"),
    ]
    for value, label in filter_items:
        prefix = "✅" if peer_filter == value else "▫️"
        filter_row.append(Button.inline(f"{prefix}{label}", data=f"pick_type:{value}"))
    buttons.append(filter_row)

    if (search_query or "").strip():
        preview = _truncate_text((search_query or "").strip(), 14)
        buttons.append([
            Button.inline(f"🔎 {preview}", data="pick_noop"),
            Button.inline("❌ 清除搜索", data="pick_search_clear"),
            Button.inline("✏️ 重新搜索", data="pick_search"),
        ])
    else:
        buttons.append([
            Button.inline("🔎 搜索", data="pick_search"),
        ])

    for resource in page_items:
        key = (str(resource.peer_type), int(resource.peer_id))
        checked = "✅" if key in selected_keys else "▫️"
        icon, _ = _peer_meta(resource.peer_type)
        display_name = (
            (resource.title or "").strip()
            or (f"@{resource.username}" if resource.username else f"ID:{resource.peer_id}")
        )
        label = f"{checked} {icon} {_truncate_text(display_name, 18)}"
        buttons.append([Button.inline(label, data=f"pick_res:{resource.resource_id}")])

    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(Button.inline("⬅️ 上一页", data=f"pick_page:{page - 1}"))
        nav_row.append(Button.inline(f"📄 {page + 1}/{total_pages}", data="pick_noop"))
        if page < total_pages - 1:
            nav_row.append(Button.inline("下一页 ➡️", data=f"pick_page:{page + 1}"))
        buttons.append(nav_row)

    buttons.append([
        Button.inline(f"✅ 完成 ({len(selected_keys)})", data="pick_done"),
        Button.inline("🧹 清空", data="pick_clear"),
    ])
    buttons.append([Button.inline("⬅️ 返回设置", data=f"settings:{task_id}")])
    return buttons, page, total_pages


async def start_select_task_account(event, user_id: int, task_id: str):
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        db_user_id = await _resolve_db_user_id(session, user_id)
        if db_user_id is None:
            await event.answer("未找到系统用户，请先绑定", alert=True)
            return

        result = await session.execute(
            select(Account)
            .where(
                Account.user_id == db_user_id,
                Account.is_active == True,
            )
            .order_by(Account.created_at.desc())
        )
        accounts = result.scalars().all()

    if not task:
        await event.answer("任务不存在", alert=True)
        return

    if not accounts:
        await event.answer("暂无可用账号，请先在 H5 绑定并启用账号", alert=True)
        return

    _set_selector_context(
        user_id,
        task_id=task_id,
        account_id=task.account_id,
        page=0,
        peer_filter="all",
        search="",
    )
    text = (
        "👤 **请选择执行账号**\n\n"
        "选择后将进入目标聊天多选。若切换账号，原目标聊天将被清空。"
    )
    keyboard = _build_account_picker_keyboard(
        task_id=task_id,
        accounts=accounts,
        current_account_id=task.account_id,
    )
    if _should_edit_event(event):
        await event.edit(text, buttons=keyboard, parse_mode="markdown")
    else:
        await event.respond(text, buttons=keyboard, parse_mode="markdown")


async def start_select_task_targets(event, user_id: int, task_id: str, page: int = 0):
    ctx = _get_selector_context(user_id) or {}
    peer_filter = _normalize_target_filter(ctx.get("peer_filter"))
    search_query = str(ctx.get("search") or "").strip()

    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if not task:
            await event.answer("任务不存在", alert=True)
            return

        if not task.account_id:
            await event.answer("请先选择执行账号", alert=True)
            await start_select_task_account(event, user_id, task_id)
            return

        resource_result = await session.execute(
            select(Resource)
            .where(
                Resource.account_id == task.account_id,
                Resource.is_active == True,
            )
            .order_by(Resource.title.asc().nullslast(), Resource.resource_id.asc())
        )
        all_resources = resource_result.scalars().all()
        resources = _filter_target_resources(
            all_resources,
            peer_filter=peer_filter,
            search_query=search_query,
        )

        selected_targets = _normalize_task_targets(task)
        selected_keys = {
            (str(item["peer_type"]), int(item["peer_id"]))
            for item in selected_targets
        }

    keyboard, page, total_pages = _build_target_picker_keyboard(
        task_id=task_id,
        resources=resources,
        selected_keys=selected_keys,
        page=page,
        peer_filter=peer_filter,
        search_query=search_query,
    )
    _set_selector_context(
        user_id,
        task_id=task_id,
        account_id=task.account_id,
        page=page,
        peer_filter=peer_filter,
        search=search_query,
    )

    text = (
        "🎯 **选择目标聊天（支持多选）**\n\n"
        f"已选择: {len(selected_keys)} 个\n"
        f"类型筛选: {_target_filter_label(peer_filter)}\n"
        f"关键词: {_escape_markdown(search_query or '无')}\n"
        f"第 {page + 1}/{total_pages} 页，每页 {_TARGET_PAGE_SIZE} 条"
    )
    if not resources:
        text += "\n\n⚠️ 当前筛选条件下没有可选聊天，请调整筛选或搜索词。"
    if _should_edit_event(event):
        await event.edit(text, buttons=keyboard, parse_mode="markdown")
    else:
        await event.respond(text, buttons=keyboard, parse_mode="markdown")


async def _handle_pick_account(event, user_id: int, account_id: str):
    ctx = _get_selector_context(user_id)
    if not ctx:
        await event.answer("会话已过期，请重新进入任务设置", alert=True)
        return

    task_id = str(ctx["task_id"])
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        db_user_id = await _resolve_db_user_id(session, user_id)
        if not task or db_user_id is None:
            await event.answer("任务不存在或无权限", alert=True)
            return

        account_result = await session.execute(
            select(Account).where(
                Account.account_id == account_id,
                Account.user_id == db_user_id,
                Account.is_active == True,
            )
        )
        account = account_result.scalar_one_or_none()
        if not account:
            await event.answer("账号不存在或不可用", alert=True)
            return

        account_changed = task.account_id != account_id
        task.account_id = account_id
        if account_changed:
            _apply_task_targets(task, [])
        await session.commit()

    await event.answer("已选择执行账号")
    _set_selector_context(
        user_id,
        task_id=task_id,
        account_id=account_id,
        page=0,
        peer_filter="all",
        search="",
    )
    await start_select_task_targets(event, user_id, task_id, page=0)


async def _handle_pick_resource(event, user_id: int, resource_id: int):
    ctx = _get_selector_context(user_id)
    if not ctx:
        await event.answer("会话已过期，请重新进入任务设置", alert=True)
        return

    task_id = str(ctx["task_id"])
    page = int(ctx.get("page") or 0)

    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if not task or not task.account_id:
            await event.answer("请先选择执行账号", alert=True)
            return

        resource_result = await session.execute(
            select(Resource).where(
                Resource.resource_id == resource_id,
                Resource.account_id == task.account_id,
                Resource.is_active == True,
            )
        )
        resource = resource_result.scalar_one_or_none()
        if not resource:
            await event.answer("目标聊天不存在或已失效", alert=True)
            return

        targets = _normalize_task_targets(task)
        key = (str(resource.peer_type), int(resource.peer_id))
        existing_keys = {(str(t["peer_type"]), int(t["peer_id"])) for t in targets}

        if key in existing_keys:
            targets = [
                t for t in targets
                if (str(t["peer_type"]), int(t["peer_id"])) != key
            ]
            await event.answer("已取消选择")
        else:
            targets.append({
                "peer_id": int(resource.peer_id),
                "peer_type": str(resource.peer_type),
                "access_hash": resource.access_hash,
            })
            await event.answer("已加入目标")

        _apply_task_targets(task, targets)
        await session.commit()

    await start_select_task_targets(event, user_id, task_id, page=page)


async def _handle_pick_clear(event, user_id: int):
    ctx = _get_selector_context(user_id)
    if not ctx:
        await event.answer("会话已过期，请重新进入任务设置", alert=True)
        return

    task_id = str(ctx["task_id"])
    page = int(ctx.get("page") or 0)

    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if not task:
            await event.answer("任务不存在", alert=True)
            return
        _apply_task_targets(task, [])
        await session.commit()

    await event.answer("已清空目标")
    await start_select_task_targets(event, user_id, task_id, page=page)


async def _handle_pick_done(event, user_id: int):
    ctx = _get_selector_context(user_id)
    if not ctx:
        await event.answer("会话已过期，请重新进入任务设置", alert=True)
        return

    task_id = str(ctx["task_id"])
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if not task:
            await event.answer("任务不存在", alert=True)
            return
        targets = _normalize_task_targets(task)

    if not targets:
        await event.answer("请至少选择一个目标聊天", alert=True)
        return

    _clear_selector_context(user_id)
    await event.answer(f"已保存 {len(targets)} 个目标")
    await show_task_settings(event, user_id, task_id)


async def handle_target_search_input(event, user_id: int, text: str):
    """处理目标聊天搜索输入"""
    ctx = _get_selector_context(user_id)
    if not ctx:
        fsm_storage.set_state(user_id, FSMState.NONE)
        await event.respond("⚠️ 选择会话已过期，请重新进入任务设置")
        return

    keyword = (text or "").strip()
    logger.info(
        f"目标搜索输入: user_id={user_id}, state={fsm_storage.get_state(user_id)}, raw={keyword!r}"
    )
    if keyword.lower() in {"cancel", "/cancel"}:
        fsm_storage.set_state(user_id, FSMState.NONE)
        _set_selector_context(
            user_id,
            task_id=str(ctx["task_id"]),
            account_id=ctx.get("account_id"),
            page=int(ctx.get("page") or 0),
            peer_filter=str(ctx.get("peer_filter") or "all"),
            search=str(ctx.get("search") or ""),
            expect_search=False,
        )
        await start_select_task_targets(
            event,
            user_id,
            str(ctx["task_id"]),
            page=int(ctx.get("page") or 0),
        )
        return

    # 兼容用户习惯：/狼、/@name 也按关键词处理
    if keyword.startswith("/"):
        keyword = keyword.lstrip("/")

    if keyword.lower() in {"clear", "清空"}:
        keyword = ""

    if len(keyword) > 32:
        await event.respond("关键词过长，请控制在 32 个字符以内")
        return

    fsm_storage.set_state(user_id, FSMState.NONE)
    _set_selector_context(
        user_id,
        task_id=str(ctx["task_id"]),
        account_id=ctx.get("account_id"),
        page=0,
        peer_filter=str(ctx.get("peer_filter") or "all"),
        search=keyword,
    )
    await start_select_task_targets(event, user_id, str(ctx["task_id"]), page=0)


# ============ 任务操作 ============

async def create_new_task(event, user_id: int):
    """创建新任务"""
    import uuid
    task_id = str(uuid.uuid4())

    async with get_async_session() as session:
        db_user_id = await _resolve_db_user_id(session, user_id)
        if db_user_id is None:
            await event.answer("未找到对应系统用户，请先完成绑定", alert=True)
            return

        task = ScheduledMessageTask(
            task_id=task_id,
            user_id=db_user_id,
            chat_id=None,
            title="新任务",
            repeat_interval_min=60,
            enabled=False,
            next_run_at=int(datetime.now().timestamp()) + 3600,
        )
        session.add(task)
        await session.commit()

    await start_select_task_account(event, user_id, task_id)


async def toggle_task(event, user_id: int, task_id: str):
    """切换任务启用状态"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)

        if task:
            task.enabled = not task.enabled
            if task.enabled and task.next_run_at is None:
                now_ts = int(datetime.now().timestamp())
                start_at_ts = int(task.start_at or 0)
                task.next_run_at = max(now_ts, start_at_ts) if start_at_ts > 0 else now_ts
            await session.commit()
            await event.answer(f"任务已{'启用' if task.enabled else '禁用'}")
            await show_task_list(event, user_id)


async def confirm_delete_task(event, user_id: int, task_id: str):
    """确认删除任务"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)

        if task:
            text = CONFIRM_DELETE.format(title=task.title)
            keyboard = get_confirm_delete_keyboard(task_id)
            await event.edit(text, buttons=keyboard, parse_mode='markdown')


async def delete_task(event, user_id: int, task_id: str):
    """删除任务"""
    async with get_async_session() as session:
        db_user_id = await _resolve_db_user_id(session, user_id)
        if db_user_id is None:
            await event.answer("未找到对应系统用户，请先完成绑定", alert=True)
            return

        from sqlalchemy import delete
        await session.execute(
            delete(ScheduledMessageTask).where(
                ScheduledMessageTask.task_id == task_id,
                ScheduledMessageTask.user_id == db_user_id
            )
        )
        await session.commit()

    await event.answer("任务已删除")
    await show_task_list(event, user_id)


async def update_task_enabled(event, user_id: int, task_id: str, enabled: bool):
    """更新任务启用状态"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)

        if task:
            task.enabled = enabled
            if enabled and task.next_run_at is None:
                now_ts = int(datetime.now().timestamp())
                start_at_ts = int(task.start_at or 0)
                task.next_run_at = max(now_ts, start_at_ts) if start_at_ts > 0 else now_ts
            await session.commit()
            await event.answer(SUCCESS_TASK_ENABLED if enabled else SUCCESS_TASK_DISABLED)
            await show_task_settings(event, user_id, task_id)


async def toggle_delete_previous(event, user_id: int, task_id: str):
    """切换删除上一条设置"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)

        if task:
            task.delete_previous = not task.delete_previous
            await session.commit()
            await show_task_settings(event, user_id, task_id)


async def toggle_pin_message(event, user_id: int, task_id: str):
    """切换置顶设置"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)

        if task:
            task.pin_message = not task.pin_message
            await session.commit()
            await show_task_settings(event, user_id, task_id)


# ============ 编辑功能 ============

async def start_edit_text(event, user_id: int, task_id: str):
    """开始编辑文本"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)

        if not task:
            return

    fsm_storage.set_state(user_id, FSMState.WAIT_TEXT)
    fsm_storage.update_data(user_id, task_id=task_id)

    text = EDIT_TEXT_PROMPT.format(text=task.text or "（无）")
    keyboard = get_cancel_keyboard(task_id)
    await event.edit(text, buttons=keyboard, parse_mode='markdown')


async def handle_text_input(event, user_id: int, task_id: str, text: str):
    """处理文本输入"""
    if len(text) > 4096:
        await event.respond(ERROR_TEXT_TOO_LONG)
        return

    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)

        if task:
            task.text = text
            await session.commit()

    fsm_storage.reset_state(user_id)
    await event.respond(SUCCESS_TEXT_UPDATED)
    await show_task_settings(event, user_id, task_id)


async def start_edit_media(event, user_id: int, task_id: str):
    """开始编辑媒体"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)

        if not task:
            return

    fsm_storage.set_state(user_id, FSMState.WAIT_MEDIA)
    fsm_storage.update_data(user_id, task_id=task_id)

    media_status = task.media_type.value if task.media_type != MediaType.NONE else "无"
    text = EDIT_MEDIA_PROMPT.format(current_media=media_status)
    keyboard = get_cancel_keyboard(task_id)
    await event.edit(text, buttons=keyboard, parse_mode='markdown')


async def handle_media_input(event, user_id: int, task_id: str, media):
    """处理媒体输入"""
    media_type = MediaType.NONE
    file_id = None

    if isinstance(media, MessageMediaPhoto):
        media_type = MediaType.PHOTO
        file_id = media.photo.id
    elif isinstance(media, MessageMediaDocument):
        # 检测文档类型
        for attr in media.document.attributes:
            if hasattr(attr, 'video'):
                media_type = MediaType.VIDEO
            elif hasattr(attr, 'animated'):
                media_type = MediaType.ANIMATION
        file_id = media.document.id

    if media_type == MediaType.NONE:
        await event.respond(ERROR_INVALID_MEDIA)
        return

    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)

        if task:
            task.media_type = media_type
            task.media_file_id = str(file_id)
            await session.commit()

    fsm_storage.reset_state(user_id)
    await event.respond(SUCCESS_MEDIA_UPDATED)
    await show_task_settings(event, user_id, task_id)


async def start_edit_buttons(event, user_id: int, task_id: str):
    """开始编辑按钮"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)

        if not task:
            return

    fsm_storage.set_state(user_id, FSMState.WAIT_BUTTONS)
    fsm_storage.update_data(user_id, task_id=task_id)

    current_buttons = _format_buttons(task.buttons) if task.buttons else "无"
    text = EDIT_BUTTONS_PROMPT.format(current_buttons=current_buttons)
    keyboard = get_cancel_keyboard(task_id)
    await event.edit(text, buttons=keyboard, parse_mode='markdown')


async def handle_buttons_input(event, user_id: int, task_id: str, text: str):
    """处理按钮输入"""
    try:
        buttons = parse_buttons(text)

        async with get_async_session() as session:
            task = await _get_user_task(session, task_id, user_id)

            if task:
                task.buttons = buttons
                await session.commit()

        fsm_storage.reset_state(user_id)
        await event.respond(SUCCESS_BUTTONS_UPDATED)
        await show_task_settings(event, user_id, task_id)

    except Exception as e:
        await event.respond(f"{ERROR_INVALID_BUTTON_FORMAT}\n错误: {str(e)}")


async def show_interval_selection(event, user_id: int, task_id: str):
    """显示间隔时间选择"""
    keyboard = get_interval_keyboard(task_id)
    text = SELECT_INTERVAL
    await event.edit(text, buttons=keyboard, parse_mode='markdown')


async def set_interval(event, user_id: int, task_id: str, interval: int):
    """设置重复间隔"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)

        if task:
            task.repeat_interval_min = interval
            if task.enabled:
                now_ts = int(datetime.now().timestamp())
                start_at_ts = int(task.start_at or 0)
                task.next_run_at = max(now_ts + interval * 60, start_at_ts) if start_at_ts > 0 else now_ts + interval * 60
            await session.commit()
            await event.answer(SUCCESS_INTERVAL_UPDATED.format(interval=interval))
            await show_task_settings(event, user_id, task_id)


async def start_edit_hours(event, user_id: int, task_id: str):
    """开始编辑时段"""
    fsm_storage.set_state(user_id, FSMState.WAIT_DAY_START)
    fsm_storage.update_data(user_id, task_id=task_id)

    keyboard = get_hour_select_keyboard(task_id, for_start=True)
    text = SELECT_START_HOUR
    await event.edit(text, buttons=keyboard, parse_mode='markdown')


async def set_hour(event, user_id: int, task_id: str, is_start: bool, hour: int):
    """设置小时"""
    state = fsm_storage.get_state(user_id)
    data = fsm_storage.get_data(user_id)

    if is_start:
        # 设置开始时间，然后询问结束时间
        fsm_storage.set_state(user_id, FSMState.WAIT_DAY_END)
        fsm_storage.update_data(user_id, day_start_hour=hour)

        keyboard = get_hour_select_keyboard(task_id, for_start=False)
        text = SELECT_END_HOUR
        await event.edit(text, buttons=keyboard, parse_mode='markdown')
    else:
        # 设置结束时间，保存
        day_start_hour = data.get("day_start_hour")
        day_end_hour = hour

        async with get_async_session() as session:
            task = await _get_user_task(session, task_id, user_id)

            if task:
                task.day_start_hour = day_start_hour
                task.day_end_hour = day_end_hour
                await session.commit()

        fsm_storage.reset_state(user_id)
        await event.answer(
            SUCCESS_TIME_RANGE_UPDATED.format(start=day_start_hour, end=day_end_hour)
        )
        await show_task_settings(event, user_id, task_id)


async def start_edit_start_at(event, user_id: int, task_id: str):
    """开始编辑开始时间"""
    fsm_storage.set_state(user_id, FSMState.WAIT_START_AT)
    fsm_storage.update_data(user_id, task_id=task_id)

    text = EDIT_START_AT_PROMPT
    keyboard = get_cancel_keyboard(task_id)
    await event.edit(text, buttons=keyboard, parse_mode='markdown')


async def handle_start_at_input(event, user_id: int, task_id: str, text: str):
    """处理开始时间输入"""
    try:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
        timestamp = int(dt.timestamp())

        async with get_async_session() as session:
            task = await _get_user_task(session, task_id, user_id)

            if task:
                # 检查是否早于结束时间
                if task.end_at and timestamp >= task.end_at:
                    await event.respond(ERROR_END_BEFORE_START)
                    return

                task.start_at = timestamp
                await session.commit()

        fsm_storage.reset_state(user_id)
        await event.respond(SUCCESS_START_AT_UPDATED)
        await show_task_settings(event, user_id, task_id)

    except ValueError:
        await event.respond(ERROR_INVALID_TIME_FORMAT)


async def start_edit_end_at(event, user_id: int, task_id: str):
    """开始编辑结束时间"""
    fsm_storage.set_state(user_id, FSMState.WAIT_END_AT)
    fsm_storage.update_data(user_id, task_id=task_id)

    text = EDIT_END_AT_PROMPT
    keyboard = get_cancel_keyboard(task_id)
    await event.edit(text, buttons=keyboard, parse_mode='markdown')


async def handle_end_at_input(event, user_id: int, task_id: str, text: str):
    """处理结束时间输入"""
    try:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
        timestamp = int(dt.timestamp())

        async with get_async_session() as session:
            task = await _get_user_task(session, task_id, user_id)

            if task:
                # 检查是否早于开始时间
                if task.start_at and timestamp <= task.start_at:
                    await event.respond(ERROR_END_BEFORE_START)
                    return

                task.end_at = timestamp
                await session.commit()

        fsm_storage.reset_state(user_id)
        await event.respond(SUCCESS_END_AT_UPDATED)
        await show_task_settings(event, user_id, task_id)

    except ValueError:
        await event.respond(ERROR_INVALID_TIME_FORMAT)


async def open_h5_webapp(event, user_id: int, task_id: str):
    """打开 H5 控制台"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if not task:
            await event.answer("任务不存在或无权限", alert=True)
            return

    # 统一前端入口，使用 SPA 路由并携带 task_id 供前端定位
    url = generate_h5_url(task_id)

    # 使用 WebApp 或直接发送链接
    await event.answer(f"🌐 请点击下方链接进入 H5 控制台:\n{url}", alert=True)


# ============ 辅助函数 ============

def _format_timestamp(ts: Optional[int]) -> str:
    """格式化时间戳"""
    if ts is None:
        return "未设置"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _format_buttons(buttons) -> str:
    """格式化按钮显示"""
    if not buttons:
        return "无"

    lines = []
    for row in buttons:
        btn_texts = [btn.get("text", "") for btn in row]
        lines.append(" | ".join(btn_texts))

    return "\n".join(lines)


def parse_buttons(text: str) -> list:
    """解析按钮输入"""
    buttons = []

    for line in text.strip().split("\n"):
        row = []
        parts = line.split("&&")

        for part in parts:
            part = part.strip()
            if " - " not in part:
                raise ValueError(f"按钮格式错误: {part}")

            btn_text, url = part.split(" - ", 1)
            btn_text = btn_text.strip()
            url = url.strip()

            # 自动补全 https
            if not url.startswith("http://") and not url.startswith("https://"):
                url = "https://" + url

            row.append({"text": btn_text, "url": url})

        if row:
            buttons.append(row)

    if len(buttons) > 3:
        raise ValueError("最多支持 3 行按钮")

    for row in buttons:
        if len(row) > 3:
            raise ValueError("每行最多 3 个按钮")

    return buttons


def generate_h5_url(task_id: str) -> str:
    """生成 H5 访问 URL（统一跳转到 SPA 任务页）"""
    base = _normalize_h5_base_url() or "http://localhost:8000"
    return f"{base}/tasks?task_id={task_id}"
