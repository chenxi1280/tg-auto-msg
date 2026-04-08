-- 完整 RBAC：角色、权限、角色权限、账号角色绑定

CREATE TABLE IF NOT EXISTS admin_roles (
    id SERIAL PRIMARY KEY,
    role_key VARCHAR(64) NOT NULL UNIQUE,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    status VARCHAR(20) DEFAULT 'active' NOT NULL,
    is_system BOOLEAN DEFAULT FALSE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_admin_roles_status ON admin_roles(status);

CREATE TABLE IF NOT EXISTS admin_permissions (
    id SERIAL PRIMARY KEY,
    permission_code VARCHAR(100) NOT NULL UNIQUE,
    module_key VARCHAR(50) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_admin_permissions_module ON admin_permissions(module_key);

CREATE TABLE IF NOT EXISTS admin_role_permissions (
    id SERIAL PRIMARY KEY,
    role_id INTEGER NOT NULL REFERENCES admin_roles(id) ON DELETE CASCADE,
    permission_id INTEGER NOT NULL REFERENCES admin_permissions(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_admin_role_permissions_role_permission UNIQUE (role_id, permission_id)
);

CREATE INDEX IF NOT EXISTS idx_admin_role_permissions_role ON admin_role_permissions(role_id);
CREATE INDEX IF NOT EXISTS idx_admin_role_permissions_permission ON admin_role_permissions(permission_id);

CREATE TABLE IF NOT EXISTS admin_account_roles (
    id SERIAL PRIMARY KEY,
    admin_account_id INTEGER NOT NULL REFERENCES admin_accounts(id) ON DELETE CASCADE,
    role_id INTEGER NOT NULL REFERENCES admin_roles(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT uq_admin_account_roles_account_role UNIQUE (admin_account_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_admin_account_roles_account ON admin_account_roles(admin_account_id);
CREATE INDEX IF NOT EXISTS idx_admin_account_roles_role ON admin_account_roles(role_id);

INSERT INTO admin_roles (role_key, display_name, description, status, is_system)
VALUES
    ('super_admin', '超管', '系统超管，拥有后台全部能力', 'active', TRUE),
    ('master_agent', '省总代', '省级总代，负责分销链路与审批', 'active', TRUE),
    ('sub_agent', '下级代理', '管理自己链路内的代理和批次', 'active', TRUE)
ON CONFLICT (role_key) DO UPDATE
SET
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    status = 'active',
    is_system = TRUE;

WITH defs(permission_code, module_key, display_name, description) AS (
    VALUES
        ('dashboard.read', 'dashboard', '查看仪表盘', '允许进入后台仪表盘'),
        ('security.read', 'security', '查看账户安全', '允许查看自己的后台账号安全信息'),
        ('security.update', 'security', '修改账户安全', '允许修改密码和 TG 绑定'),
        ('agents.read', 'agents', '查看代理', '允许查看代理树和后台账号列表'),
        ('agents.write', 'agents', '管理代理', '允许创建下级、调额和设置结算模式'),
        ('pricing.read', 'pricing', '查看统一价格', '允许查看统一价格'),
        ('pricing.write', 'pricing', '管理统一价格', '允许更新统一价格'),
        ('ledgers.read', 'ledgers', '查看自有流水', '允许查看自己的资金流水'),
        ('ledgers.read.visible', 'ledgers', '查看下级流水', '允许查看下级资金流水审计'),
        ('approvals.read', 'approvals', '查看审批', '允许查看审批中心'),
        ('approvals.approve', 'approvals', '审批通过', '允许审批通过请求'),
        ('approvals.reject', 'approvals', '审批驳回', '允许审批驳回请求'),
        ('approvals.batch', 'approvals', '批量审批', '允许批量通过或驳回审批'),
        ('batches.read', 'batches', '查看卡密批次', '允许查看批次和卡密明细'),
        ('batches.generate', 'batches', '生成卡密批次', '允许立即生成卡密或提交批次申请'),
        ('batches.export', 'batches', '导出卡密', '允许导出卡密 Excel'),
        ('batches.copy', 'batches', '复制卡密', '允许复制卡密'),
        ('audit.read', 'audit', '查看审计', '允许查看审计日志'),
        ('system.settings.read', 'system_settings', '查看系统配置', '允许查看购买入口和 Bot 公告栏'),
        ('system.settings.update', 'system_settings', '修改系统配置', '允许更新购买入口和 Bot 公告栏'),
        ('developer_apps.read', 'developer_apps', '查看开发者应用', '允许查看开发者应用池'),
        ('developer_apps.write', 'developer_apps', '管理开发者应用', '允许新增和编辑开发者应用'),
        ('developer_apps.check', 'developer_apps', '检查开发者应用', '允许健康检查与设置默认应用'),
        ('system_proxies.read', 'system_proxies', '查看系统代理', '允许查看系统代理池'),
        ('system_proxies.write', 'system_proxies', '管理系统代理', '允许新增和删除系统代理'),
        ('system_proxies.check', 'system_proxies', '检查系统代理', '允许检测系统代理健康'),
        ('system_proxies.assign', 'system_proxies', '分配系统代理', '允许分配或解绑系统代理'),
        ('legacy_cards.read', 'legacy_cards', '查看旧卡密', '允许查看旧卡密规格、卡密和授权'),
        ('legacy_cards.write', 'legacy_cards', '管理旧卡密', '允许修改旧卡密规格和生成卡密'),
        ('legacy_cards.export', 'legacy_cards', '导出旧卡密', '允许导出旧卡密列表'),
        ('users.read', 'users', '查看用户授权', '允许查看用户、TG 账号和授权'),
        ('users.write', 'users', '管理用户授权', '允许设置用户开发者应用和删除账号'),
        ('users.reset_password', 'users', '重置用户密码', '允许重置用户密码'),
        ('admin_accounts.read', 'admin_accounts', '查看后台账号', '允许查看后台账号列表'),
        ('admin_accounts.write', 'admin_accounts', '管理后台账号', '允许创建、编辑和分配后台账号角色'),
        ('admin_accounts.reset_password', 'admin_accounts', '重置后台密码', '允许重置后台账号密码'),
        ('rbac.roles.read', 'rbac_roles', '查看角色', '允许查看角色和角色权限'),
        ('rbac.roles.write', 'rbac_roles', '管理角色', '允许创建角色和修改角色权限'),
        ('rbac.permissions.read', 'rbac_permissions', '查看权限', '允许查看权限点字典')
)
INSERT INTO admin_permissions (permission_code, module_key, display_name, description)
SELECT permission_code, module_key, display_name, description FROM defs
ON CONFLICT (permission_code) DO UPDATE
SET
    module_key = EXCLUDED.module_key,
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description;

DELETE FROM admin_role_permissions
WHERE role_id IN (
    SELECT id FROM admin_roles WHERE role_key IN ('super_admin', 'master_agent', 'sub_agent')
);

INSERT INTO admin_role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM admin_roles r
JOIN admin_permissions p ON (
    r.role_key = 'super_admin'
    OR (
        r.role_key = 'master_agent'
        AND p.permission_code IN (
            'dashboard.read', 'security.read', 'security.update', 'agents.read', 'agents.write',
            'pricing.read', 'ledgers.read', 'ledgers.read.visible', 'approvals.read',
            'approvals.approve', 'approvals.reject', 'approvals.batch', 'batches.read',
            'batches.generate', 'batches.export', 'batches.copy', 'audit.read'
        )
    )
    OR (
        r.role_key = 'sub_agent'
        AND p.permission_code IN (
            'dashboard.read', 'security.read', 'security.update', 'agents.read', 'agents.write',
            'pricing.read', 'ledgers.read', 'approvals.read', 'approvals.approve',
            'approvals.reject', 'approvals.batch', 'batches.read', 'batches.generate',
            'batches.export', 'batches.copy', 'audit.read'
        )
    )
)
ON CONFLICT (role_id, permission_id) DO NOTHING;

INSERT INTO admin_account_roles (admin_account_id, role_id)
SELECT a.id, r.id
FROM admin_accounts a
JOIN admin_roles r ON r.role_key = a.role_code
ON CONFLICT (admin_account_id, role_id) DO NOTHING;
