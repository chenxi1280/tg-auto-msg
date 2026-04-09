-- 回填历史旧卡密到当前省份超管归属，便于在新卡密中心统一展示

WITH target_super_admin AS (
    SELECT id
    FROM admin_accounts
    WHERE role_code = 'super_admin'
      AND status = 'active'
    ORDER BY id ASC
    LIMIT 1
)
UPDATE activation_cards AS card
SET creator_account_id = COALESCE(card.creator_account_id, target_super_admin.id),
    owner_account_id = COALESCE(card.owner_account_id, target_super_admin.id),
    root_master_account_id = COALESCE(card.root_master_account_id, target_super_admin.id),
    direct_parent_account_id = NULL,
    card_source_type = CASE
        WHEN COALESCE(NULLIF(card.card_source_type, ''), 'legacy') IN ('balance', 'credit', 'platform')
            THEN card.card_source_type
        ELSE 'legacy'
    END,
    settlement_unit_price_cents = COALESCE(
        card.settlement_unit_price_cents,
        (
            SELECT plan.price_cents
            FROM pricing_plans AS plan
            WHERE plan.plan_code = card.plan_code
            LIMIT 1
        )
    )
FROM target_super_admin
WHERE card.batch_id IS NULL;
