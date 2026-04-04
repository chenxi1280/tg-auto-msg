-- Backfill legacy used activation cards into slot-based licenses.
-- Idempotent: only processes cards that have no entry in user_authorization_cards.

WITH legacy_used_cards AS (
    SELECT
        c.id AS activation_card_id,
        c.used_by_user_id AS user_id,
        COALESCE(
            NULLIF(c.duration_days, 0),
            p.duration_days,
            0
        ) AS duration_days,
        COALESCE(c.used_at, c.created_at, NOW()) AS start_at
    FROM activation_cards c
    LEFT JOIN pricing_plans p ON p.plan_code = c.plan_code
    LEFT JOIN user_authorization_cards usc ON usc.activation_card_id = c.id
    WHERE c.is_used = TRUE
      AND c.used_by_user_id IS NOT NULL
      AND usc.id IS NULL
),
prepared AS (
    SELECT
        md5('legacy-slot-' || l.activation_card_id::text) AS authorization_id,
        l.activation_card_id,
        l.user_id,
        l.duration_days,
        l.start_at,
        (l.start_at + (l.duration_days || ' days')::interval) AS end_at
    FROM legacy_used_cards l
    WHERE l.duration_days > 0
)
INSERT INTO user_authorizations (
    authorization_id,
    user_id,
    current_account_id,
    source_card_id,
    total_duration_days,
    start_at,
    end_at,
    status,
    created_at,
    updated_at
)
SELECT
    p.authorization_id,
    p.user_id,
    NULL,
    p.activation_card_id,
    p.duration_days,
    p.start_at,
    p.end_at,
    CASE WHEN p.end_at > NOW() THEN 'active' ELSE 'expired' END,
    NOW(),
    NOW()
FROM prepared p
ON CONFLICT (authorization_id) DO NOTHING;

WITH legacy_used_cards AS (
    SELECT
        c.id AS activation_card_id,
        c.used_by_user_id AS user_id,
        COALESCE(
            NULLIF(c.duration_days, 0),
            p.duration_days,
            0
        ) AS duration_days,
        COALESCE(c.used_at, c.created_at, NOW()) AS start_at
    FROM activation_cards c
    LEFT JOIN pricing_plans p ON p.plan_code = c.plan_code
    LEFT JOIN user_authorization_cards usc ON usc.activation_card_id = c.id
    WHERE c.is_used = TRUE
      AND c.used_by_user_id IS NOT NULL
      AND usc.id IS NULL
),
prepared AS (
    SELECT
        md5('legacy-slot-' || l.activation_card_id::text) AS authorization_id,
        l.activation_card_id,
        l.user_id,
        l.duration_days,
        l.start_at
    FROM legacy_used_cards l
    WHERE l.duration_days > 0
)
INSERT INTO user_authorization_cards (
    authorization_id,
    activation_card_id,
    duration_days,
    applied_at
)
SELECT
    p.authorization_id,
    p.activation_card_id,
    p.duration_days,
    p.start_at
FROM prepared p
ON CONFLICT (activation_card_id) DO NOTHING;
