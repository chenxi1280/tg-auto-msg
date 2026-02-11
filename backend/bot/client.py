"""
Telegram 客户端初始化

支持两种登录方式：
1. 二维码登录（推荐）：通过 H5 页面扫码登录
2. 验证码登录：通过手机号和验证码登录
"""
import asyncio
import time
from typing import Optional, Any
from pathlib import Path
from telethon import TelegramClient
from telethon.sessions import StringSession
from loguru import logger
from sqlalchemy import select

from backend.config.settings import settings
from backend.bot.redis_login_manager import RedisLoginManager, LoginStatus
from backend.database.session import get_async_session
from backend.database.models import SystemSession
from backend.utils.crypto import encrypt_string_session, decrypt_string_session


# 系统级会话键
_SYSTEM_BOT_SESSION_KEY = "manager_bot"
_SYSTEM_USERBOT_SESSION_KEY = "global_userbot"
_LEGACY_SESSION_FILES = (
    "bot_session.session",
    "bot_session.session-journal",
    "userbot_session.session",
    "userbot_session.session-journal",
)

# Bot 客户端（用于接收命令和按钮交互）
bot_client = TelegramClient(
    StringSession(),
    api_id=settings.api_id,
    api_hash=settings.api_hash,
)

# Userbot 客户端（用于实际发送消息）
userbot_client = TelegramClient(
    StringSession(),
    api_id=settings.api_id,
    api_hash=settings.api_hash,
)

# 当前正在进行的二维码登录会话
_current_qr_login_id: Optional[str] = None


def _extract_expected_bot_id(bot_token: str) -> Optional[int]:
    """从 Bot Token 提取预期 bot_id。"""
    if not bot_token:
        return None
    try:
        return int(str(bot_token).split(":", 1)[0])
    except Exception:
        return None


