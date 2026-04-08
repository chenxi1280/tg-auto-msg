import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import select

from backend.config.core.settings import settings
from backend.database.runtime.session import get_async_session, init_database
from backend.database.schema.models import AdminAccount
from backend.h5_backend.services.admin_auth.service import get_admin_auth_service


async def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("Usage: python scripts/init_admin_account.py <username> <password> [display_name]")

    username = sys.argv[1].strip()
    password = sys.argv[2].strip()
    display_name = sys.argv[3].strip() if len(sys.argv) > 3 else username

    if not username or len(password) < 6:
        raise SystemExit("username 不能为空，password 至少 6 位")

    await init_database()
    auth = get_admin_auth_service()

    async with get_async_session() as session:
        existing = (
            await session.execute(select(AdminAccount).where(AdminAccount.username == username).limit(1))
        ).scalar_one_or_none()
        if existing is not None:
            raise SystemExit(f"后台账号已存在: {username}")

        account = AdminAccount(
            username=username,
            password_hash=auth.get_password_hash(password),
            role_code="super_admin",
            province_code=settings.province_code,
            level_depth=0,
            status="active",
            settlement_mode="prepaid",
            is_credit_whitelisted=True,
            force_password_change=True,
            display_name=display_name,
            created_by=None,
        )
        session.add(account)
        await session.flush()
        print(f"Created super_admin account: username={account.username}, id={account.id}, province={account.province_code}")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
