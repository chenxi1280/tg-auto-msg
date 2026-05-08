-- Update monthly card pricing to 120 yuan/month and prepare the optional second purchase button.

UPDATE pricing_plans
SET
    price_cents = 12000,
    duration_days = 30,
    billing_cycle = 'monthly',
    is_active = TRUE
WHERE plan_code = 'monthly';

INSERT INTO app_settings (key, value)
SELECT
    'purchase_buttons',
    json_build_array(
        json_build_object(
            'text',
            COALESCE(NULLIF(TRIM(purchase_button_text.value), ''), '联系 Telegram 购买'),
            'url',
            COALESCE(NULLIF(TRIM(purchase_url.value), ''), 'https://t.me/')
        )
    )::text
FROM
    (SELECT value FROM app_settings WHERE key = 'purchase_url') AS purchase_url
    FULL JOIN (SELECT value FROM app_settings WHERE key = 'purchase_button_text') AS purchase_button_text ON TRUE
ON CONFLICT (key) DO NOTHING;