def _build_session_meta(extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    meta = {"updated_at": int(time.time())}
    if extra:
        meta.update(extra)
    return meta


async def _load_system_session_string(session_key: str) -> Optional[str]:
    """从数据库加载并解密系统会话字符串。"""
    try:
        async with get_async_session() as session:
            result = await session.execute(
                select(SystemSession).where(SystemSession.session_key == session_key)
            )
            row = result.scalar_one_or_none()
            if not row or not row.session_encrypted:
                return None

            try:
                return decrypt_string_session(row.session_encrypted)
            except Exception as e:
                logger.error(f"系统会话解密失败，已清理损坏记录: key={session_key}, error={e}")
                await session.delete(row)
                return None
    except Exception as e:
        logger.warning(f"读取系统会话失败: key={session_key}, error={e}")
        return None


async def _save_system_session_string(
    session_key: str,
    session_string: str,
    *,
    session_meta: Optional[dict[str, Any]] = None,
) -> None:
    """将系统会话字符串加密后写入数据库。"""
    if not session_string:
        return

    encrypted = encrypt_string_session(session_string)
    meta = _build_session_meta(session_meta)

    try:
        async with get_async_session() as session:
            row = await session.get(SystemSession, session_key)
            if row is None:
                row = SystemSession(
                    session_key=session_key,
                    session_encrypted=encrypted,
                    session_meta=meta,
                )
                session.add(row)
            else:
                row.session_encrypted = encrypted
                row.session_meta = meta
    except Exception as e:
        logger.warning(f"保存系统会话失败: key={session_key}, error={e}")


async def _delete_system_session(session_key: str) -> None:
    """删除数据库中的系统会话。"""
    try:
        async with get_async_session() as session:
            row = await session.get(SystemSession, session_key)
            if row is not None:
                await session.delete(row)
    except Exception as e:
        logger.warning(f"删除系统会话失败: key={session_key}, error={e}")


async def _restore_client_session(client: TelegramClient, session_key: str) -> None:
    """
    从数据库恢复客户端 Session。
    仅在未连接时调用，避免运行中切换 session。
    """
    if client.is_connected():
        return

    session_string = await _load_system_session_string(session_key)
    if not session_string:
        return

    try:
        client.session = StringSession(session_string)
        logger.info(f"已从数据库恢复系统会话: {session_key}")
    except Exception as e:
        logger.warning(f"恢复系统会话失败: key={session_key}, error={e}")


async def _persist_client_session(
    client: TelegramClient,
    session_key: str,
    *,
    session_meta: Optional[dict[str, Any]] = None,
) -> None:
    """将当前客户端 Session 持久化到数据库。"""
    try:
        session_string = StringSession.save(client.session)
    except Exception as e:
        logger.warning(f"导出客户端会话失败: key={session_key}, error={e}")
        return

    if not session_string:
        return
    await _save_system_session_string(
        session_key,
        session_string,
        session_meta=session_meta,
    )


def _cleanup_legacy_session_files() -> None:
    """清理历史 SQLite .session 文件，避免误判仍在使用本地会话。"""
    for filename in _LEGACY_SESSION_FILES:
        path = Path(filename)
        if not path.exists():
            continue
        try:
            path.unlink()
            logger.info(f"已清理历史本地会话文件: {filename}")
        except Exception as e:
            logger.warning(f"清理历史本地会话文件失败: {filename}, error={e}")


async def start_manager_bot(bot_token: str):
    """
    启动管理 Bot，并确保会话与当前 BOT_TOKEN 一致。

    Telethon 在已有授权会话时会忽略新 bot_token。
    因此当会话 bot_id 与 token 不一致时，清理并重建数据库会话后重新登录。
    """
    expected_bot_id = _extract_expected_bot_id(bot_token)
    current_me = None

    _cleanup_legacy_session_files()

    if not bot_client.is_connected():
        await _restore_client_session(bot_client, _SYSTEM_BOT_SESSION_KEY)
        await bot_client.connect()

    try:
        if await bot_client.is_user_authorized():
            current_me = await bot_client.get_me()
    except Exception as e:
        logger.warning(f"读取当前 bot 会话失败，将继续使用 token 重新登录: {e}")

    if current_me and expected_bot_id and int(current_me.id) != int(expected_bot_id):
        logger.warning(
            "检测到 BOT_TOKEN 与已持久化 bot 会话不一致，正在重建会话: "
            f"session_bot_id={current_me.id}, token_bot_id={expected_bot_id}"
        )
        try:
            await bot_client.disconnect()
        except Exception as e:
            logger.warning(f"断开旧 bot 会话失败: {e}")
        await _delete_system_session(_SYSTEM_BOT_SESSION_KEY)
        bot_client.session = StringSession()
        await bot_client.connect()

    await bot_client.start(bot_token=bot_token)
    me = await bot_client.get_me()
    await _persist_client_session(
        bot_client,
        _SYSTEM_BOT_SESSION_KEY,
        session_meta={
            "bot_id": int(me.id),
            "username": me.username or "",
        },
    )
    return me


async def init_userbot():
    """初始化 Userbot 客户端"""
    _cleanup_legacy_session_files()

    # 先连接客户端
    if not userbot_client.is_connected():
        await _restore_client_session(userbot_client, _SYSTEM_USERBOT_SESSION_KEY)
        await userbot_client.connect()

    # 检查是否已授权
    if await userbot_client.is_user_authorized():
        # 获取当前用户信息
        me = await userbot_client.get_me()
        await _persist_client_session(
            userbot_client,
            _SYSTEM_USERBOT_SESSION_KEY,
            session_meta={
                "tg_user_id": int(me.id),
                "username": me.username or "",
                "phone": me.phone or "",
            },
        )
        logger.info(f"Userbot 已登录: {me.first_name} (@{me.username})")
        return True

    # 未授权，等待用户通过 H5 页面扫码登录
    logger.info("Userbot 未登录，请通过 H5 页面扫码登录")
    return False


async def start_qr_login(login_id: str) -> bool:
    """
    开始二维码登录流程

    Args:
        login_id: 登录会话 ID

    Returns:
        bool: 是否成功启动登录流程
    """
    global _current_qr_login_id

    # 使用 RedisLoginManager
    redis_manager = RedisLoginManager()
    session = await redis_manager.get_session(login_id)
    if not session:
        logger.error(f"登录会话无效或已过期: {login_id}")
        await redis_manager.update_status(login_id, LoginStatus.ERROR, error="会话无效或已过期")
        return False

    try:
        # 连接客户端
        if not userbot_client.is_connected():
            await userbot_client.connect()

        # 检查是否已登录
        if await userbot_client.is_user_authorized():
            me = await userbot_client.get_me()
            string_session = StringSession.save(userbot_client.session)
            string_session_encrypted = encrypt_string_session(string_session)
            await _persist_client_session(
                userbot_client,
                _SYSTEM_USERBOT_SESSION_KEY,
                session_meta={
                    "tg_user_id": int(me.id),
                    "username": me.username or "",
                    "phone": me.phone or "",
                },
            )
            bind_code = await redis_manager.save_string_session(
                login_id=login_id,
                string_session=string_session_encrypted,
                tg_user_id=me.id,
                username=me.username or me.first_name or "",
                phone=me.phone or ""
            )
            logger.info(f"Userbot 已登录: {me.first_name}, bind_code={bind_code}")
            return True

        # 开始二维码登录流程
        logger.info(f"开始二维码登录流程: {login_id}")
        _current_qr_login_id = login_id

        # 使用 Telethon 的 QR 登录功能
        qr_login = await userbot_client.qr_login()

        # 保存 QR URL 到 Redis
        await redis_manager.update_qr_url(login_id, qr_login.url)
        logger.info(f"QR URL 已保存: {qr_login.url}")

        # 获取二维码并更新会话
        await redis_manager.update_status(login_id, LoginStatus.PENDING)

        # 启动后台任务等待登录结果
        asyncio.create_task(_wait_for_qr_login(login_id, qr_login))

        return True

    except Exception as e:
        error_msg = str(e)
        logger.error(f"启动二维码登录失败: {error_msg}")
        await redis_manager.update_status(login_id, LoginStatus.ERROR, error=error_msg)
        return False


def generate_bind_code() -> str:
    """生成 6 位数字绑定码"""
    import random
    return ''.join([str(random.randint(0, 9)) for _ in range(6)])


async def _wait_for_qr_login(
    login_id: str,
    qr_login,
    login_client: Optional[TelegramClient] = None
):
    """
    等待二维码登录完成

    Args:
        login_id: 登录会话 ID
        qr_login: Telethon QR 登录对象
    """
    global _current_qr_login_id

    active_client = login_client or userbot_client

    # 使用 RedisLoginManager
    redis_manager = RedisLoginManager()

    try:
        # 更新状态为等待扫码
        await redis_manager.update_status(login_id, LoginStatus.SCANNING)

        deadline = time.monotonic() + 300  # 总超时 5 分钟
        refresh_attempts = 0

        async def refresh_qr(reason: str) -> bool:
            """
            刷新二维码。
            优先使用 recreate()，失败则退化为重新发起 qr_login()。
            """
            nonlocal qr_login, refresh_attempts

            last_error: Optional[Exception] = None

            # 策略1：在原 QR 会话上 recreate
            try:
                qr_login = await qr_login.recreate()
                await redis_manager.update_qr_url(login_id, qr_login.url)
                await redis_manager.update_status(login_id, LoginStatus.SCANNING, error="")
                refresh_attempts += 1
                logger.info(f"二维码已刷新({reason}): {login_id}, attempt={refresh_attempts}, strategy=recreate")
                return True
            except Exception as e:
                last_error = e

            # 策略2：重新创建 QR 登录对象
            try:
                qr_login = await active_client.qr_login()
                await redis_manager.update_qr_url(login_id, qr_login.url)
                await redis_manager.update_status(login_id, LoginStatus.SCANNING, error="")
                refresh_attempts += 1
                logger.info(f"二维码已刷新({reason}): {login_id}, attempt={refresh_attempts}, strategy=new")
                return True
            except Exception as e:
                last_error = e

            error_msg = str(last_error) if last_error else "二维码刷新失败"
            logger.error(f"刷新二维码失败: {error_msg}")
            await redis_manager.update_status(login_id, LoginStatus.ERROR, error=error_msg)
            return False

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                await redis_manager.update_status(login_id, LoginStatus.EXPIRED)
                logger.error(f"二维码登录超时: {login_id}")
                return

            try:
                # 单次等待不超过 60 秒，便于刷新二维码
                result = await asyncio.wait_for(qr_login.wait(), timeout=min(60, remaining))
            except asyncio.TimeoutError:
                # 超时未扫码，刷新二维码
                refreshed = await refresh_qr(reason="timeout")
                if not refreshed:
                    return
                continue
            except Exception as e:
                error_msg = str(e)
                # ImportLoginTokenRequest 过期：刷新二维码并继续等待
                lowered = error_msg.lower()
                if (
                    "authorization token has expired" in lowered
                    or "token has expired" in lowered
                    or "updated qr-code must be re-scanned" in lowered
                    or "importlogintokenrequest" in lowered
                    or "acceptlogintokenrequest" in lowered
                ):
                    refreshed = await refresh_qr(reason="token-expired")
                    if not refreshed:
                        return
                    continue

                # 检查是否需要两步验证
                if "Two-step verification" in error_msg or "password" in error_msg.lower():
                    await redis_manager.update_status(
                        login_id,
                        LoginStatus.ERROR,
                        error="该账户启用了两步验证，请暂时关闭或使用验证码登录"
                    )
                else:
                    await redis_manager.update_status(login_id, LoginStatus.ERROR, error=error_msg)
                return

            if result:
                # 获取用户信息
                me = await active_client.get_me()

                # 将当前登录会话导出为 StringSession 并加密，供后续绑定落库使用
                string_session = StringSession.save(active_client.session)
                string_session_encrypted = encrypt_string_session(string_session)

                # 使用统一接口保存绑定码映射(login:bind:*),避免绑定阶段取不到会话
                bind_code = await redis_manager.save_string_session(
                    login_id=login_id,
                    string_session=string_session_encrypted,
                    tg_user_id=me.id,
                    username=me.username or me.first_name or "",
                    phone=me.phone or ""
                )

                # 全局 userbot 会话（非临时客户端）写入数据库，禁用本地 .session 文件
                if login_client is None:
                    await _save_system_session_string(
                        _SYSTEM_USERBOT_SESSION_KEY,
                        string_session,
                        session_meta={
                            "tg_user_id": int(me.id),
                            "username": me.username or "",
                            "phone": me.phone or "",
                        },
                    )

                logger.info(f"二维码登录成功: {me.first_name} (@{me.username}), bind_code: {bind_code}")
                return

            await redis_manager.update_status(login_id, LoginStatus.ERROR, error="登录被取消")
            return

    except Exception as e:
        error_msg = str(e)
        logger.error(f"二维码登录失败: {error_msg}")
        await redis_manager.update_status(login_id, LoginStatus.ERROR, error=error_msg)
    finally:
        _current_qr_login_id = None
        if login_client:
            try:
                await login_client.disconnect()
            except Exception as e:
                logger.warning(f"关闭临时二维码登录客户端失败: {e}")


async def get_peer(chat_id: int):
    """
    获取 Peer 对象

    Args:
        chat_id: 群组/频道 ID

    Returns:
        InputPeer 对象
    """
    entity = await userbot_client.get_entity(chat_id)
    return entity


async def is_userbot_ready() -> bool:
    """检查 Userbot 是否已就绪（已登录）"""
    if not userbot_client.is_connected():
        return False
    return await userbot_client.is_user_authorized()
