import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.h5_backend.dependencies import get_current_admin_account
from backend.h5_backend.routers.admin_panel import router


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


class AdminPanelRouteTests(unittest.TestCase):
    def _build_client(self, current_admin):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_admin_account] = lambda: current_admin
        return TestClient(app)

    def test_direct_recharge_requires_agents_write_permission(self):
        client = self._build_client(_build_admin("agents.read"))

        response = client.post(
            "/api/admin/fund-ledgers/recharge",
            json={"subject_account_id": 2, "amount_cents": 1000, "remark": "线下"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "无权访问该后台资源")

    def test_direct_recharge_passes_payload_and_client_ip_to_service(self):
        client = self._build_client(_build_admin("agents.write"))
        service = SimpleNamespace(
            create_recharge_entry=AsyncMock(return_value={"id": 2, "balance_cents": 5000})
        )

        with patch("backend.h5_backend.routers.admin_panel.get_admin_panel_service", return_value=service):
            response = client.post(
                "/api/admin/fund-ledgers/recharge",
                json={"subject_account_id": 2, "amount_cents": 1000, "remark": "线下"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        service.create_recharge_entry.assert_awaited_once()
        kwargs = service.create_recharge_entry.await_args.kwargs
        self.assertEqual(kwargs["subject_account_id"], 2)
        self.assertEqual(kwargs["amount_cents"], 1000)
        self.assertEqual(kwargs["remark"], "线下")
        self.assertEqual(kwargs["ip_address"], "testclient")

    def test_operation_logs_uses_scope_flag_based_on_permissions(self):
        client = self._build_client(_build_admin("operation_logs.read"))
        service = SimpleNamespace(
            list_operation_logs=AsyncMock(return_value={"items": [], "total": 0, "limit": 20, "offset": 0, "stats": {}})
        )

        with patch("backend.h5_backend.routers.admin_panel.get_admin_panel_service", return_value=service):
            response = client.get("/api/admin/operation-logs")

        self.assertEqual(response.status_code, 200)
        kwargs = service.list_operation_logs.await_args.kwargs
        self.assertFalse(kwargs["scope_only"])

    def test_operation_logs_denies_when_no_permission(self):
        client = self._build_client(_build_admin("agents.read"))

        response = client.get("/api/admin/operation-logs")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "无权访问该后台资源")

    def test_audit_logs_now_require_system_audit_permission(self):
        client = self._build_client(_build_admin("operation_logs.scope.read"))

        response = client.get("/api/agent/audit-logs")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "无权访问该后台资源")


if __name__ == "__main__":
    unittest.main()
