import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

from backend.h5_backend.services.admin_auth.service import AdminAuthService
from backend.h5_backend.services.admin_rbac.service import AdminRbacService


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _BootstrapSession:
    def __init__(self, existing_account):
        self.existing_account = existing_account
        self.added = []
        self.execute_calls = 0

    async def execute(self, _stmt):
        self.execute_calls += 1
        if self.execute_calls == 1:
            return _ScalarResult(self.existing_account)
        return _ScalarResult(None)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None


class AdminAccountModelRefactorTests(unittest.IsolatedAsyncioTestCase):
    def test_permission_codes_fallback_to_default_roles_for_legacy_accounts(self):
        service = AdminRbacService()
        legacy_master_agent = SimpleNamespace(
            role_code="master_agent",
            account_type=None,
            business_identity=None,
            role_bindings=[],
        )
        legacy_super_admin = SimpleNamespace(
            role_code="super_admin",
            account_type=None,
            business_identity=None,
            role_bindings=[],
        )

        master_permissions = set(service.get_permission_codes_for_account(legacy_master_agent))
        super_permissions = set(service.get_permission_codes_for_account(legacy_super_admin))

        self.assertIn("batches.generate", master_permissions)
        self.assertIn("agents.read", master_permissions)
        self.assertIn("system.stats.read", super_permissions)
        self.assertIn("admin_accounts.write", super_permissions)

    async def test_bootstrap_skips_creation_when_staff_account_already_has_super_admin_role(self):
        service = AdminAuthService()
        existing_account = SimpleNamespace(
            id=9,
            username="ops-root",
            role_code="staff",
            account_type="staff",
            province_code="default",
            status="active",
        )
        fake_session = _BootstrapSession(existing_account)

        @asynccontextmanager
        async def fake_get_async_session():
            yield fake_session

        with patch("backend.h5_backend.services.admin_auth.service.get_async_session", new=fake_get_async_session), patch(
            "backend.h5_backend.services.admin_auth.service.settings.admin_bootstrap_username",
            "admin",
        ), patch(
            "backend.h5_backend.services.admin_auth.service.settings.admin_bootstrap_password",
            "123456a.",
        ), patch(
            "backend.h5_backend.services.admin_auth.service.settings.province_code",
            "default",
        ):
            result = await service.ensure_bootstrap_super_admin()

        self.assertIs(result, existing_account)
        self.assertEqual(fake_session.added, [])


if __name__ == "__main__":
    unittest.main()
