from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from backend.bot.account.proxy_observation import (
    SING_BOX_PROXY_REGIONS,
    get_proxy_region_options,
    is_proxy_observation_active,
    mark_proxy_observation_success,
    proxy_observation_has_send_budget,
    proxy_observation_remaining_seconds,
    start_proxy_observation,
)


def test_fixed_sing_box_regions_are_stable():
    options = get_proxy_region_options()

    assert [item["region_code"] for item in options] == ["hk", "tw", "jp", "sg", "us1", "us2", "uk"]
    assert [item["port"] for item in options] == [10801, 10802, 10803, 10804, 10805, 10806, 10807]
    assert all(item["host"] == "sing-box" for item in options)
    assert len(SING_BOX_PROXY_REGIONS) == 7


def test_proxy_observation_starts_24_hour_window_with_one_success_budget():
    now = datetime(2026, 5, 9, 10, 0, 0)
    account = SimpleNamespace(
        proxy_observation_started_at=None,
        proxy_observation_until=None,
        proxy_observation_success_count=9,
    )

    start_proxy_observation(account, now=now)

    assert account.proxy_observation_started_at == now
    assert account.proxy_observation_until == now + timedelta(hours=24)
    assert account.proxy_observation_success_count == 0
    assert is_proxy_observation_active(account, now)
    assert proxy_observation_has_send_budget(account, now)
    assert proxy_observation_remaining_seconds(account, now) == 24 * 3600

    account.proxy_observation_success_count = 1
    assert not proxy_observation_has_send_budget(account, now)


def test_proxy_observation_expires_without_manual_unlock():
    now = datetime(2026, 5, 9, 10, 0, 0)
    account = SimpleNamespace(
        proxy_observation_until=now - timedelta(seconds=1),
        proxy_observation_success_count=1,
    )

    assert not is_proxy_observation_active(account, now)
    assert proxy_observation_has_send_budget(account, now)


@pytest.mark.asyncio
async def test_proxy_observation_success_count_is_capped():
    now = datetime(2026, 5, 9, 10, 0, 0)
    account = SimpleNamespace(
        proxy_observation_until=now + timedelta(hours=1),
        proxy_observation_success_count=1,
    )

    class FakeSession:
        async def get(self, model, account_id):
            return account

    count = await mark_proxy_observation_success(FakeSession(), "acc-1", now=now)

    assert count == 1
    assert account.proxy_observation_success_count == 1
