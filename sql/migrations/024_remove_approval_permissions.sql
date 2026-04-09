-- 去审批化后，移除审批权限点及其角色绑定

DELETE FROM admin_role_permissions
WHERE permission_id IN (
    SELECT id
    FROM admin_permissions
    WHERE permission_code IN (
        'approvals.read',
        'approvals.approve',
        'approvals.reject',
        'approvals.batch'
    )
);

DELETE FROM admin_permissions
WHERE permission_code IN (
    'approvals.read',
    'approvals.approve',
    'approvals.reject',
    'approvals.batch'
);
