-- 账号级固定代理与 24 小时观察期

ALTER TABLE IF EXISTS proxies
    ADD COLUMN IF NOT EXISTS display_name VARCHAR(100),
    ADD COLUMN IF NOT EXISTS region_code VARCHAR(20),
    ADD COLUMN IF NOT EXISTS is_system_gateway BOOLEAN DEFAULT FALSE NOT NULL,
    ADD COLUMN IF NOT EXISTS is_shared BOOLEAN DEFAULT FALSE NOT NULL;

CREATE INDEX IF NOT EXISTS idx_proxies_region_gateway
    ON proxies(region_code, is_system_gateway);

ALTER TABLE IF EXISTS accounts
    ADD COLUMN IF NOT EXISTS proxy_observation_started_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS proxy_observation_until TIMESTAMP,
    ADD COLUMN IF NOT EXISTS proxy_observation_success_count INTEGER DEFAULT 0 NOT NULL;

CREATE INDEX IF NOT EXISTS idx_accounts_proxy_observation_until
    ON accounts(proxy_observation_until);
