-- 统一用户可见的规格展示文案：Key -> 卡密

UPDATE pricing_plans
SET display_name = CASE
    WHEN plan_code = 'monthly' THEN '月付卡密'
    WHEN plan_code = 'yearly' THEN '年付卡密'
    WHEN display_name LIKE '%Key%' THEN replace(display_name, 'Key', '卡密')
    ELSE display_name
END
WHERE plan_code IN ('monthly', 'yearly')
   OR display_name LIKE '%Key%';
