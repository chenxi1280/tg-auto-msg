import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from telethon.errors import PhoneCodeExpiredError

import backend.bot.handlers.core.main  # noqa: F401
from backend.bot.onboarding.service import BotOnboardingService
from backend.bot.session.redis_login_manager import LoginStatus
from backend.bot.state.fsm import FSMState, fsm_storage
from backend.h5_backend.services.login.service import LoginService


class _FakeCallbackEvent:
    def __init__(self):
        self.sender_id = 100
        self.chat_id = 100
        self.answer = AsyncMock()
        self.edit = AsyncMock()
        self.respond = AsyncMock()


class _FailingTelegramClient:
    async def connect(self):
        return None

    async def sign_in(self, **_kwargs):
        raise PhoneCodeExpiredError(None)

    async def disconnect(self):
        return None


class BotLoginKeypadTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        fsm_storage.reset_state(100)

    async def test_handle_login_code_text_warns_and_does_not_submit_code(self):
        service = BotOnboardingService()
        fsm_storage.set_state(100, FSMState.WAIT_LOGIN_CODE)
        fsm_storage.update_data(100, login_id="login_text_only")
        login_service = SimpleNamespace(submit_phone_code_data=AsyncMock())

        with patch(
            "backend.bot.onboarding.service.get_login_service",
            return_value=login_service,
        ), patch(
            "backend.bot.onboarding.service.bot_client.send_message",
            new=AsyncMock(),
        ) as send_message:
            await service.handle_login_code(SimpleNamespace(), 100, "12345")

        login_service.submit_phone_code_data.assert_not_called()
        send_message.assert_awaited_once()
        self.assertIn("不要把验证码作为消息发送", send_message.await_args.args[1])

    async def test_handle_login_code_digit_updates_buffer_and_prompt(self):
        service = BotOnboardingService()
        event = _FakeCallbackEvent()
        fsm_storage.set_state(100, FSMState.WAIT_LOGIN_CODE)
        fsm_storage.update_data(
            100,
            login_id="login_digit",
            phone_number="+85268797870",
            login_code_buffer="12",
        )

        with patch(
            "backend.bot.onboarding.service._send_or_edit",
            new=AsyncMock(),
        ) as send_or_edit:
            await service.handle_login_code_digit(event, 100, "3")

        self.assertEqual(fsm_storage.get_data(100)["login_code_buffer"], "123")
        self.assertIn("已输入 3 位", send_or_edit.await_args.args[1])

    async def test_submit_login_code_by_keypad_uses_callback_input_mode(self):
        service = BotOnboardingService()
        event = _FakeCallbackEvent()
        fsm_storage.set_state(100, FSMState.WAIT_LOGIN_CODE)
        fsm_storage.update_data(
            100,
            login_id="login_submit",
            phone_number="+85268797870",
            login_code_buffer="12345",
        )
        login_service = SimpleNamespace(
            submit_phone_code_data=AsyncMock(
                return_value={
                    "status": LoginStatus.CONFIRMED.value,
                    "account_id": "acc_1",
                    "trial_authorization": None,
                }
            )
        )

        with patch(
            "backend.bot.onboarding.service.get_login_service",
            return_value=login_service,
        ), patch.object(
            service,
            "_get_db_user_id",
            AsyncMock(return_value=9),
        ), patch.object(
            service,
            "_send_login_success_message",
            AsyncMock(),
        ) as send_success, patch(
            "backend.bot.onboarding.service._clear_tracked_login_messages",
            new=AsyncMock(),
        ):
            await service.submit_login_code_by_keypad(event, 100)

        login_service.submit_phone_code_data.assert_awaited_once_with(
            login_id="login_submit",
            user_id=9,
            code="12345",
            expected_tg_user_id=None,
            input_mode="callback_keypad",
        )
        send_success.assert_awaited_once()
        self.assertEqual(fsm_storage.get_state(100), FSMState.NONE)


class LoginServicePhoneCodeLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_phone_code_data_logs_callback_keypad_input_mode(self):
        service = LoginService()
        session = SimpleNamespace(
            login_mode="phone_code",
            status=LoginStatus.CODE_INPUT_REQUIRED,
            phone_number="+85268797870",
            phone_code_hash="hash_1",
            pending_session_encrypted="encrypted",
            developer_app_id="3",
            code_attempts="0",
        )
        login_manager = SimpleNamespace(update_status=AsyncMock())

        with patch.object(
            service,
            "_load_session_for_user",
            AsyncMock(return_value=session),
        ), patch.object(
            service,
            "_resolve_login_credentials",
            AsyncMock(return_value=SimpleNamespace(api_id=1, api_hash="hash")),
        ), patch(
            "backend.h5_backend.services.login.service.decrypt_string_session",
            return_value="session_string",
        ), patch(
            "backend.h5_backend.services.login.service.StringSession",
            side_effect=lambda value="": value,
        ), patch(
            "backend.h5_backend.services.login.service.TelegramClient",
            return_value=_FailingTelegramClient(),
        ), patch(
            "backend.h5_backend.services.login.service.get_redis_login_manager",
            return_value=login_manager,
        ), patch(
            "backend.h5_backend.services.login.service.logger",
        ) as logger:
            with self.assertRaises(HTTPException) as ctx:
                await service.submit_phone_code_data(
                    login_id="login_fail",
                    user_id=9,
                    code="12345",
                    input_mode="callback_keypad",
                )

        self.assertEqual(str(ctx.exception.detail), "验证码已过期，请重新发送验证码")
        self.assertEqual(logger.warning.call_args.args[-1], "callback_keypad")
