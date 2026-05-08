"""User-related admin service extracted from AdminLicenseService."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import func, select

from backend.database.runtime.session import get_async_session
from backend.database.schema.models import (
    Account,
    AppSetting,
    ScheduledMessageTask,
    TaskLog,
    User,
    UserAuthorization,
)
from backend.h5_backend.services.auth.service import get_auth_service
from backend.h5_backend.services.licensing.service import (
    get_account_authorization_summary,
    list_user_authorizations,
)
from backend.h5_backend.services.shared.audit import append_audit_log, mask_actor_name


class UsersService:
    """Admin-only operations for user and account management."""

    @staticmethod
    def _account_display_name(account: Account) -> str:
        if account.username:
            return f"@{account.username}"
        if account.first_name:
            return account.first_name
        if account.phone:
            return account.phone
        return str(account.account_id)

    async def list_users(self, search: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        limit = max(1, min(500, int(limit)))
        offset = max(0, int(offset))

        async with get_async_session() as session:
            base_stmt = (
                select(func.count(User.id))
            )
            stmt = (
                select(
                    User.id,
                    User.username,
                    User.email,
                    User.is_active,
                    User.created_at,
                    func.count(Account.account_id).filter(Account.is_active.is_(True)).label("account_count"),
                )
                .outerjoin(Account, Account.user_id == User.id)
                .group_by(User.id)
                .order_by(User.id.desc())
                .limit(limit)
                .offset(offset)
            )

            if search:
                search_value = f"%{search.strip()}%"
                search_condition = (User.username.ilike(search_value)) | (User.email.ilike(search_value))
                stmt = stmt.where(search_condition)
                base_stmt = base_stmt.where(search_condition)

            total = int((await session.execute(base_stmt)).scalar_one() or 0)
            rows = (await session.execute(stmt)).all()
            user_ids = [row.id for row in rows]

            user_app_map: Dict[int, Optional[int]] = {}
            accounts_by_user: Dict[int, List[Account]] = {int(user_id): [] for user_id in user_ids}
            task_counts_by_user: Dict[int, Dict[str, int]] = {
                int(user_id): {"task_count": 0, "enabled_task_count": 0}
                for user_id in user_ids
            }
            if user_ids:
                keys = [f"user_dev_app:{uid}" for uid in user_ids]
                app_rows = (
                    await session.execute(
                        select(AppSetting.key, AppSetting.value).where(AppSetting.key.in_(keys))
                    )
                ).all()
                for key, value in app_rows:
                    try:
                        uid = int(str(key).split(":", 1)[1])
                        app_id = int((value or "").strip()) if (value or "").strip() else None
                        user_app_map[uid] = app_id
                    except Exception:
                        continue

                account_rows = (
                    await session.execute(
                        select(Account)
                        .where(Account.user_id.in_(user_ids))
                        .order_by(Account.created_at.desc())
                    )
                ).scalars().all()
                for account in account_rows:
                    accounts_by_user.setdefault(int(account.user_id), []).append(account)

                task_rows = (
                    await session.execute(
                        select(
                            ScheduledMessageTask.user_id,
                            func.count(ScheduledMessageTask.task_id).label("task_count"),
                            func.count(ScheduledMessageTask.task_id)
                            .filter(ScheduledMessageTask.enabled.is_(True))
                            .label("enabled_task_count"),
                        )
                        .where(ScheduledMessageTask.user_id.in_(user_ids))
                        .group_by(ScheduledMessageTask.user_id)
                    )
                ).all()
                for task_row in task_rows:
                    task_counts_by_user[int(task_row.user_id)] = {
                        "task_count": int(task_row.task_count or 0),
                        "enabled_task_count": int(task_row.enabled_task_count or 0),
                    }

            data: List[Dict[str, Any]] = []
            for row in rows:
                authorizations = await list_user_authorizations(int(row.id), session=session)
                current = authorizations[0] if authorizations else None
                user_accounts = accounts_by_user.get(int(row.id), [])
                tg_account_names = [self._account_display_name(account) for account in user_accounts]
                task_counts = task_counts_by_user.get(int(row.id), {"task_count": 0, "enabled_task_count": 0})
                data.append(
                    {
                        "id": row.id,
                        "username": row.username,
                        "email": row.email,
                        "is_active": row.is_active,
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                        "account_count": int(row.account_count or 0),
                        "authorization_count": 1 if current else 0,
                        "developer_app_id": user_app_map.get(row.id),
                        "tg_account_names": tg_account_names,
                        "tg_account_summary": "、".join(tg_account_names[:3]) + (" 等" if len(tg_account_names) > 3 else ""),
                        "task_count": task_counts["task_count"],
                        "enabled_task_count": task_counts["enabled_task_count"],
                        "current_authorization": {
                            "start_at": current.start_at.isoformat() if current else None,
                            "end_at": current.end_at.isoformat() if current else None,
                            "status": current.status if current else None,
                        },
                    }
                )
            return {
                "items": data,
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    async def list_account_options(self, search: Optional[str] = None, limit: int = 300) -> List[Dict[str, Any]]:
        limit = max(1, min(1000, int(limit)))
        async with get_async_session() as session:
            stmt = (
                select(
                    Account.account_id,
                    Account.username,
                    Account.phone,
                    Account.tg_user_id,
                    User.id.label("user_id"),
                    User.username.label("owner_username"),
                )
                .join(User, User.id == Account.user_id)
                .order_by(Account.created_at.desc())
                .limit(limit)
            )
            if search:
                q = f"%{search.strip()}%"
                stmt = stmt.where(
                    (Account.username.ilike(q))
                    | (Account.phone.ilike(q))
                    | (User.username.ilike(q))
                )
            rows = (await session.execute(stmt)).all()
            return [
                {
                    "account_id": row.account_id,
                    "username": row.username,
                    "phone": row.phone,
                    "tg_user_id": row.tg_user_id,
                    "owner_user_id": row.user_id,
                    "owner_username": row.owner_username,
                    "label": f"{row.owner_username} / {row.username or row.phone or row.account_id}",
                }
                for row in rows
            ]

    async def list_user_accounts(self, user_id: int) -> List[Dict[str, Any]]:
        async with get_async_session() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id).limit(1))
            ).scalar_one_or_none()
            if not user:
                raise HTTPException(status_code=404, detail="用户不存在")

            accounts = (
                await session.execute(
                    select(Account).where(Account.user_id == user_id).order_by(Account.created_at.desc())
                )
            ).scalars().all()
            account_ids = [str(account.account_id) for account in accounts]
            task_counts_by_account: Dict[str, Dict[str, int]] = {
                account_id: {"task_count": 0, "enabled_task_count": 0}
                for account_id in account_ids
            }
            send_stats_by_account: Dict[str, Dict[str, Any]] = {
                account_id: {
                    "send_log_count": 0,
                    "send_success_count": 0,
                    "send_failed_count": 0,
                    "last_send_at": None,
                    "last_send_result": None,
                    "last_send_error_message": None,
                }
                for account_id in account_ids
            }
            if account_ids:
                task_rows = (
                    await session.execute(
                        select(
                            ScheduledMessageTask.account_id,
                            func.count(ScheduledMessageTask.task_id).label("task_count"),
                            func.count(ScheduledMessageTask.task_id)
                            .filter(ScheduledMessageTask.enabled.is_(True))
                            .label("enabled_task_count"),
                        )
                        .where(
                            ScheduledMessageTask.user_id == int(user_id),
                            ScheduledMessageTask.account_id.in_(account_ids),
                        )
                        .group_by(ScheduledMessageTask.account_id)
                    )
                ).all()
                for task_row in task_rows:
                    task_counts_by_account[str(task_row.account_id)] = {
                        "task_count": int(task_row.task_count or 0),
                        "enabled_task_count": int(task_row.enabled_task_count or 0),
                    }

                send_rows = (
                    await session.execute(
                        select(
                            ScheduledMessageTask.account_id,
                            func.count(TaskLog.id).label("send_log_count"),
                            func.count(TaskLog.id).filter(TaskLog.result == "success").label("send_success_count"),
                            func.count(TaskLog.id).filter(TaskLog.result == "failed").label("send_failed_count"),
                            func.max(TaskLog.send_at).label("last_send_at"),
                        )
                        .select_from(ScheduledMessageTask)
                        .join(TaskLog, TaskLog.task_id == ScheduledMessageTask.task_id)
                        .where(
                            ScheduledMessageTask.user_id == int(user_id),
                            ScheduledMessageTask.account_id.in_(account_ids),
                        )
                        .group_by(ScheduledMessageTask.account_id)
                    )
                ).all()
                for send_row in send_rows:
                    account_id = str(send_row.account_id)
                    send_stats_by_account[account_id] = {
                        **send_stats_by_account.get(account_id, {}),
                        "send_log_count": int(send_row.send_log_count or 0),
                        "send_success_count": int(send_row.send_success_count or 0),
                        "send_failed_count": int(send_row.send_failed_count or 0),
                        "last_send_at": send_row.last_send_at.isoformat() if send_row.last_send_at else None,
                    }

                latest_log_ranked = (
                    select(
                        ScheduledMessageTask.account_id.label("account_id"),
                        TaskLog.result.label("result"),
                        TaskLog.error_message.label("error_message"),
                        func.row_number()
                        .over(
                            partition_by=ScheduledMessageTask.account_id,
                            order_by=(TaskLog.send_at.desc(), TaskLog.id.desc()),
                        )
                        .label("rn"),
                    )
                    .select_from(ScheduledMessageTask)
                    .join(TaskLog, TaskLog.task_id == ScheduledMessageTask.task_id)
                    .where(
                        ScheduledMessageTask.user_id == int(user_id),
                        ScheduledMessageTask.account_id.in_(account_ids),
                    )
                    .subquery()
                )
                latest_rows = (
                    await session.execute(
                        select(
                            latest_log_ranked.c.account_id,
                            latest_log_ranked.c.result,
                            latest_log_ranked.c.error_message,
                        ).where(latest_log_ranked.c.rn == 1)
                    )
                ).all()
                for latest_row in latest_rows:
                    account_id = str(latest_row.account_id)
                    send_stats_by_account.setdefault(account_id, {})
                    send_stats_by_account[account_id]["last_send_result"] = latest_row.result
                    send_stats_by_account[account_id]["last_send_error_message"] = latest_row.error_message

            items = []
            for a in accounts:
                task_counts = task_counts_by_account.get(
                    str(a.account_id),
                    {"task_count": 0, "enabled_task_count": 0},
                )
                send_stats = send_stats_by_account.get(
                    str(a.account_id),
                    {
                        "send_log_count": 0,
                        "send_success_count": 0,
                        "send_failed_count": 0,
                        "last_send_at": None,
                        "last_send_result": None,
                        "last_send_error_message": None,
                    },
                )
                items.append({
                    "account_id": a.account_id,
                    "tg_user_id": a.tg_user_id,
                    "username": a.username,
                    "tg_account_name": self._account_display_name(a),
                    "first_name": a.first_name,
                    "phone": a.phone,
                    "developer_app_id": a.developer_app_id,
                    "is_active": a.is_active,
                    "is_banned": a.is_banned,
                    "health_status": a.health_status,
                    "is_flooding": a.is_flooding,
                    "messages_sent": a.messages_sent,
                    "task_count": task_counts["task_count"],
                    "enabled_task_count": task_counts["enabled_task_count"],
                    "send_log_count": send_stats["send_log_count"],
                    "send_success_count": send_stats["send_success_count"],
                    "send_failed_count": send_stats["send_failed_count"],
                    "last_send_at": send_stats["last_send_at"],
                    "last_send_result": send_stats["last_send_result"],
                    "last_send_error_message": send_stats["last_send_error_message"],
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                    **(await get_account_authorization_summary(a.account_id, session=session)).to_dict(),
                })
            return items

    async def list_account_send_logs(
        self,
        user_id: int,
        account_id: str,
        *,
        result: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        limit = max(1, min(200, int(limit)))
        offset = max(0, int(offset))
        normalized_result = (result or "").strip().lower()
        if normalized_result and normalized_result not in {"success", "failed"}:
            raise HTTPException(status_code=400, detail="result 仅支持 success 或 failed")

        async with get_async_session() as session:
            account = await session.get(Account, str(account_id))
            if account is None or int(account.user_id) != int(user_id):
                raise HTTPException(status_code=404, detail="账号不存在")

            conditions = [
                ScheduledMessageTask.user_id == int(user_id),
                ScheduledMessageTask.account_id == str(account_id),
            ]
            if normalized_result:
                conditions.append(TaskLog.result == normalized_result)

            count_stmt = (
                select(func.count(TaskLog.id))
                .select_from(ScheduledMessageTask)
                .join(TaskLog, TaskLog.task_id == ScheduledMessageTask.task_id)
                .where(*conditions)
            )
            rows_stmt = (
                select(TaskLog, ScheduledMessageTask.task_id, ScheduledMessageTask.title)
                .select_from(ScheduledMessageTask)
                .join(TaskLog, TaskLog.task_id == ScheduledMessageTask.task_id)
                .where(*conditions)
                .order_by(TaskLog.send_at.desc(), TaskLog.id.desc())
                .limit(limit)
                .offset(offset)
            )
            total = int((await session.execute(count_stmt)).scalar_one() or 0)
            rows = (await session.execute(rows_stmt)).all()

        return {
            "items": [
                {
                    "id": log.id,
                    "task_id": task_id,
                    "task_title": task_title,
                    "send_at": log.send_at.isoformat() if log.send_at else None,
                    "result": log.result,
                    "trigger_source": log.trigger_source,
                    "error_code": log.error_code,
                    "error_message": log.error_message,
                    "message_id": log.message_id,
                }
                for log, task_id, task_title in rows
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    async def admin_delete_account(
        self,
        account_id: str,
        *,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> None:
        from backend.bot.account.manager import get_account_manager

        account_manager = get_account_manager()
        ok = await account_manager.delete_account(account_id)
        if not ok:
            raise HTTPException(status_code=404, detail="账号不存在")

        async with get_async_session() as session:
            await append_audit_log(
                session,
                actor=mask_actor_name(actor),
                action="admin.delete_account",
                target_type="account",
                target_id=account_id,
                detail={},
                ip_address=ip_address,
            )
            await session.commit()

    async def reset_user_password(
        self,
        user_id: int,
        new_password: str,
        *,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> None:
        if len(new_password or "") < 6:
            raise HTTPException(status_code=400, detail="新密码至少 6 位")

        auth_service = get_auth_service()
        async with get_async_session() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id).limit(1))
            ).scalar_one_or_none()
            if not user:
                raise HTTPException(status_code=404, detail="用户不存在")
            user.password_hash = auth_service.get_password_hash(new_password)
            user.bot_initial_password_viewable = False
            user.password_changed_after_bot_registration = True
            await append_audit_log(
                session,
                actor=mask_actor_name(actor),
                action="admin.reset_user_password",
                target_type="user",
                target_id=str(user_id),
                detail={},
                ip_address=ip_address,
            )
            await session.commit()

    async def list_authorizations(
        self,
        *,
        status: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Dict[str, Any]:
        limit = max(1, min(500, int(limit)))
        offset = max(0, int(offset))

        count_stmt = select(func.count(UserAuthorization.authorization_id))
        stmt = (
            select(UserAuthorization, User.username, Account.username, Account.phone, Account.tg_user_id)
            .join(User, User.id == UserAuthorization.user_id)
            .outerjoin(Account, Account.account_id == UserAuthorization.current_account_id)
            .order_by(UserAuthorization.end_at.asc(), UserAuthorization.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if status:
            stmt = stmt.where(UserAuthorization.status == status)
            count_stmt = count_stmt.where(UserAuthorization.status == status)

        async with get_async_session() as session:
            total = int((await session.execute(count_stmt)).scalar_one() or 0)
            rows = (await session.execute(stmt)).all()

        data: List[Dict[str, Any]] = []
        for slot, owner_username, account_username, account_phone, account_tg_user_id in rows:
            data.append(
                {
                    "authorization_id": slot.authorization_id,
                    "user_id": slot.user_id,
                    "owner_username": owner_username,
                    "status": slot.status,
                    "current_account_id": slot.current_account_id,
                    "current_account_username": account_username,
                    "current_account_phone": account_phone,
                    "current_account_tg_user_id": account_tg_user_id,
                    "total_duration_days": slot.total_duration_days,
                    "start_at": slot.start_at.isoformat() if slot.start_at else None,
                    "end_at": slot.end_at.isoformat() if slot.end_at else None,
                    "created_at": slot.created_at.isoformat() if slot.created_at else None,
                    "updated_at": slot.updated_at.isoformat() if slot.updated_at else None,
                }
            )
        return {
            "items": data,
            "total": total,
            "limit": limit,
            "offset": offset,
        }


_user_service: UsersService | None = None


def get_user_admin_service() -> UsersService:
    global _user_service
    if _user_service is None:
        _user_service = UsersService()
    return _user_service
