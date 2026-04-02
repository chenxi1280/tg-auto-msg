-- Drop legacy user-level subscription schema after license-slot migration.

ALTER TABLE IF EXISTS pricing_plans
    DROP COLUMN IF EXISTS max_tg_accounts;

ALTER TABLE IF EXISTS users
    DROP COLUMN IF EXISTS max_tg_accounts_override;

DROP TRIGGER IF EXISTS update_user_subscriptions_updated_at ON user_subscriptions;

DROP TABLE IF EXISTS subscription_notice_logs;
DROP TABLE IF EXISTS user_subscriptions;
