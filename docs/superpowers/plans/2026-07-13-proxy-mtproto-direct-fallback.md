# Proxy MTProto Direct Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect unusable Telegram proxy gateways with an MTProto probe, permanently unbind them, and resolve the affected account directly in the same scheduled task.

**Architecture:** Replace TCP-only proxy health with a bounded anonymous Telethon `GetConfigRequest` probe and cache its result for a finite interval. Make `ensure_account_proxy()` check every explicitly bound proxy, including system gateways; a failed probe marks the proxy unhealthy, closes its cached client, removes the account binding, and lets the existing client resolver create a direct client.

**Tech Stack:** Python 3.11, Telethon, SQLAlchemy async, unittest/pytest, sing-box, Docker Compose.

---

### Task 1: Cover System Gateway Failure And MTProto Health Caching

**Files:**
- Modify: `tests/test_account_client_runtime_proxy.py`
- Create: `tests/test_proxy_health.py`

- [ ] **Step 1: Write a failing system-gateway fallback test**

```python
async def test_healthy_flagged_system_gateway_is_unbound_when_mtproto_check_fails():
    manager = SimpleNamespace(
        _clients={"account-1": AsyncMock()}, _locks={},
        get_account=AsyncMock(return_value=SimpleNamespace(proxy_id=1)),
        update_account=AsyncMock(),
    )
    proxy_pool = SimpleNamespace(
        get_proxy=AsyncMock(return_value=SimpleNamespace(
            proxy_id=1, is_system_gateway=True, is_active=True, is_healthy=True,
        )),
        check_health=AsyncMock(return_value=SimpleNamespace(
            is_healthy=False, error="IncompleteReadError",
        )),
        unassign_proxy=AsyncMock(),
    )

    with patch("backend.bot.proxy.pool.get_proxy_pool", return_value=proxy_pool):
        assert await ensure_account_proxy(manager, "account-1") is None

    proxy_pool.check_health.assert_awaited_once_with(1)
    proxy_pool.unassign_proxy.assert_awaited_once_with("account-1")
    manager.update_account.assert_awaited_once_with("account-1", proxy_id=None)
```

- [ ] **Step 2: Write failing MTProto probe and finite-cache tests**

```python
async def test_mtproto_failure_marks_proxy_unhealthy():
    manager = proxy_manager_fixture()
    with patch(
        "backend.bot.proxy.health.probe_telegram_proxy",
        AsyncMock(side_effect=IncompleteReadError(b"", 8)),
    ):
        result = await check_health(manager, proxy_id=1, timeout=10, status_factory=HealthStatus)
    assert result.is_healthy is False
    assert "IncompleteReadError" in result.error
    manager.update_proxy.assert_awaited_once()

async def test_expired_healthy_cache_reprobes_mtproto():
    manager = proxy_manager_fixture(cache_ttl=60)
    with patch("backend.bot.proxy.health.probe_telegram_proxy", AsyncMock(return_value=12)) as probe:
        await check_health(manager, proxy_id=1, timeout=10, status_factory=HealthStatus)
        manager._health_cache_checked_at[1] = 0
        with patch("backend.bot.proxy.health.time.monotonic", return_value=61):
            await check_health(manager, proxy_id=1, timeout=10, status_factory=HealthStatus)
    assert probe.await_count == 2
```

- [ ] **Step 3: Run the focused tests and confirm RED**

Run: `.venv/bin/python -m pytest tests/test_account_client_runtime_proxy.py tests/test_proxy_health.py -q`

Expected: FAIL because system gateways bypass `check_health`, `probe_telegram_proxy` does not exist, and the cache never expires.

### Task 2: Implement MTProto Health And Permanent Direct Fallback

**Files:**
- Modify: `backend/bot/proxy/health.py`
- Modify: `backend/bot/proxy/pool.py`
- Modify: `backend/bot/account/client_runtime.py`

- [ ] **Step 1: Add a bounded anonymous Telegram probe**

```python
async def probe_telegram_proxy(proxy_config: Dict[str, Any], *, api_id: int, api_hash: str, timeout: int) -> int:
    client = TelegramClient(
        StringSession(), api_id=api_id, api_hash=api_hash, proxy=proxy_config,
        timeout=timeout, connection_retries=1, request_retries=1,
        retry_delay=1, auto_reconnect=False,
    )
    started_at = time.monotonic()
    try:
        async with asyncio.timeout(timeout):
            await client.connect()
            await client(GetConfigRequest())
        return int((time.monotonic() - started_at) * 1000)
    finally:
        await client.disconnect()
```

