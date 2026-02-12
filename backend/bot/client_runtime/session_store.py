"""System session persistence helpers for Telegram clients."""
from __future__ import annotations

import time
import asyncio
from pathlib import Path
from typing import Any, Optional

from loguru import logger
from sqlalchemy import select
from telethon import TelegramClient
from telethon.sessions import StringSession

from backend.database.schema.models import SystemSession
from backend.database.runtime.session import get_async_session
from backend.utils.security.crypto import decrypt_string_session, encrypt_string_session

_DB_OP_TIMEOUT_SECONDS = 5


def _format_error(err: Exception) -> str:
    """Human-readable error detail even for empty-message exceptions."""
    text = str(err).strip()
    if text:
        return f"{type(err).__name__}: {text}"
    return f"{type(err).__name__}: {err!r}"


def extract_expected_bot_id(bot_token: str) -> Optional[int]:
    """Extract expected bot id from token prefix."""
    if not bot_token:
        return None
    try:
        return int(str(bot_token).split(":", 1)[0])
    except Exception:
        return None


def build_session_meta(extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Build persisted metadata payload for system sessions."""
    meta = {"updated_at": int(time.time())}
    if extra:
        meta.update(extra)
    return meta


async def load_system_session_string(session_key: str) -> Optional[str]:
    """Load and decrypt one persisted system session string."""
    try:
        async with asyncio.timeout(_DB_OP_TIMEOUT_SECONDS):
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
                    logger.error(f"系统会话解密失败，已清理损坏记录: key={session_key}, error={_format_error(e)}")
                    await session.delete(row)
                    return None
    except TimeoutError:
        logger.warning(f"读取系统会话超时: key={session_key}, timeout={_DB_OP_TIMEOUT_SECONDS}s")
        return None
    except Exception as e:
        logger.warning(f"读取系统会话失败: key={session_key}, error={_format_error(e)}")
        return None


async def save_system_session_string(
    session_key: str,
    session_string: str,
    *,
    session_meta: Optional[dict[str, Any]] = None,
    developer_app_id: Optional[int] = None,
) -> None:
    """Encrypt and persist one system session string."""
    if not session_string:
        return

    encrypted = encrypt_string_session(session_string)
    meta = build_session_meta(session_meta)
    try:
        async with asyncio.timeout(_DB_OP_TIMEOUT_SECONDS):
            async with get_async_session() as session:
                row = await session.get(SystemSession, session_key)
                if row is None:
                    row = SystemSession(
                        session_key=session_key,
                        session_encrypted=encrypted,
                        developer_app_id=developer_app_id,
                        session_meta=meta,
                    )
                    session.add(row)
                else:
                    row.session_encrypted = encrypted
                    if developer_app_id is not None:
                        row.developer_app_id = int(developer_app_id)
                    row.session_meta = meta
    except TimeoutError:
        logger.warning(f"保存系统会话超时: key={session_key}, timeout={_DB_OP_TIMEOUT_SECONDS}s")
    except Exception as e:
        logger.warning(f"保存系统会话失败: key={session_key}, error={_format_error(e)}")


async def delete_system_session(session_key: str) -> None:
    """Delete one persisted system session."""
    try:
        async with asyncio.timeout(_DB_OP_TIMEOUT_SECONDS):
            async with get_async_session() as session:
                row = await session.get(SystemSession, session_key)
                if row is not None:
                    await session.delete(row)
    except TimeoutError:
        logger.warning(f"删除系统会话超时: key={session_key}, timeout={_DB_OP_TIMEOUT_SECONDS}s")
    except Exception as e:
        logger.warning(f"删除系统会话失败: key={session_key}, error={_format_error(e)}")


async def restore_client_session(client: TelegramClient, session_key: str) -> None:
    """Restore client StringSession from DB before connect."""
    if client.is_connected():
        return

    session_string = await load_system_session_string(session_key)
    if not session_string:
        return

    try:
        client.session = StringSession(session_string)
        logger.info(f"已从数据库恢复系统会话: {session_key}")
    except Exception as e:
        logger.warning(f"恢复系统会话失败: key={session_key}, error={_format_error(e)}")


async def persist_client_session(
    client: TelegramClient,
    session_key: str,
    *,
    session_meta: Optional[dict[str, Any]] = None,
    developer_app_id: Optional[int] = None,
) -> None:
    """Export and persist current client session."""
    try:
        session_string = StringSession.save(client.session)
    except Exception as e:
        logger.warning(f"导出客户端会话失败: key={session_key}, error={_format_error(e)}")
        return
    if not session_string:
        return
    await save_system_session_string(
        session_key,
        session_string,
        session_meta=session_meta,
        developer_app_id=developer_app_id,
    )


def cleanup_legacy_session_files(legacy_files: tuple[str, ...]) -> None:
    """Remove legacy sqlite session files."""
    for filename in legacy_files:
        path = Path(filename)
        if not path.exists():
            continue
        try:
            path.unlink()
            logger.info(f"已清理历史本地会话文件: {filename}")
        except Exception as e:
            logger.warning(f"清理历史本地会话文件失败: {filename}, error={e}")
