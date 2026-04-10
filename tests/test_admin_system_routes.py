import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.h5_backend.dependencies import get_current_admin_account
from backend.h5_backend.routers.admin_system import router


def _build_admin(*permissions: str):
    permission_objs = [SimpleNamespace(permission_code=code) for code in permissions]
    role = SimpleNamespace(status="active", permission_bindings=[SimpleNamespace(permission=item) for item in permission_objs])
    binding = SimpleNamespace(role=role)
    return SimpleNamespace(
        id=1,
        username="admin",
        role_code="super_admin",
        province_code="default",
        role_bindings=[binding],
    )


class AdminSystemRouteTests(unittest.TestCase):
    def _build_client(self, current_admin):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_admin_account] = lambda: current_admin
        return TestClient(app)

    def test_today_stats_requires_system_stats_permission(self):
        client = self._build_client(_build_admin("system.settings.read"))

        response = client.get("/api/admin/system/stats/today")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "无权访问该后台资源")

    def test_today_stats_returns_service_payload(self):
        client = self._build_client(_build_admin("system.stats.read"))
        service = SimpleNamespace(
            get_today_system_stats=AsyncMock(
                return_value={
                    "date": "2026-04-09",
                    "timezone": "Asia/Shanghai",
                    "today_sent_messages": 12,
                    "today_bound_cards": 3,
                    "today_new_users": 5,
                }
            )
        )

        with patch("backend.h5_backend.routers.admin_system.get_admin_license_service", return_value=service):
            response = client.get("/api/admin/system/stats/today")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(response.json()["data"]["today_sent_messages"], 12)
        service.get_today_system_stats.assert_awaited_once()

    def test_system_audit_logs_require_system_audit_permission(self):
        client = self._build_client(_build_admin("operation_logs.scope.read"))

        response = client.get("/api/admin/audit-logs")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "无权访问该后台资源")


if __name__ == "__main__":
    unittest.main()
