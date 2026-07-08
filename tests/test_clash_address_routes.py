import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.h5_backend.dependencies import get_current_admin_account
from backend.h5_backend.routers.admin_clash_addresses import router


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


class ClashAddressRouteTests(unittest.TestCase):
    def _build_client(self, current_admin):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_admin_account] = lambda: current_admin
        return TestClient(app)

    def test_list_requires_system_settings_read_permission(self):
        client = self._build_client(_build_admin("system.stats.read"))

        response = client.get("/api/admin/system/clash-addresses")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "无权访问该后台资源")

    def test_create_clash_address_uses_update_permission_and_masks_url(self):
        client = self._build_client(_build_admin("system.settings.update"))
        service = SimpleNamespace(
            create_address=AsyncMock(
                return_value={
                    "id": 1,
                    "name": "香港主线路",
                    "url_masked": "https://proxy.example.com/sub?token=se***en",
                    "is_active": True,
                    "remark": "机场 A",
                    "created_at": "2026-07-08T09:00:00",
                    "updated_at": "2026-07-08T09:00:00",
                }
            )
        )

        with patch(
            "backend.h5_backend.routers.admin_clash_addresses.get_clash_address_service",
            return_value=service,
        ):
            response = client.post(
                "/api/admin/system/clash-addresses",
                json={
                    "name": "香港主线路",
                    "url": "https://proxy.example.com/sub?token=secret-token",
                    "is_active": True,
                    "remark": "机场 A",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertNotIn("secret-token", str(response.json()))
        service.create_address.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
