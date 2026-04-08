import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.h5_backend.services.me.service import MeService


class _FakeExecuteResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    def __init__(self, user):
        self._user = user
        self.committed = False

    async def execute(self, *_args, **_kwargs):
        return _FakeExecuteResult(self._user)

    async def commit(self):
        self.committed = True


class _FakeSessionManager:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class MeServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_bot_initial_password_returns_decrypted_value(self):
        user = SimpleNamespace(
            id=9,
            bot_initial_password_viewable=True,
            bot_initial_password_encrypted="ciphertext",
        )
        session = _FakeSession(user)
        crypto = MagicMock()
        crypto.decrypt.return_value = "Plain123456789"

        with patch(
            "backend.h5_backend.services.me.service.get_async_session",
            return_value=_FakeSessionManager(session),
        ), patch(
            "backend.h5_backend.services.me.service.get_crypto_manager",
            return_value=crypto,
        ):
            password = await MeService().get_bot_initial_password(9)

        self.assertEqual(password, "Plain123456789")
        self.assertEqual(user.bot_initial_password_encrypted, "ciphertext")
        self.assertTrue(user.bot_initial_password_viewable)
        self.assertFalse(session.committed)

    async def test_reset_corrupted_bot_initial_password_updates_user_state(self):
        user = SimpleNamespace(
            id=9,
            password_hash="old-hash",
            bot_initial_password_encrypted="broken-ciphertext",
            bot_initial_password_viewable=True,
            password_changed_after_bot_registration=False,
        )
        session = _FakeSession(user)
        auth_service = MagicMock()
        auth_service.get_password_hash.side_effect = lambda raw: f"hashed::{raw}"

        with patch.object(
            MeService,
            "_generate_reset_password",
            return_value="Reset123456789",
        ), patch(
            "backend.h5_backend.services.me.service.get_async_session",
            return_value=_FakeSessionManager(session),
        ), patch(
            "backend.h5_backend.services.me.service.get_auth_service",
            return_value=auth_service,
        ):
            new_password = await MeService().reset_corrupted_bot_initial_password(9)

        self.assertEqual(new_password, "Reset123456789")
        self.assertEqual(user.password_hash, "hashed::Reset123456789")
        self.assertIsNone(user.bot_initial_password_encrypted)
        self.assertFalse(user.bot_initial_password_viewable)
        self.assertTrue(user.password_changed_after_bot_registration)
        self.assertTrue(session.committed)
