-- Close deprecated batch_purchase approval requests after the flow is removed.
UPDATE approval_requests
SET
    status = 'rejected',
    rejected_at = COALESCE(rejected_at, NOW()),
    updated_at = NOW()
WHERE request_type = 'batch_purchase'
  AND status = 'pending';