Use `settings.api_id` and `settings.api_hash` for generic proxy checks. A missing credential is an explicit unhealthy result, not a TCP-only success.

- [ ] **Step 2: Add finite proxy health cache metadata**

```python
HEALTH_CACHE_TTL_SECONDS = 60

class ProxyPool:
    def __init__(self):
        self._health_cache = {}
        self._health_cache_checked_at = {}
        self._cache_ttl = HEALTH_CACHE_TTL_SECONDS
```

Return a cached healthy status only while `time.monotonic() - checked_at < _cache_ttl`. Persist every completed probe with `update_proxy()` and cache both its status and check time.

- [ ] **Step 3: Remove the system-gateway bypass**

```python
status = await proxy_pool.check_health(account.proxy_id)
if status.is_healthy:
    return account.proxy_id

logger.warning(
    "账号 {} 的代理 {} 无法完成 Telegram 通信({})，永久解除绑定后使用直连",
    account_id, account.proxy_id, status.error or "unknown",
)
await proxy_pool.unassign_proxy(account_id)
await manager.update_account(account_id, proxy_id=None)
await close_client(manager, account_id)
return None
```

The existing `_resolve_client()` sequence calls `ensure_account_proxy()` before `get_client()`, so the database refresh inside `get_client()` constructs the direct client in the same task without a second send attempt.

- [ ] **Step 4: Run the focused tests and confirm GREEN**

Run: `.venv/bin/python -m pytest tests/test_account_client_runtime_proxy.py tests/test_proxy_health.py -q`

Expected: all focused tests pass.

### Task 3: Record Verification Requirements And Apply The New Subscription

**Files:**
- Modify: `docs/deployment/PRODUCTION_RUNTIME.md`
- Production-only: `/data/infra/sing-box/subscription.url`

- [ ] **Step 1: Document MTProto verification**

Add the requirement that a proxy update must prove an anonymous Telegram MTProto request through each enabled gateway; TCP listener reachability alone is insufficient.

- [ ] **Step 2: Validate the supplied subscription without exposing its token**

Run the production renderer with a temporary, mode-600 URL file:

```bash
SING_BOX_SUBSCRIPTION_URL_FILE=/run/tgmsg-subscription.url \
  sudo -n /data/infra/compose/deploy/sync-sing-box.sh --dry-run
```

Expected: rendered JSON and `sing-box check` both succeed.

- [ ] **Step 3: Apply and reload sing-box**

Atomically replace `/data/infra/sing-box/subscription.url`, run `sync-sing-box.sh`, then explicitly restart `app-infra-sing-box`. Confirm that `docker inspect` reports a new `StartedAt` value.

- [ ] **Step 4: Verify every enabled gateway with MTProto**

From `tgmsg-app`, run a bounded anonymous `TelegramClient(..., proxy=...)` plus `GetConfigRequest` probe for every active system gateway. Mark failed rows unhealthy and leave successful rows active.

### Task 4: Full Verification, Release, And Production Acceptance

**Files:**
- Verify: `tests/test_account_client_runtime_proxy.py`
- Verify: `tests/test_proxy_health.py`
- Verify: `tests/test_clash_address_service.py`
- Verify: `docs/deployment/PRODUCTION_RUNTIME.md`

- [ ] **Step 1: Run local checks**

Run: `.venv/bin/python -m pytest tests/test_account_client_runtime_proxy.py tests/test_proxy_health.py tests/test_clash_address_service.py -q && .venv/bin/python -m py_compile backend/bot/proxy/health.py backend/bot/proxy/pool.py backend/bot/account/client_runtime.py`

Expected: exit code 0.

- [ ] **Step 2: Commit the code and documentation**

```bash
git add backend/bot/proxy/health.py backend/bot/proxy/pool.py backend/bot/account/client_runtime.py \
  tests/test_account_client_runtime_proxy.py tests/test_proxy_health.py docs/deployment/PRODUCTION_RUNTIME.md \
  docs/superpowers/plans/2026-07-13-proxy-mtproto-direct-fallback.md
git commit -m "fix: fall back to direct on proxy mtproto failure"
```

- [ ] **Step 3: Push release and verify deployment**

Run: `git push origin release`, then inspect the `Deploy Production` run until `checks`, `build-images`, and `deploy` succeed.

- [ ] **Step 4: Verify the actual production runtime**

Confirm the deployed commit/image, `tgmsg-app` health, `/api/health/runtime`, direct MTProto, per-gateway MTProto, affected account `proxy_id=NULL`, and a scheduler execution without a new 240-second timeout.
