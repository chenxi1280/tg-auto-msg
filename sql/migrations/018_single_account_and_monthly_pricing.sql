-- 单系统账号只保留 1 个当前 TG 账号，并统一收费信息为 100 元 / 月

WITH ranked_accounts AS (
    SELECT
        account_id,
        user_id,
        ROW_NUMBER() OVER (
            PARTITION BY user_id
            ORDER BY
                CASE WHEN is_active THEN 1 ELSE 0 END DESC,
                CASE WHEN health_status = 'online' THEN 1 ELSE 0 END DESC,
                COALESCE(last_used_at, created_at) DESC,
                created_at DESC,
                account_id ASC
        ) AS rn
    FROM accounts
)
UPDATE accounts AS a
SET is_active = FALSE
FROM ranked_accounts AS r
WHERE a.account_id = r.account_id
  AND r.rn > 1
  AND a.is_active = TRUE;

WITH ranked_accounts AS (
    SELECT
        account_id,
        user_id,
        ROW_NUMBER() OVER (
            PARTITION BY user_id
            ORDER BY
                CASE WHEN is_active THEN 1 ELSE 0 END DESC,
                CASE WHEN health_status = 'online' THEN 1 ELSE 0 END DESC,
                COALESCE(last_used_at, created_at) DESC,
                created_at DESC,
                account_id ASC
        ) AS rn
    FROM accounts
)
UPDATE scheduled_message_tasks
SET enabled = FALSE
WHERE account_id IN (
    SELECT account_id
    FROM ranked_accounts
    WHERE rn > 1
);

INSERT INTO pricing_plans (
    plan_code,
    display_name,
    billing_cycle,
    price_cents,
    duration_days,
    is_active,
    sort_order
)
VALUES
    ('monthly', '月付Key', 'monthly', 10000, 30, TRUE, 10)
ON CONFLICT (plan_code) DO UPDATE
SET
    display_name = EXCLUDED.display_name,
    billing_cycle = EXCLUDED.billing_cycle,
    price_cents = EXCLUDED.price_cents,
    duration_days = EXCLUDED.duration_days,
    is_active = EXCLUDED.is_active,
    sort_order = EXCLUDED.sort_order;

UPDATE pricing_plans
SET is_active = FALSE
WHERE plan_code <> 'monthly';
