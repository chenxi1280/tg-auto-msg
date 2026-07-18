import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.bot.account.proxy_observation import REAUTH_LOGIN_ROUTE_DIRECT
from backend.bot.handlers.account.management import relogin_account


def _session_ctx(session):
    @asynccontextmanager
    async def _ctx():
        yield session

    return _ctx


class AccountReloginTests(unittest.IsolatedAsyncioTestCase):
    async def test_unhealthy_proxy_reauth_starts_phone_login_over_direct_route(self):
        event = SimpleNamespace(answer=AsyncMock())
        account = SimpleNamespace(
            account_id="acc-1",
            tg_user_id=12345,
            reauth_required=True,
            reauth_reason="proxy_region_selected",
        )
        session = SimpleNamespace(commit=AsyncMock())
        onboarding = SimpleNamespace(start_account_login=AsyncMock())

        with (
            patch(
                "backend.bot.handlers.account.management._get_owned_account",
                AsyncMock(return_value=(9, account)),
            ),
            patch(
                "backend.bot.handlers.account.management.get_async_session",
                _session_ctx(session),
            ),
            patch(
                "backend.bot.handlers.account.management.resolve_reauth_login_route",
                AsyncMock(return_value=REAUTH_LOGIN_ROUTE_DIRECT),
            ),
            patch("backend.bot.onboarding.get_onboarding_service", return_value=onboarding),
        ):
            await relogin_account(event, user_id=100, account_id="acc-1")

        session.commit.assert_awaited_once()
        event.answer.assert_awaited_once_with("固定代理不可用，已切换服务器直连重新登录。")
        onboarding.start_account_login.assert_awaited_once_with(
            event,
            100,
            existing_tg_user_id=12345,
            target_account_id="acc-1",
        )
