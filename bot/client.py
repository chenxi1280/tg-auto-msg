"""
Telegram 客户端初始化

支持两种登录方式：
1. 二维码登录（推荐）：通过 H5 页面扫码登录
2. 验证码登录：通过手机号和验证码登录
"""
import asyncio
from typing import Optional
from telethon import TelegramClient
from loguru import logger

from config.settings import settings
from bot.redis_login_manager import RedisLoginManager, LoginStatus


# Bot 客户端（用于接收命令和按钮交互）
bot_client = TelegramClient(
    "bot_session",
    api_id=settings.api_id,
    api_hash=settings.api_hash,
)

# Userbot 客户端（用于实际发送消息）
userbot_client = TelegramClient(
    "userbot_session",
    api_id=settings.api_id,
    api_hash=settings.api_hash,
)

# 当前正在进行的二维码登录会话
_current_qr_login_id: Optional[str] = None


async def init_userbot():
    """初始化 Userbot 客户端"""
    # 先连接客户端
    if not userbot_client.is_connected():
        await userbot_client.connect()

    # 检查是否已授权
    if await userbot_client.is_user_authorized():
        # 获取当前用户信息
        me = await userbot_client.get_me()
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
            await redis_manager.update_status(login_id, LoginStatus.CONFIRMED, tg_user_id=str(me.id))
            logger.info(f"Userbot 已登录: {me.first_name}")
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


async def _wait_for_qr_login(login_id: str, qr_login):
    """
    等待二维码登录完成

    Args:
        login_id: 登录会话 ID
        qr_login: Telethon QR 登录对象
    """
    global _current_qr_login_id

    # 使用 RedisLoginManager
    redis_manager = RedisLoginManager()

    try:
        # 更新状态为等待扫码
        await redis_manager.update_status(login_id, LoginStatus.SCANNING)

        # 等待登录完成（设置超时）
        result = await asyncio.wait_for(
            qr_login.wait(),
            timeout=300  # 5 分钟超时
        )

        if result:
            me = await userbot_client.get_me()
            await redis_manager.update_status(login_id, LoginStatus.CONFIRMED, tg_user_id=str(me.id))
            logger.info(f"二维码登录成功: {me.first_name} (@{me.username})")
        else:
            await redis_manager.update_status(login_id, LoginStatus.ERROR, error="登录被取消")

    except asyncio.TimeoutError:
        await redis_manager.update_status(login_id, LoginStatus.EXPIRED)
        logger.error(f"二维码登录超时: {login_id}")
    except Exception as e:
        error_msg = str(e)
        logger.error(f"二维码登录失败: {error_msg}")

        # 检查是否需要两步验证
        if "Two-step verification" in error_msg or "password" in error_msg.lower():
            await redis_manager.update_status(
                login_id,
                LoginStatus.ERROR,
                error="该账户启用了两步验证，请暂时关闭或使用验证码登录"
            )
        else:
            await redis_manager.update_status(login_id, LoginStatus.ERROR, error=error_msg)
    finally:
        _current_qr_login_id = None


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


def is_userbot_ready() -> bool:
    """检查 Userbot 是否已就绪（已登录）"""
    return userbot_client.is_connected() and userbot_client.is_user_authorized()
