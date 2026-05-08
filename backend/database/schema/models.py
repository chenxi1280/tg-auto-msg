"""
数据库模型定义
"""
from datetime import datetime
from typing import Optional, List, Any
from enum import Enum
import uuid

from sqlalchemy import (
    Column, String, Integer, BigInteger, Boolean, DateTime, Text, Index,
    Enum as SQLEnum, JSON, func, ForeignKey, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, relationship

Base = declarative_base()


class User(Base):
    """系统用户表"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, comment="用户名")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="密码哈希")
    bot_initial_password_encrypted: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True, comment="Bot自动注册初始密码（加密）")
    bot_initial_password_viewable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否允许在Bot中查看初始密码")
    password_changed_after_bot_registration: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="Bot自动注册后是否已修改密码")
    bot_trial_eligible_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="Bot首绑试用资格获得时间")
    bot_trial_granted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="Bot首绑试用授权发放时间")
    bot_trial_authorization_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, comment="Bot首绑试用授权ID")
    email: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="邮箱")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否激活")
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    accounts: Mapped[List["Account"]] = relationship("Account", back_populates="user", cascade="all, delete-orphan")
    activated_cards: Mapped[List["ActivationCard"]] = relationship(
        "ActivationCard",
        back_populates="used_by_user",
    )
    authorizations: Mapped[List["UserAuthorization"]] = relationship(
        "UserAuthorization",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class AdminAccount(Base):
    """后台管理员 / 代理账号。"""
    __tablename__ = "admin_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="后台登录名")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="密码哈希")
    role_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="角色代码")
    account_type: Mapped[str] = mapped_column(String(20), default="staff", nullable=False, comment="账号类型")
    business_identity: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, comment="业务身份")
    province_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="省份编码")
    parent_account_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("admin_accounts.id", ondelete="SET NULL"),
        nullable=True,
        comment="直接上级账号 ID",
    )
    root_master_account_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("admin_accounts.id", ondelete="SET NULL"),
        nullable=True,
        comment="省总代账号 ID",
    )
    level_depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="层级深度")
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, comment="状态")
    settlement_mode: Mapped[str] = mapped_column(String(20), default="prepaid", nullable=False, comment="结算模式")
    is_credit_whitelisted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否授信白名单")
    credit_limit_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False, comment="总额度")
    allocated_credit_limit_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False, comment="已分配额度总和")
    credit_used_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False, comment="已使用额度")
    credit_prepay_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False, comment="授信预抵金额")
    balance_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False, comment="余额")
    force_password_change: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否强制改密")
    display_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="展示名称")
    contact_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="联系人")
    contact_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="联系电话")
    created_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="创建人账号 ID")
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="最近登录时间")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    parent_account: Mapped[Optional["AdminAccount"]] = relationship(
        "AdminAccount",
        remote_side=[id],
        foreign_keys=[parent_account_id],
        back_populates="children",
    )
    children: Mapped[List["AdminAccount"]] = relationship(
        "AdminAccount",
        foreign_keys=[parent_account_id],
        back_populates="parent_account",
    )
    tg_binding: Mapped[Optional["AdminAccountTgBinding"]] = relationship(
        "AdminAccountTgBinding",
        back_populates="admin_account",
        cascade="all, delete-orphan",
        uselist=False,
    )
    role_bindings: Mapped[List["AdminAccountRole"]] = relationship(
        "AdminAccountRole",
        back_populates="admin_account",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_admin_accounts_role_status", "role_code", "status"),
        Index("idx_admin_accounts_type_status", "account_type", "status"),
        Index("idx_admin_accounts_business_identity", "business_identity"),
        Index("idx_admin_accounts_parent", "parent_account_id"),
        Index("idx_admin_accounts_root_master", "root_master_account_id"),
        Index("idx_admin_accounts_province_role", "province_code", "role_code"),
    )


class AdminRole(Base):
    """后台 RBAC 角色。"""
    __tablename__ = "admin_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, comment="角色唯一键")
    display_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="角色名称")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="角色说明")
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, comment="状态")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否系统内置角色")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    permission_bindings: Mapped[List["AdminRolePermission"]] = relationship(
        "AdminRolePermission",
        back_populates="role",
        cascade="all, delete-orphan",
    )
    account_bindings: Mapped[List["AdminAccountRole"]] = relationship(
        "AdminAccountRole",
        back_populates="role",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_admin_roles_status", "status"),
    )


class AdminPermission(Base):
    """后台 RBAC 权限点。"""
    __tablename__ = "admin_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    permission_code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, comment="权限代码")
    module_key: Mapped[str] = mapped_column(String(50), nullable=False, comment="模块键")
    display_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="权限名称")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="权限说明")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    role_bindings: Mapped[List["AdminRolePermission"]] = relationship(
        "AdminRolePermission",
        back_populates="permission",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_admin_permissions_module", "module_key"),
    )


class AdminRolePermission(Base):
    """角色与权限点绑定。"""
    __tablename__ = "admin_role_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("admin_roles.id", ondelete="CASCADE"),
        nullable=False,
        comment="角色 ID",
    )
    permission_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("admin_permissions.id", ondelete="CASCADE"),
        nullable=False,
        comment="权限 ID",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    role: Mapped["AdminRole"] = relationship("AdminRole", back_populates="permission_bindings")
    permission: Mapped["AdminPermission"] = relationship("AdminPermission", back_populates="role_bindings")

    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_admin_role_permissions_role_permission"),
        Index("idx_admin_role_permissions_role", "role_id"),
        Index("idx_admin_role_permissions_permission", "permission_id"),
    )


class AdminAccountRole(Base):
    """后台账号与角色绑定。"""
    __tablename__ = "admin_account_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("admin_accounts.id", ondelete="CASCADE"),
        nullable=False,
        comment="后台账号 ID",
    )
    role_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("admin_roles.id", ondelete="CASCADE"),
        nullable=False,
        comment="角色 ID",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    admin_account: Mapped["AdminAccount"] = relationship("AdminAccount", back_populates="role_bindings")
    role: Mapped["AdminRole"] = relationship("AdminRole", back_populates="account_bindings")

    __table_args__ = (
        UniqueConstraint("admin_account_id", "role_id", name="uq_admin_account_roles_account_role"),
        Index("idx_admin_account_roles_account", "admin_account_id"),
        Index("idx_admin_account_roles_role", "role_id"),
    )


class AdminAccountTgBinding(Base):
    """后台账号 TG 绑定关系。"""
    __tablename__ = "admin_account_tg_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("admin_accounts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        comment="后台账号 ID",
    )
    tg_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, unique=True, comment="TG 用户 ID")
    tg_username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="TG 用户名")
    bind_status: Mapped[str] = mapped_column(String(20), default="unbound", nullable=False, comment="绑定状态")
    bind_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, comment="绑定码")
    bind_code_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="绑定码过期时间")
    bound_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="绑定时间")
    unbound_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="解绑时间")
    bound_by_account_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="发起绑定的后台账号 ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    admin_account: Mapped["AdminAccount"] = relationship("AdminAccount", back_populates="tg_binding")

    __table_args__ = (
        Index("idx_admin_tg_bindings_account", "admin_account_id"),
        Index("idx_admin_tg_bindings_tg_user", "tg_user_id"),
        Index("idx_admin_tg_bindings_status", "bind_status"),
    )


class AgentCreditLimit(Base):
    """代理上下级额度配置。"""
    __tablename__ = "agent_credit_limits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("admin_accounts.id", ondelete="CASCADE"),
        nullable=False,
        comment="直接上级账号 ID",
    )
    child_account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("admin_accounts.id", ondelete="CASCADE"),
        nullable=False,
        comment="直接下级账号 ID",
    )
    delegated_credit_limit_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False, comment="受限额度")
    delegated_credit_used_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False, comment="已使用受限额度")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否有效")
    last_adjusted_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="最近调整人账号 ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("parent_account_id", "child_account_id", name="uq_agent_credit_limits_parent_child"),
        Index("idx_agent_credit_limits_parent", "parent_account_id"),
        Index("idx_agent_credit_limits_child", "child_account_id"),
    )


class CardBatch(Base):
    """卡密批次。"""
    __tablename__ = "card_batches"

    batch_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    province_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="省份编码")
    creator_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("admin_accounts.id", ondelete="RESTRICT"), nullable=False)
    owner_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("admin_accounts.id", ondelete="RESTRICT"), nullable=False)
    direct_parent_account_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("admin_accounts.id", ondelete="SET NULL"), nullable=True)
    root_master_account_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("admin_accounts.id", ondelete="SET NULL"), nullable=True)
    current_liability_account_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("admin_accounts.id", ondelete="SET NULL"),
        nullable=True,
        comment="当前对上欠款责任账号 ID",
    )
    current_counterparty_account_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("admin_accounts.id", ondelete="SET NULL"),
        nullable=True,
        comment="当前应结算到的上级账号 ID，为空表示平台侧",
    )
    plan_code: Mapped[str] = mapped_column(String(32), ForeignKey("pricing_plans.plan_code", ondelete="CASCADE"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, comment="数量")
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False, comment="时长天数")
    unit_price_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="单价快照")
    total_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="总金额")
    settlement_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, comment="结算状态")
    payment_status: Mapped[str] = mapped_column(String(20), default="unpaid", nullable=False, comment="支付状态")
    export_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="导出次数")
    last_exported_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="最近导出时间")
    remark: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="备注")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    cards: Mapped[List["ActivationCard"]] = relationship("ActivationCard", back_populates="batch")

    __table_args__ = (
        Index("idx_card_batches_owner", "owner_account_id"),
        Index("idx_card_batches_parent", "direct_parent_account_id"),
        Index("idx_card_batches_root_master", "root_master_account_id"),
        Index("idx_card_batches_liability", "current_liability_account_id"),
        Index("idx_card_batches_status", "settlement_status", "payment_status"),
        Index("idx_card_batches_created_at", "created_at"),
    )


class AgentFundLedger(Base):
    """代理资金与额度流水。"""
    __tablename__ = "agent_fund_ledgers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ledger_scope: Mapped[str] = mapped_column(String(20), nullable=False, comment="platform/channel")
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("admin_accounts.id", ondelete="CASCADE"), nullable=False)
    counterparty_account_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("admin_accounts.id", ondelete="SET NULL"), nullable=True)
    biz_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="业务类型")
    direction: Mapped[str] = mapped_column(String(16), nullable=False, comment="资金方向")
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="金额")
    balance_after_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="变更后余额")
    credit_used_after_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="变更后额度占用")
    related_batch_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("card_batches.batch_id", ondelete="SET NULL"), nullable=True)
    related_request_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, comment="关联审批请求")
    remark: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="备注")
    operator_account_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("admin_accounts.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_agent_fund_ledgers_account", "account_id"),
        Index("idx_agent_fund_ledgers_scope", "ledger_scope"),
        Index("idx_agent_fund_ledgers_batch", "related_batch_id"),
        Index("idx_agent_fund_ledgers_created_at", "created_at"),
    )


class PricingPlan(Base):
    """Key 规格配置"""
    __tablename__ = "pricing_plans"

    plan_code: Mapped[str] = mapped_column(String(32), primary_key=True, comment="Key规格编码：monthly/yearly")
    display_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="Key规格展示名称")
    billing_cycle: Mapped[str] = mapped_column(String(20), nullable=False, comment="计费周期：monthly/yearly")
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, comment="价格（分）")
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False, comment="授权时长（天）")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    activation_cards: Mapped[List["ActivationCard"]] = relationship("ActivationCard", back_populates="plan")

    __table_args__ = (
        Index("idx_pricing_plans_is_active", "is_active", "sort_order"),
    )

class ActivationCard(Base):
    """卡密表"""
    __tablename__ = "activation_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    card_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="卡密")
    plan_code: Mapped[Optional[str]] = mapped_column(
        String(32),
        ForeignKey("pricing_plans.plan_code", ondelete="SET NULL"),
        nullable=True,
        comment="关联套餐编码",
    )
    duration_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="覆盖套餐时长（天）")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="卡密是否可用")
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否已使用")
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="卡密过期时间")
    used_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="使用者用户 ID",
    )
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="使用时间")
    batch_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("card_batches.batch_id", ondelete="SET NULL"),
        nullable=True,
        comment="所属批次",
    )
    creator_account_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("admin_accounts.id", ondelete="SET NULL"),
        nullable=True,
        comment="生成人账号 ID",
    )
    owner_account_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("admin_accounts.id", ondelete="SET NULL"),
        nullable=True,
        comment="归属账号 ID",
    )
    direct_parent_account_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("admin_accounts.id", ondelete="SET NULL"),
        nullable=True,
        comment="直接上级账号 ID",
    )
    root_master_account_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("admin_accounts.id", ondelete="SET NULL"),
        nullable=True,
        comment="省总代账号 ID",
    )
    settlement_unit_price_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="单张结算价")
    card_source_type: Mapped[str] = mapped_column(String(20), default="platform", nullable=False, comment="来源类型")
    copy_status: Mapped[str] = mapped_column(String(20), default="new", nullable=False, comment="复制状态")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    plan: Mapped[Optional["PricingPlan"]] = relationship("PricingPlan", back_populates="activation_cards")
    used_by_user: Mapped[Optional["User"]] = relationship("User", back_populates="activated_cards")
    batch: Mapped[Optional["CardBatch"]] = relationship("CardBatch", back_populates="cards")
    slot_usages: Mapped[List["UserAuthorizationCard"]] = relationship(
        "UserAuthorizationCard",
        back_populates="activation_card",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_activation_cards_is_used", "is_used", "is_active"),
        Index("idx_activation_cards_plan_code", "plan_code"),
        Index("idx_activation_cards_batch_id", "batch_id"),
        Index("idx_activation_cards_owner_account_id", "owner_account_id"),
    )


class UserAuthorization(Base):
    """系统用户下的当前授权记录。"""
    __tablename__ = "user_authorizations"

    authorization_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="归属系统用户 ID",
    )
    current_account_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("accounts.account_id", ondelete="SET NULL"),
        nullable=True,
        comment="当前绑定的 TG 账号 ID",
    )
    source_card_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("activation_cards.id", ondelete="SET NULL"),
        nullable=True,
        comment="首次创建该授权的卡密 ID",
    )
    grant_source: Mapped[str] = mapped_column(
        String(20),
        default="card",
        nullable=False,
        comment="授权来源：card/bot_trial",
    )
    total_duration_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="累计授权天数")
    start_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="首次生效时间")
    end_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="当前到期时间")
    status: Mapped[str] = mapped_column(
        String(20),
        default="active",
        nullable=False,
        comment="状态：active/expired/disabled",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User", back_populates="authorizations")
    current_account: Mapped[Optional["Account"]] = relationship("Account", foreign_keys=[current_account_id])
    source_card: Mapped[Optional["ActivationCard"]] = relationship("ActivationCard", foreign_keys=[source_card_id])
    card_usages: Mapped[List["UserAuthorizationCard"]] = relationship(
        "UserAuthorizationCard",
        back_populates="slot",
        cascade="all, delete-orphan",
    )
    bindings: Mapped[List["UserAuthorizationBinding"]] = relationship(
        "UserAuthorizationBinding",
        back_populates="slot",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_user_authorizations_user_status", "user_id", "status"),
        Index("idx_user_authorizations_account", "current_account_id"),
        Index("idx_user_authorizations_end_at", "end_at"),
    )


class UserAuthorizationCard(Base):
    """当前授权所消费的卡密记录。"""
    __tablename__ = "user_authorization_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    authorization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user_authorizations.authorization_id", ondelete="CASCADE"),
        nullable=False,
        comment="授权 ID",
    )
    activation_card_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("activation_cards.id", ondelete="CASCADE"),
        nullable=False,
        comment="卡密 ID",
    )
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False, comment="本次增加时长（天）")
    applied_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="应用时间")

    slot: Mapped["UserAuthorization"] = relationship("UserAuthorization", back_populates="card_usages")
    activation_card: Mapped["ActivationCard"] = relationship("ActivationCard", back_populates="slot_usages")

    __table_args__ = (
        UniqueConstraint("activation_card_id", name="uq_user_authorization_cards_activation_card_id"),
        Index("idx_user_authorization_cards_authorization_id", "authorization_id"),
    )


class UserAuthorizationBinding(Base):
    """当前授权与 TG 账号的切换历史。"""
    __tablename__ = "user_authorization_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    authorization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user_authorizations.authorization_id", ondelete="CASCADE"),
        nullable=False,
        comment="授权 ID",
    )
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.account_id", ondelete="CASCADE"),
        nullable=False,
        comment="TG 账号 ID",
    )
    bind_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="绑定时间")
    unbind_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="解绑时间")
    unbind_reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="解绑原因")

    slot: Mapped["UserAuthorization"] = relationship("UserAuthorization", back_populates="bindings")
    account: Mapped["Account"] = relationship("Account")

    __table_args__ = (
        Index("idx_user_authorization_bindings_authorization_id", "authorization_id"),
        Index("idx_user_authorization_bindings_account_id", "account_id"),
    )


class AuthorizationNoticeLog(Base):
    """授权到期提醒发送记录。"""
    __tablename__ = "authorization_notice_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    authorization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user_authorizations.authorization_id", ondelete="CASCADE"),
        nullable=False,
        comment="授权 ID",
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="系统用户 ID",
    )
    days_before: Mapped[int] = mapped_column(Integer, nullable=False, comment="距到期前天数")
    sent_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="发送时间")

    __table_args__ = (
        UniqueConstraint("authorization_id", "days_before", name="uq_authorization_notice_once"),
        Index("idx_authorization_notice_user_id", "user_id"),
        Index("idx_authorization_notice_sent_at", "sent_at"),
    )


class MediaType(str, Enum):
    """媒体类型枚举"""
    NONE = "none"
    PHOTO = "photo"
    VIDEO = "video"
    STICKER = "sticker"
    ANIMATION = "animation"


class TaskTriggerMode(str, Enum):
    """任务触发方式枚举。"""
    SCHEDULED = "scheduled"
    MANUAL_SHORTCUT = "manual_shortcut"


class TaskTriggerSource(str, Enum):
    """任务执行来源枚举。"""
    SCHEDULER = "scheduler"
    BOT_SHORTCUT = "bot_shortcut"
    API_MANUAL = "api_manual"


class HealthStatus(str, Enum):
    """账号健康状态枚举"""
    ONLINE = "online"
    OFFLINE = "offline"
    BANNED = "banned"


class PeerType(str, Enum):
    """Peer 类型枚举"""
    USER = "user"
    CHAT = "chat"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"


class ProxyType(str, Enum):
    """代理类型枚举"""
    SOCKS5 = "socks5"
    HTTP = "http"
    MTPROTO = "mtproto"


class DeveloperAppHealthStatus(str, Enum):
    """开发者应用健康状态枚举"""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    CHECKING = "checking"
    DISABLED = "disabled"


class TelegramDeveloperApp(Base):
    """Telegram 开发者应用凭证池（多 API_ID/API_HASH）"""
    __tablename__ = "telegram_developer_apps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    app_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="应用名称")
    api_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, comment="Telegram API_ID")
    api_hash_encrypted: Mapped[str] = mapped_column(Text, nullable=False, comment="加密存储的 API_HASH")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否可分配使用")
    max_accounts: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="最大账号数，0 表示不限制")
    selection_weight: Mapped[int] = mapped_column(Integer, default=100, nullable=False, comment="自动分配权重")
    health_status: Mapped[str] = mapped_column(String(20), default=DeveloperAppHealthStatus.HEALTHY.value, nullable=False, comment="健康状态")
    last_health_check_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="最近健康检查时间")
    last_health_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="最近健康检查错误")
    last_health_latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="最近健康检查耗时（毫秒）")
    health_fail_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="连续健康检查失败次数")
    credentials_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="凭证版本号")
    last_rotated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="最近凭证轮换时间")
    notes: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="备注")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    accounts: Mapped[List["Account"]] = relationship("Account", back_populates="developer_app")
    system_sessions: Mapped[List["SystemSession"]] = relationship("SystemSession", back_populates="developer_app")

    __table_args__ = (
        Index("idx_telegram_developer_apps_active", "is_active"),
        Index("idx_telegram_developer_apps_health_status", "health_status"),
    )

    def __repr__(self) -> str:
        return f"<TelegramDeveloperApp(id={self.id}, name={self.app_name}, api_id={self.api_id})>"


class ScheduledMessageTask(Base):
    """定时消息任务表"""
    __tablename__ = "scheduled_message_tasks"

    # 主键
    task_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # 基础信息
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, comment="归属系统用户 ID")
    account_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("accounts.account_id", ondelete="CASCADE"),
        nullable=True,
        comment="执行账号 ID",
    )
    chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="群组/频道 ID（兼容旧数据）")
    title: Mapped[str] = mapped_column(String(100), nullable=False, comment="显示名")

    # 目标 Peer 信息（新架构）
    target_peer_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="目标 Peer ID")
    target_peer_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="目标 Peer 类型")
    target_access_hash: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="目标 Access Hash")
    target_peers: Mapped[Optional[List[Any]]] = mapped_column(JSON, nullable=True, comment="多目标 Peer 列表")

    # 启用状态
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否启用")
    trigger_mode: Mapped[str] = mapped_column(
        String(20),
        default=TaskTriggerMode.SCHEDULED.value,
        nullable=False,
        comment="触发方式：scheduled/manual_shortcut",
    )
    shortcut_slot: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="快捷栏位置 1-3")
    shortcut_label: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="快捷按钮名称")

    # 优先级（用于紧急任务插队）
    priority: Mapped[int] = mapped_column(Integer, default=0, comment="任务优先级，越大越优先")

    # 重复设置
    repeat_interval_min: Mapped[int] = mapped_column(Integer, nullable=False, comment="重复间隔（分钟）")
    jitter_seconds: Mapped[int] = mapped_column(Integer, default=0, comment="随机抖动秒数（0-300）")
    delay_min_seconds: Mapped[int] = mapped_column(Integer, default=0, comment="随机延迟下限（秒）")
    delay_max_seconds: Mapped[int] = mapped_column(Integer, default=0, comment="随机延迟上限（秒）")

    # 每日时段限制
    day_start_hour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="每日发送起始小时")
    day_end_hour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="每日发送结束小时")

    # 日期范围
    start_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="开始时间 Unix")
    end_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="终止时间 Unix")

    # 消息内容
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="HTML 文本（≤4096）")
    media_type: Mapped[MediaType] = mapped_column(
        SQLEnum(
            MediaType,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            native_enum=False,
            validate_strings=True,
            name="media_type_enum",
        ),
        default=MediaType.NONE,
        comment="媒体类型",
    )
    media_file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="Telegram file_id")
    buttons: Mapped[Optional[List[Any]]] = mapped_column(JSON, nullable=True, comment="二维按钮数组")

    # 执行设置
    delete_previous: Mapped[bool] = mapped_column(Boolean, default=True, comment="删除上一条")
    pin_message: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否置顶")

    # 运行状态
    last_sent_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="上次发送消息 ID")
    next_run_at: Mapped[Optional[int]] = mapped_column(BigInteger, index=True, nullable=True, comment="下次执行时间")
    failure_count: Mapped[int] = mapped_column(Integer, default=0, comment="失败次数")

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    # 索引
    __table_args__ = (
        Index("idx_user_chat", "user_id", "chat_id"),
        Index("idx_account_id", "account_id"),
        Index("idx_enabled_next_run", "enabled", "next_run_at"),
        Index("idx_task_user_trigger_shortcut", "user_id", "trigger_mode", "shortcut_slot"),
    )

    def __repr__(self) -> str:
        return f"<ScheduledMessageTask(id={self.task_id}, title={self.title}, enabled={self.enabled})>"


class TaskLog(Base):
    """任务执行日志表"""
    __tablename__ = "task_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True, comment="任务 ID")
    send_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="发送时间")
    result: Mapped[str] = mapped_column(String(20), nullable=False, comment="执行结果: success/failed")
    trigger_source: Mapped[str] = mapped_column(
        String(20),
        default=TaskTriggerSource.SCHEDULER.value,
        nullable=False,
        comment="触发来源: scheduler/bot_shortcut/api_manual",
    )
    error_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="错误代码")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="错误信息")
    message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="消息 ID")

    # 索引
    __table_args__ = (
        Index("idx_task_id_send_at", "task_id", "send_at"),
        Index("idx_send_at", "send_at"),
    )

    def __repr__(self) -> str:
        return f"<TaskLog(id={self.id}, task_id={self.task_id}, result={self.result})>"


class TaskTargetSendIssue(Base):
    """单个任务目标的发送异常状态。"""
    __tablename__ = "task_target_send_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("scheduled_message_tasks.task_id", ondelete="CASCADE"),
        nullable=False,
        comment="任务 ID",
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="归属系统用户 ID",
    )
    account_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("accounts.account_id", ondelete="SET NULL"),
        nullable=True,
        comment="执行账号 ID",
    )
    peer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="目标 Peer ID")
    peer_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="目标 Peer 类型")
    peer_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="目标标题")
    current_error_type: Mapped[str] = mapped_column(String(100), nullable=False, comment="当前错误类型")
    current_error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="当前错误摘要")
    issue_category: Mapped[str] = mapped_column(String(50), nullable=False, comment="问题分类")
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, comment="状态：active/resolved")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="首次出现时间")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, comment="最近出现时间")
    last_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="最近提醒时间")
    muted_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="静默到期时间")
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="连续失败次数")
    auto_suspended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否自动暂停目标")
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="恢复时间")
    recovered_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="恢复提醒时间")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("task_id", "peer_type", "peer_id", name="uq_task_target_send_issues_target"),
        Index("idx_task_target_send_issues_status", "status", "last_seen_at"),
        Index("idx_task_target_send_issues_notify", "status", "last_notified_at", "muted_until"),
        Index("idx_task_target_send_issues_user", "user_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<TaskTargetSendIssue(id={self.id}, task_id={self.task_id}, "
            f"peer={self.peer_type}:{self.peer_id}, status={self.status})>"
        )


class Proxy(Base):
    """代理池表"""
    __tablename__ = "proxies"

    proxy_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 代理配置
    proxy_type: Mapped[str] = mapped_column(String(10), nullable=False, comment="代理类型: socks5/http/mtproto")
    host: Mapped[str] = mapped_column(String(255), nullable=False, comment="代理主机")
    port: Mapped[int] = mapped_column(Integer, nullable=False, comment="代理端口")
    display_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="代理展示名称")
    region_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="固定区域代码")
    is_system_gateway: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否系统内网代理网关")
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否允许多个账号共享")
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="代理认证用户名")
    password_encrypted: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="加密存储的密码")

    # 健康状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    is_healthy: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否健康")
    last_check_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="最后检查时间")
    response_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="响应时间（毫秒）")

    # 使用统计
    usage_count: Mapped[int] = mapped_column(Integer, default=0, comment="使用次数")
    assigned_account_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("accounts.account_id", ondelete="SET NULL"),
        nullable=True,
        comment="分配给的账号",
    )

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关系
    assigned_account: Mapped[Optional["Account"]] = relationship(
        "Account",
        foreign_keys=[assigned_account_id],
        uselist=False  # 一对一：一个代理只能分配给一个账号
    )

    # 索引和约束
    __table_args__ = (
        UniqueConstraint("proxy_type", "host", "port", name="unique_proxy"),
        Index("idx_proxies_is_active", "is_active", "is_healthy"),
        Index("idx_proxies_assigned", "assigned_account_id"),
        Index("idx_proxies_region_gateway", "region_code", "is_system_gateway"),
    )

    def __repr__(self) -> str:
        return f"<Proxy(id={self.proxy_id}, type={self.proxy_type}, host={self.host}:{self.port})>"


class Account(Base):
    """Userbot 账号管理表"""
    __tablename__ = "accounts"

    # 主键
    account_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # 用户信息
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, comment="归属系统用户 ID")
    tg_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True, comment="登录后的 Telegram UID")
    username: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="Telegram 用户名")
    first_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="名字")
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="手机号")

    # 登录凭证（加密存储）
    string_session_encrypted: Mapped[str] = mapped_column(Text, nullable=False, comment="AES-256-GCM 加密的 StringSession")
    developer_app_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("telegram_developer_apps.id", ondelete="SET NULL"),
        nullable=True,
        comment="关联开发者应用凭证 ID",
    )
    developer_app_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="账号绑定时的凭证版本号")
    bind_code: Mapped[Optional[str]] = mapped_column(String(6), unique=True, nullable=True, comment="6位绑定码")
    bind_code_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="绑定码过期时间")

    # 代理配置
    proxy_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("proxies.proxy_id"), nullable=True, comment="关联代理 ID")

    # 账号状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否被封禁")
    health_status: Mapped[str] = mapped_column(String(20), default=HealthStatus.ONLINE, comment="健康状态: online/offline/banned")

    # 风控状态
    is_flooding: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否触发 FloodWait")
    flood_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="FloodWait 解除时间")
    reauth_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否需要重新绑定")
    reauth_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, comment="需要重登的原因")
    reauth_required_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="重登要求生效时间")
    proxy_observation_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="代理重登观察期开始时间")
    proxy_observation_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="代理重登观察期结束时间")
    proxy_observation_success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="代理观察期成功发送计数")

    # 负载均衡
    weight: Mapped[int] = mapped_column(Integer, default=100, comment="权重（用于账号选择）")

    # 统计
    messages_sent: Mapped[int] = mapped_column(Integer, default=0, comment="已发送消息数")
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="最后使用时间")

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关系
    user: Mapped["User"] = relationship("User", back_populates="accounts")
    developer_app: Mapped[Optional["TelegramDeveloperApp"]] = relationship(
        "TelegramDeveloperApp",
        back_populates="accounts",
    )
    proxy: Mapped[Optional["Proxy"]] = relationship(
        "Proxy",
        foreign_keys=[proxy_id]
    )
    resources: Mapped[List["Resource"]] = relationship("Resource", back_populates="account", cascade="all, delete-orphan")
    tasks: Mapped[List["ScheduledMessageTask"]] = relationship("ScheduledMessageTask", foreign_keys=[ScheduledMessageTask.account_id])

    # 索引
    __table_args__ = (
        Index("idx_accounts_user_id", "user_id"),
        Index("idx_accounts_health_status", "health_status"),
        Index("idx_accounts_bind_code", "bind_code"),
        Index("idx_accounts_developer_app_id", "developer_app_id"),
        Index("idx_accounts_reauth_required", "reauth_required"),
        Index("idx_accounts_proxy_observation_until", "proxy_observation_until"),
    )

    def __repr__(self) -> str:
        return f"<Account(id={self.account_id}, username={self.username}, health={self.health_status})>"


class Resource(Base):
    """Dialogs 资源表"""
    __tablename__ = "resources"

    # 主键
    resource_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 归属
    account_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.account_id", ondelete="CASCADE"), nullable=False, comment="归属账号 ID")

    # Peer 信息
    peer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="群组/频道/用户 ID")
    peer_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="Peer 类型: user/chat/supergroup/channel")
    access_hash: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="构造 InputPeer 必需")

    # 元数据
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="名称")
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="@username")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="描述（频道/超级群）")

    # 分类标记
    is_muted: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否已静音")
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否已归档")
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否认证")
    is_scam: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否诈骗")

    # 成员数（群组/频道）
    participants_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="成员数")

    # 同步状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否活跃（未被删除/封禁）")
    last_sync_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="最后同步时间")

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关系
    account: Mapped["Account"] = relationship("Account", back_populates="resources")

    # 索引和约束
    __table_args__ = (
        UniqueConstraint("account_id", "peer_id", name="unique_account_peer"),
        Index("idx_resources_account_id", "account_id"),
        Index("idx_resources_peer_type", "peer_type"),
        Index("idx_resources_username", "username"),
        Index("idx_resources_is_active", "account_id", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<Resource(id={self.resource_id}, type={self.peer_type}, title={self.title})>"


class AccountBindLog(Base):
    """账号绑定日志表"""
    __tablename__ = "account_bind_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("accounts.account_id", ondelete="SET NULL"),
        nullable=True,
        comment="账号 ID",
    )
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, comment="绑定用户 ID")
    bind_code: Mapped[Optional[str]] = mapped_column(String(6), nullable=True, comment="绑定码")
    bound_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="绑定时间")
    ip_address: Mapped[Optional[str]] = mapped_column(INET, nullable=True, comment="IP 地址")

    # 索引
    __table_args__ = (
        Index("idx_bind_logs_user_id", "user_id"),
        Index("idx_bind_logs_bound_at", "bound_at"),
    )

    def __repr__(self) -> str:
        return f"<AccountBindLog(id={self.id}, user_id={self.user_id}, code={self.bind_code})>"


class SystemSession(Base):
    """系统级 Telegram 会话表（仅保存 bot/userbot 客户端会话）"""
    __tablename__ = "system_sessions"

    session_key: Mapped[str] = mapped_column(String(64), primary_key=True, comment="会话键: manager_bot/global_userbot")
    session_encrypted: Mapped[str] = mapped_column(Text, nullable=False, comment="加密后的 Telethon StringSession")
    developer_app_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("telegram_developer_apps.id", ondelete="SET NULL"),
        nullable=True,
        comment="关联开发者应用凭证 ID",
    )
    session_meta: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True, comment="附加元数据")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    developer_app: Mapped[Optional["TelegramDeveloperApp"]] = relationship(
        "TelegramDeveloperApp",
        back_populates="system_sessions",
    )

    __table_args__ = (
        Index("idx_system_sessions_updated_at", "updated_at"),
        Index("idx_system_sessions_developer_app_id", "developer_app_id"),
    )

    def __repr__(self) -> str:
        return f"<SystemSession(key={self.session_key})>"


class AdminAuditLog(Base):
    """管理员操作审计日志"""
    __tablename__ = "admin_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False, default="admin", comment="操作者标识")
    action: Mapped[str] = mapped_column(String(100), nullable=False, comment="操作动作")
    target_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="目标类型")
    target_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="目标标识")
    developer_app_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("telegram_developer_apps.id", ondelete="SET NULL"),
        nullable=True,
        comment="关联开发者应用凭证 ID",
    )
    old_value: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True, comment="变更前值（结构化）")
    new_value: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True, comment="变更后值（结构化）")
    detail: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True, comment="操作详情 JSON")
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True, comment="来源 IP")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="操作时间")

    developer_app: Mapped[Optional["TelegramDeveloperApp"]] = relationship("TelegramDeveloperApp")

    __table_args__ = (
        Index("idx_admin_audit_logs_created_at", "created_at"),
        Index("idx_admin_audit_logs_action", "action"),
        Index("idx_admin_audit_logs_developer_app_id", "developer_app_id"),
    )

    def __repr__(self) -> str:
        return f"<AdminAuditLog(id={self.id}, action={self.action}, target={self.target_type}:{self.target_id})>"


class AppSetting(Base):
    """系统配置键值表"""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True, comment="配置键")
    value: Mapped[str] = mapped_column(Text, nullable=False, comment="配置值")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    __table_args__ = (
        Index("idx_app_settings_updated_at", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<AppSetting(key={self.key})>"
