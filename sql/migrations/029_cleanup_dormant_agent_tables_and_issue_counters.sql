-- @statement
ALTER TABLE task_target_send_issues
    ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER DEFAULT 0 NOT NULL;

-- @statement
DO $$
DECLARE
    approval_count BIGINT := 0;
    plan_price_count BIGINT := 0;
BEGIN
    IF to_regclass('approval_requests') IS NOT NULL THEN
        EXECUTE 'SELECT COUNT(*) FROM approval_requests' INTO approval_count;
    END IF;

    IF to_regclass('agent_plan_prices') IS NOT NULL THEN
        EXECUTE 'SELECT COUNT(*) FROM agent_plan_prices' INTO plan_price_count;
    END IF;

    IF approval_count > 0 OR plan_price_count > 0 THEN
        RAISE EXCEPTION
            'Refusing to drop dormant tables with existing data: approval_requests=% , agent_plan_prices=%',
            approval_count,
            plan_price_count;
    END IF;
END $$;

-- @statement
DROP TABLE IF EXISTS approval_requests;

-- @statement
DROP TABLE IF EXISTS agent_plan_prices;
