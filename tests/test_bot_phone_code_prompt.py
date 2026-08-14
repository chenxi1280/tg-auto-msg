import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from backend.bot.onboarding.service import BotOnboardingService
from backend.bot.state.fsm import FSMState, fsm_storage
from backend.h5_backend.services.login.phone_code_delivery import (
    DELIVERY_METHOD_SMS,
    DELIVERY_METHOD_TELEGRAM_APP,
)


class _CallbackEvent:
    def __init__(self):
        self.answer = AsyncMock()
        self.edit = AsyncMock()
        self.respond = AsyncMock()


class BotPhoneCodePromptTests(unittest.IsolatedAsyncioTestCase):
    USER_ID = 101

    def tearDown(self):
        fsm_storage.reset_state(self.USER_ID)

    async def test_initial_prompt_keeps_wait_after_keypad_interaction(self):
        service = BotOnboardingService()
        fsm_storage.set_state(self.USER_ID, FSMState.WAIT_LOGIN_PHONE)
        fsm_storage.update_data(self.USER_ID, login_id="bot_login_initial", expected_tg_user_id=self.USER_ID)
        login_service = SimpleNamespace(
            submit_phone_number_data=AsyncMock(
                return_value={
                    "phone_number": "+15550001111",
                    "delivery_method": DELIVERY_METHOD_TELEGRAM_APP,
                    "next_delivery_method": DELIVERY_METHOD_SMS,
                    "code_length": 6,
                    "resend_after_seconds": 30,
                }
            )
        )

        with patch("backend.bot.onboarding.service.get_login_service", return_value=login_service), patch.object(
            service,
            "_get_db_user_id",
            AsyncMock(return_value=9),
        ), patch(
            "backend.bot.onboarding.service.bot_client.send_message",
            new=AsyncMock(return_value=SimpleNamespace(id=88)),
        ) as send_message, patch(
            "backend.bot.onboarding.service._track_login_message",
            new=MagicMock(),
        ):
            await service.handle_login_phone(SimpleNamespace(), self.USER_ID, "+15550001111")

        initial_prompt = send_message.await_args.args[1]
        self.assertIn("已登录的 Telegram 客户端", initial_prompt)
        self.assertIn("30 秒后才可重新请求", initial_prompt)

        event = _CallbackEvent()
        await service.handle_login_code_digit(event, self.USER_ID, "1")

        refreshed_prompt = event.edit.await_args.args[0]
        self.assertIn("秒后才可重新请求", refreshed_prompt)
        self.assertNotIn("如未收到验证码，可点击", refreshed_prompt)

    async def test_early_resend_shows_remaining_seconds_without_new_delivery(self):
        service = BotOnboardingService()
        event = _CallbackEvent()
        fsm_storage.set_state(self.USER_ID, FSMState.WAIT_LOGIN_CODE)
        fsm_storage.update_data(
            self.USER_ID,
            login_id="bot_login_wait",
            phone_number="+15550001111",
            delivery_method=DELIVERY_METHOD_SMS,
            login_code_buffer="",
        )
        login_service = SimpleNamespace(
            submit_phone_number_data=AsyncMock(
                side_effect=HTTPException(429, "验证码已请求，请在 23 秒后再试。", {"Retry-After": "23"})
            )
        )

        with patch("backend.bot.onboarding.service.get_login_service", return_value=login_service), patch.object(
            service,
            "_get_db_user_id",
            AsyncMock(return_value=9),
        ):
            await service.handle_login_code_resend(event, self.USER_ID)

        prompt = event.edit.await_args.args[0]
        self.assertIn("请等待后再重发验证码", prompt)
        self.assertIn("23 秒后", prompt)
        self.assertEqual(fsm_storage.get_data(self.USER_ID)["delivery_method"], DELIVERY_METHOD_SMS)

    async def test_non_cooldown_resend_error_is_not_presented_as_a_wait(self):
        service = BotOnboardingService()
        event = _CallbackEvent()
        fsm_storage.set_state(self.USER_ID, FSMState.WAIT_LOGIN_CODE)
        fsm_storage.update_data(
            self.USER_ID,
            login_id="bot_login_error",
            phone_number="+15550001111",
            delivery_method=DELIVERY_METHOD_SMS,
            login_code_buffer="",
        )
        login_service = SimpleNamespace(
            submit_phone_number_data=AsyncMock(
                side_effect=HTTPException(400, "当前会话状态不允许重新发送验证码")
            )
        )

        with patch("backend.bot.onboarding.service.get_login_service", return_value=login_service), patch.object(
            service,
            "_get_db_user_id",
            AsyncMock(return_value=9),
        ):
            await service.handle_login_code_resend(event, self.USER_ID)

        prompt = event.edit.await_args.args[0]
        self.assertIn("验证码请求未成功", prompt)
        self.assertIn("当前会话状态不允许重新发送验证码", prompt)
        self.assertNotIn("请等待后再重发验证码", prompt)

    async def test_successful_resend_updates_delivery_prompt(self):
        service = BotOnboardingService()
        event = _CallbackEvent()
        fsm_storage.set_state(self.USER_ID, FSMState.WAIT_LOGIN_CODE)
        fsm_storage.update_data(
            self.USER_ID,
            login_id="bot_login_resend",
            phone_number="+15550001111",
            delivery_method=DELIVERY_METHOD_TELEGRAM_APP,
            login_code_buffer="",
        )
        login_service = SimpleNamespace(
            submit_phone_number_data=AsyncMock(
                return_value={
                    "phone_number": "+15550001111",
                    "delivery_method": DELIVERY_METHOD_SMS,
                    "next_delivery_method": None,
                    "code_length": 5,
                    "resend_after_seconds": 45,
                }
            )
        )

        with patch("backend.bot.onboarding.service.get_login_service", return_value=login_service), patch.object(
            service,
            "_get_db_user_id",
            AsyncMock(return_value=9),
        ):
            await service.handle_login_code_resend(event, self.USER_ID)

        prompt = event.edit.await_args.args[0]
        self.assertIn("请在短信查看验证码", prompt)
        self.assertIn("45 秒后才可重新请求", prompt)
        self.assertEqual(fsm_storage.get_data(self.USER_ID)["delivery_method"], DELIVERY_METHOD_SMS)
