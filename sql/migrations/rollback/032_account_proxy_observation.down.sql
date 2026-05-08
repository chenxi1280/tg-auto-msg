DROP INDEX IF EXISTS idx_accounts_proxy_observation_until;

ALTER TABLE IF EXISTS accounts
    DROP COLUMN IF EXISTS proxy_observation_success_count,
    DROP COLUMN IF EXISTS proxy_observation_until,
    DROP COLUMN IF EXISTS proxy_observation_started_at;

DROP INDEX IF EXISTS idx_proxies_region_gateway;

ALTER TABLE IF EXISTS proxies
    DROP COLUMN IF EXISTS is_shared,
    DROP COLUMN IF EXISTS is_system_gateway,
    DROP COLUMN IF EXISTS region_code,
    DROP COLUMN IF EXISTS display_name;
