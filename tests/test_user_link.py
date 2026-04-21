import unittest
from datetime import datetime, timedelta

from backend.bot.handlers.core.user_link import load_latest_linked_tg_user_ids, set_linked_system_user_id
from backend.database.schema.models import AppSetting


class _FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self, rows):
        self.rows = {row.key: row for row in rows}

    @staticmethod
    def _sort_key(updated_at, created_at, key):
        timestamp = updated_at or created_at or datetime.min
        created = created_at or datetime.min
        return (timestamp, created, key)

    async def get(self, _model, key):
        return self.rows.get(key)

    def add(self, row):
        self.rows[row.key] = row

    async def delete(self, row):
        self.rows.pop(row.key, None)

    async def execute(self, statement):
        raw_columns = getattr(statement, "_raw_columns", [])
        if raw_columns and not hasattr(raw_columns[0], "columns"):
            rows = []
            for row in self.rows.values():
                if not row.key.startswith("tg_user_link:"):
                    continue
                rows.append((row.key, row.value, row.updated_at, row.created_at))
            rows.sort(key=lambda item: self._sort_key(item[2], item[3], item[0]), reverse=True)
            return _FakeScalarResult(rows)

        rows = [row for row in self.rows.values() if row.key.startswith("tg_user_link:")]
        rows.sort(key=lambda row: self._sort_key(row.updated_at, row.created_at, row.key), reverse=True)
        return _FakeScalarResult(rows)


class UserLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_linked_system_user_id_prunes_stale_links_for_same_user(self):
        now = datetime(2026, 4, 21, 9, 0, 0)
        session = _FakeSession(
            [
                AppSetting(
                    key="tg_user_link:7880631297",
                    value="11",
                    created_at=now,
                    updated_at=now,
                ),
                AppSetting(
                    key="tg_user_mode:7880631297",
                    value="owner",
                    created_at=now,
                    updated_at=now,
                ),
                AppSetting(
                    key="tg_active_acc:7880631297:11",
                    value="acc-old",
                    created_at=now,
                    updated_at=now,
                ),
                AppSetting(
                    key="tg_user_scoped_acc:7880631297:11",
                    value="acc-old",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )

        await set_linked_system_user_id(session, 8071215277, 11)

        self.assertIn("tg_user_link:8071215277", session.rows)
        self.assertNotIn("tg_user_link:7880631297", session.rows)
        self.assertNotIn("tg_user_mode:7880631297", session.rows)
        self.assertNotIn("tg_active_acc:7880631297:11", session.rows)
        self.assertNotIn("tg_user_scoped_acc:7880631297:11", session.rows)

    async def test_load_latest_linked_tg_user_ids_prefers_most_recent_mapping(self):
        earlier = datetime(2026, 4, 20, 23, 0, 0)
        later = earlier + timedelta(minutes=45)
        session = _FakeSession(
            [
                AppSetting(
                    key="tg_user_link:7880631297",
                    value="11",
                    created_at=earlier,
                    updated_at=earlier,
                ),
                AppSetting(
                    key="tg_user_link:8071215277",
                    value="11",
                    created_at=later,
                    updated_at=later,
                ),
                AppSetting(
                    key="tg_user_link:1234567890",
                    value="12",
                    created_at=earlier,
                    updated_at=earlier,
                ),
            ]
        )

        links = await load_latest_linked_tg_user_ids(session)

        self.assertEqual(links, {11: 8071215277, 12: 1234567890})


if __name__ == "__main__":
    unittest.main()
