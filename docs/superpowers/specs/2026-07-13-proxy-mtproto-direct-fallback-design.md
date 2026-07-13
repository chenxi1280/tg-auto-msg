# Proxy MTProto Health And Direct Fallback Design

Date: 2026-07-13

## Goal

Replace the production sing-box subscription and ensure an explicitly proxy-bound Telegram account permanently falls back to the server's direct connection when its proxy cannot complete Telegram MTProto communication.

## Runtime Behavior

Before resolving a proxy-bound account client for a send, the application checks the selected proxy with a bounded Telegram MTProto probe. A successful SOCKS TCP connection alone is not considered healthy.

Probe results are cached for a short, expiring interval to avoid opening a new Telegram probe for every target. A cached result must never remain healthy indefinitely.

When the MTProto probe fails, the application:

1. Marks the proxy unhealthy.
2. Permanently removes the proxy binding from the account.
3. Closes and evicts any cached client created with that proxy.
4. Resolves a new client without a proxy in the same task execution.
5. Continues sending through the server's direct route.

Accounts without an explicit proxy binding remain direct by default. The runtime does not automatically assign a replacement proxy.

## Delivery Safety

The direct fallback happens before a Telegram send starts. If a connection fails after a send has started and Telegram delivery is uncertain, the runtime does not automatically resend the same target through the direct route. This avoids duplicate messages. The failed proxy is still removed for later executions.

## Proxy Subscription Update

The supplied subscription URL becomes the production source file at `/data/infra/sing-box/subscription.url`. The update sequence is:

1. Render the supplied URL with the production sync script in dry-run mode.
2. Back up the existing subscription and rendered config.
3. Apply the new subscription and render a new config.
4. Restart `app-infra-sing-box` so the new config is loaded.
5. Probe every configured system gateway from `tgmsg-app` with Telegram MTProto, not only TCP.
6. Synchronize database proxy health with the probe results.

The subscription token must not be printed in logs, committed to Git, or stored in this design document.

## Components

- `backend/bot/proxy/health.py`: bounded MTProto probe and expiring health cache behavior.
- `backend/bot/proxy/pool.py`: cache lifetime state and proxy health facade.
- `backend/bot/account/client_runtime.py`: permanent unbind, cached-client eviction, and same-execution direct client resolution.
- `tests/test_account_client_runtime_proxy.py`: account fallback regression coverage.
- Proxy health tests: MTProto success, failure, and cache expiry coverage.
- Deployment documentation: record that production proxy verification requires MTProto success.

## Error Handling

- A failed MTProto probe is explicit and logged with proxy ID and error type, without credentials.
- Database updates or client cleanup failures surface as errors; the runtime does not claim that direct fallback succeeded.
- If direct client creation also fails, the task fails normally with the original failure visible.
- No mock-success or TCP-only fallback path is introduced.

## Verification

Automated verification covers:

- Healthy proxy remains bound.
- Failed system gateway becomes unhealthy and is permanently unbound.
- The cached proxy client is closed before direct client creation.
- The same task resolution path requests a direct client after unbinding.
- Health cache expires and re-probes.
- A TCP-open but MTProto-broken proxy is classified unhealthy.

Production verification covers:

- New subscription render and sing-box config validation.
- New sing-box process start time.
- Per-region MTProto probe results from `tgmsg-app`.
- Direct MTProto probe from the server.
- Affected account proxy binding and client state.
- Scheduler task completion and absence of a new reconnect storm.
