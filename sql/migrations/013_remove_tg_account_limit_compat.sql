-- Final cleanup for removed TG account limit compatibility.

ALTER TABLE IF EXISTS pricing_plans
    DROP COLUMN IF EXISTS max_tg_accounts;

ALTER TABLE IF EXISTS users
    DROP COLUMN IF EXISTS max_tg_accounts_override;
