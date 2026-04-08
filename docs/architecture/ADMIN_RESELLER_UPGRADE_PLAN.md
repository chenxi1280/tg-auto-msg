# Admin 代理分销升级方案（讨论稿）

## 1. 背景

当前项目的管理员能力已经具备以下基础：

- 通过单一 `X-Admin-Token` 进入管理后台。
- 管理员可配置卡密规格、批量生成卡密、导出卡密、停用/启用卡密。
- 用户侧只负责“激活卡密”，不负责卡密生成、分销、结算。
- 购买入口当前只是 Telegram 联系方式配置，不是在线支付订单系统。

从代码现状看，当前系统更偏向“平台统一发卡”的单层后台模型，还没有以下能力：

- 省级部署与省级运营主体划分。
- 多级代理账号体系。
- 卡密归属、谁生成、给谁结算、结算状态等账务链路。
- 代理层级价格体系、授信额度、欠款与对账。

这意味着本次改动的核心不在用户业务，而在 `admin` 侧新增一层“代理分销运营后台”。

## 2. 本次目标

结合你的描述，建议把目标明确为下面 6 点：

1. 每个省独立部署一套服务，省与省之间数据隔离。
2. 每个省有且仅有一个总代。
3. 总代理及其下级代理可以逐级创建代理账号。
4. 总代理及各级代理都可以生成卡密。
5. 卡密支持筛选、导出、按批次追踪归属。
6. 下级代理生成的卡密，平台主账汇总到总代，并由直接上级负责其下级结算。

## 3. 暂不纳入 V1 的内容

为了控制范围，建议第一阶段先不做：

- 平台统一在线支付收款。
- 多省共用一套数据库的跨区域 SaaS 化。
- 用户端卡密激活流程重构。
- 自动分账到微信/支付宝/Stripe 等支付渠道。

## 4. 建议的业务模型

### 4.1 省级部署模型

你的前提已经明确为“每个省单独部署服务，且每省一个总代”，所以建议继续保持“每省一套独立服务 + 一套独立数据库”。

这样做的好处：

- 权限、账目、库存天然隔离。
- 出问题只影响单一区域。
- 不需要一开始就做复杂的多租户。
- 运维和权限判断更简单。

因此，`province` 在 V1 更适合作为“部署维度”而不是“数据库租户维度”。  
也就是说，系统里可以保留省份配置，但不建议一开始把所有省份塞进同一库里做强多租户。

### 4.2 后台角色模型

建议先定义 4 类角色：

- `super_admin`
  - 平台内部使用，保留当前最高权限。
  - 支持多个超管账号并存，不限定单人。
  - 负责省级部署初始化、总代初始化、兜底审计。
- `province_admin`
  - 某省平台运营管理员。
  - 负责该省总代理开户、价格体系配置、结算审核。
- `master_agent`
  - 省级总代理。
  - 可创建下级代理、配置对下级结算价、查看下级账单、确认下级充值/结算。
- `sub_agent`
  - 下级代理。
  - 可继续发展更下一级代理。
  - 可生成卡密、导出卡密、查看自己的结算记录。

如果你想更简单，V1 甚至可以先不单独做 `province_admin` 页面，直接保留当前 admin 作为省级运营入口，再新增 `master_agent` / `sub_agent` 的多级代理树即可。

### 4.2.1 后台账号体系补充规则

关于 admin 体系，这里建议明确 4 条：

- 不再使用单一 `X-Admin-Token` 作为长期方案，而是改为后台账号登录。
- `super_admin` 允许存在多个账号，避免只有一个超管带来的单点风险。
- 系统必须支持“初始化账号”流程，确保新省部署后能落地首个超管或省级管理员。
- 后台管理员账号需要支持与 TG 账号绑定，用于接收确认消息、审批提醒、风控告警。

建议的初始化方式：

- 方案 1：环境变量初始化
  - 首次部署时通过环境变量写入初始超管账号。
- 方案 2：初始化脚本
  - 部署后执行一次初始化命令，创建首个超管。
- 方案 3：数据库种子
  - 仅用于测试环境，不建议作为正式生产主流程。

建议正式环境采用：

- `初始化脚本 + 强制首登改密`

原因：

- 比硬编码环境变量更安全。
- 比直接写死种子账号更可控。
- 更适合每省独立部署的初始化流程。

### 4.2.2 管理员与 TG 账号关联

建议后台管理员账号与 TG 账号做一对一可解绑绑定关系。

建议字段：

- `admin_account_id`
- `tg_user_id`
- `tg_username`
- `tg_bind_status`
- `tg_bound_at`
- `tg_bound_by`

建议绑定流程：

1. 管理员先使用后台账号密码登录。
2. 在后台生成一次性 TG 绑定码。
3. 管理员去指定 Bot 发送绑定码。
4. 系统校验成功后，将后台账号与 TG 账号绑定。

这样做的好处：

- 后台身份与 TG 身份可核验。
- 不需要直接把 TG 当成登录账号。
- 后续“总代确认”“平台确认”“异常提醒”都能直接发给绑定的 TG 账号。

### 4.2.3 角色权限矩阵

下面是建议的 V1 权限矩阵。

| 能力项 | super_admin | province_admin | master_agent | sub_agent |
| --- | --- | --- | --- | --- |
| 后台账号登录 | 是 | 是 | 是 | 是 |
| 绑定 / 解绑自己的 TG 账号 | 是 | 是 | 是 | 是 |
| 创建其他 `super_admin` | 是 | 否 | 否 | 否 |
| 创建本省 `province_admin` | 是 | 否 | 否 | 否 |
| 创建本省总代 | 是 | 是 | 否 | 否 |
| 创建直接下级代理 | 否 | 否 | 是 | 是 |
| 查看本省总代主账 | 是 | 是 | 仅自己 | 否 |
| 配置总代总额度 | 是 | 否 | 否 | 否 |
| 配置总代结算模式白名单 | 是 | 是 | 否 | 否 |
| 配置直接下级受限额度 | 否 | 否 | 是 | 是 |
| 配置直接下级卡密拿货价 | 否 | 否 | 是 | 是 |
| 查看自己整条下级链路数据 | 是 | 是 | 是 | 否 |
| 查看自己及直接下级数据 | 是 | 是 | 是 | 是 |
| 生成卡密 | 可选，通常不用 | 可选，通常不用 | 是 | 是 |
| 导出 Excel | 是 | 是 | 是 | 是 |
| 批量复制卡密（5-10 个） | 是 | 是 | 是 | 是 |
| 确认总代充值/结算 | 是 | 视业务是否授权 | 否 | 否 |
| 确认直接下级充值/结算 | 否 | 否 | 是 | 是 |
| 查看全省审计日志 | 是 | 是 | 仅自己链路 | 仅自己 |
| 调整系统级参数 | 是 | 部分 | 否 | 否 |

补充口径：

- `super_admin` 是平台级兜底角色，可存在多个。
- `province_admin` 是省级运营角色，是否保留可按实现复杂度决定。
- `master_agent` 是每省唯一总代。
- `sub_agent` 可以继续发展下级，但只能管理自己的直接下级及其链路。

### 4.2.4 TG 绑定与确认流

建议把“绑定流”和“审批流”分开设计。

#### TG 绑定流

1. 管理员使用后台账号密码登录 H5。
2. 在“安全中心”点击“绑定 TG”。
3. 系统生成一次性绑定码，时效建议 5 分钟。
4. 管理员打开指定 Bot，发送绑定码。
5. Bot 校验成功后回写绑定结果。
6. H5 刷新后显示已绑定 TG 用户名和 TG 用户 ID。

#### TG 审批确认流

1. 某笔充值、授信调整、结算确认待审批。
2. 系统按责任链找到对应审批人。
3. 向审批人绑定的 TG 账号推送确认消息。
4. 审批人可在 TG 中点击“确认”或“驳回”。
5. 系统落审计日志，并同步更新 H5 状态。

责任链固定为：

- 总代相关事项：发给 `super_admin` 或被授权的 `province_admin`
- 下级代理相关事项：发给其直接上级代理
- 更下级事项：继续逐级上推，不越级发给平台

消息建议包含：

- 申请单号
- 代理名称
- 类型：充值 / 调额 / 结算 / 驳回
- 金额或额度变化
- 操作前余额 / 额度
- 操作后余额 / 额度
- 发起时间
- H5 跳转链接

### 4.3 代理关系模型

建议使用明确的父子关系，而不是模糊权限：

- 一个上级代理可创建多个下级代理。
- 一个下级代理只能归属于一个直接上级代理。
- 系统底层按代理树设计，业务上支持多级代理。
- 平台侧只直接管理总代；总代负责管理自己的整条下级链路。
- 总代理可以给自己的下级配置“受限额度”。
- 下级代理可用额度来自其直接上级分配，而不是平台直接发放。

这样账务链路最清楚：

- 任意下级代理生成卡密。
- 这批卡密的直接应收对象是该代理的直接上级。
- 平台主账只汇总到总代，不直接向所有下级逐个收款。

### 4.3.1 双层额度模型

这里建议把额度拆成两层，避免账务混乱。

第一层：平台对总代额度

- 平台给总代设置 `platform_credit_limit_cents`。
- 总代向平台拿卡、或其下级代理消耗平台库存时，实际占用的是总代对平台的额度。

第二层：总代对下级额度

- 总代给每个下级代理设置 `delegated_credit_limit_cents`。
- 下级代理是否能继续生成卡密，先看自己被分配的受限额度是否足够。
- 但下级代理一旦成功生成，平台侧最终扣减的仍然是总代总额度。

约束关系建议固定为：

- `所有下级已分配额度之和 <= 总代可分配总额度`
- `下级实际消耗额度 <= 该下级已获分配额度`
- `总代整条链路实际消耗 <= 总代对平台的总额度`

这样就能实现：

- 平台只跟总代算总账。
- 总代可以把自己的总额度再拆分给下面代理。
- 下级不能绕过总代直接向平台透支。

### 4.3.2 额度配置责任边界

这部分建议明确写死，避免后面权限混乱。

- 总代总额度
  - 只能由 `super_admin` 配置。
  - `province_admin` 可以查看，但默认不直接修改。
- 下级受限额度
  - 默认由“直接上级代理”配置。
  - 如果该下级属于总代直辖，则由总代配置。
  - 为兼容特殊运营场景，可允许总代覆盖调整自己整条链路内下级的受限额度。

约束规则：

- 直接上级给下级分配额度时，不得超过自己剩余可分配额度。
- 总代给整条链路分配出去的额度总和，不得超过超管给总代配置的总额度。
- 任意代理只能调整自己有管理权节点的额度，不能跨链路改别人的额度。

## 5. 卡密归属与结算口径

这是这次最关键的决策点。

你提的问题本质上有三种口径：

### 方案 A：支付后才能生成卡密

流程：

- 代理先付款。
- 系统确认付款。
- 系统允许生成卡密。

优点：

- 风险最低。
- 不容易形成坏账。
- 上级账目简单。

缺点：

- 如果系统要自动确认付款，通常就要接支付。
- 平台要处理收款、回调、补单、退款等问题。
- 对代理业务来说不够灵活。

结论：

- 如果坚持“系统自动判断已支付再放卡”，后续大概率会逼着平台接支付。

### 方案 B：先生成卡密，后续再收费

流程：

- 代理直接生成卡密。
- 系统记录这批卡密的应收金额。
- 后续线下付款或人工确认结算。

优点：

- 不需要平台马上对接支付。
- 更符合很多代理业务的实际操作。
- 发卡效率高。

缺点：

- 会形成应收款和坏账风险。
- 如果代理信用差，可能先拿卡后不结算。
- 必须补齐台账、额度、风控、逾期控制。

结论：

- 可以做，但不能是“完全不控风险的先发后收”。

### 方案 C：混合模式

流程：

- 每个代理有自己的结算模式。
- 有的走预付余额。
- 有的走授信额度。
- 生成卡密时自动记账。

优点：

- 不需要平台接支付。
- 老代理可以先拿卡后结算。
- 新代理可以强制预付。
- 后续也方便平滑接入支付。

缺点：

- 后台逻辑比纯预付稍复杂。

结论：

- 这是最适合当前项目的方向。

## 6. 推荐结论

建议 V1 采用：

**“不接平台支付，支持先生成卡密，但必须带结算台账和授信控制”的混合方案。**

更具体一点：

- 默认结算口径：`生成即记账`。
- 默认收款方式：`线下收款 + 分级人工确认`。
- 默认资金模型：`余额 + 授信额度` 二选一或混用。

原因如下：

1. 当前系统本来就没有支付订单系统，强行做“支付后生成”会把范围迅速做大。
2. 代理业务里，卡密一旦生成并被代理看见，本质上就已经形成库存占用和应收。
3. 如果等“卡密被最终用户激活”才结算，会导致账期过长，对账困难，也容易出现卡已经流出但一直不结算的问题。
4. 你提到“平台还需要对接支付收款”，这正说明 V1 更适合走线下收款 + 系统记账，而不是支付网关。
5. 多级代理体系下，平台若逐个确认所有下级，会让平台运营负担过重，因此平台只确认总代更合理。

## 7. 为什么不建议按“激活后再结算”

表面上看，“卡密激活后再结算”很公平，但不建议作为主结算口径。

主要问题：

- 卡密可能已经导出、发出、转卖，但长期未激活。
- 上级无法准确知道子代理已拿走多少真实库存。
- 应收会被拖到很后面，结算口径不稳定。
- 卡密如果丢失、泄露、赠送，也很难核账。

因此建议：

- `激活时间` 只作为经营分析口径。
- `生成批次` 才是主结算口径。

如果后面确实有需要，可以再追加一个辅助分析报表：

- 已生成未激活
- 已生成已激活
- 已结算未激活
- 已逾期未结算

## 8. 推荐的 V1 业务规则

### 8.1 代理结算模式

每个代理配置一个结算模式：

- `prepaid`
  - 先充值余额。
  - 生成卡密时直接扣减余额。
- `credit`
  - 可先生成卡密。
  - 生成后记入应收。
  - 受授信额度限制。
- `hybrid`
  - 先扣余额，不足部分计入应收。

建议默认：

- 新代理默认 `prepaid`。
- 白名单代理可切 `credit` 或 `hybrid`。
- 白名单资格由其直接上级或平台按权限决定。

### 8.2 计费时点

建议用下面规则：

- 代理在后台点击生成卡密并成功落库后，立即生成一笔结算记录。
- 如果一批卡密允许导出，那么该批卡密的应收即已成立。
- 这批卡密后续是否被最终用户激活，不影响上级对下级的应收成立。
- 下级代理生成卡密时，平台侧扣减的是对应总代的余额或授信额度。
- 下级代理对平台的责任，先归集到总代，再由总代向其下级分摊和收款。
- 下级代理本地校验的是自己的受限额度，平台主账校验的是对应总代总额度。

### 8.3 价格快照

生成卡密时必须固化价格快照，避免后改价影响旧账：

- 卡密规格编码
- 卡密天数
- 子代理拿货单价
- 批次数量
- 批次总金额
- 上级代理 ID
- 下级代理 ID
- 生成时间

### 8.4 结算动作

建议支持两种人工动作：

- `确认收款`
  - 线下已付款，后台登记一笔收款。
- `余额充值`
  - 给子代理充值预存款，后续生成时自动扣减。

多级确认链建议固定为：

- 平台 TG 管理员只确认总代的充值、授信、结算。
- 总代理确认自己下级代理的充值、授信、结算。
- 更下级代理由其直接上级继续逐级确认。

这样即使没有支付接口，也能完整闭环。

## 9. 推荐的数据模型

V1 建议新增以下实体。

### 9.1 代理账号表

建议新增独立后台账号表，不要复用普通 `users`。

原因：

- 普通 `users` 是业务用户，负责 TG 账号与任务。
- 代理账号是后台运营身份，权限模型完全不同。
- 分开后，对现有用户业务影响最小。

建议字段：

- `id`
- `username`
- `password_hash`
- `role`
- `parent_agent_id`
- `root_master_agent_id`
- `level_depth`
- `status`
- `settlement_mode`
- `credit_limit_cents`
- `balance_cents`
- `allocated_credit_limit_cents`
- `credit_used_cents`
- `tg_user_id`
- `tg_username`
- `tg_bind_status`
- `tg_bound_at`
- `display_name`
- `contact`
- `created_by`
- `created_at`
- `updated_at`

字段口径建议：

- `credit_limit_cents`
  - 平台或直接上级授予该账号的总信用额度。
- `allocated_credit_limit_cents`
  - 该账号已经分配给自己下级的额度总和。
- `credit_used_cents`
  - 该账号当前已实际占用的额度。

### 9.2 代理价格表

用于维护直接上级给直接下级的结算价格。

建议字段：

- `id`
- `parent_agent_id`
- `child_agent_id`
- `plan_code`
- `settlement_price_cents`
- `is_active`
- `created_at`
- `updated_at`

如果后面价格和额度都希望按父子关系管理，也可以考虑新增代理额度配置表：

### 9.2.1 代理额度配置表

用于记录直接上级给直接下级分配的受限额度。

建议字段：

- `id`
- `parent_agent_id`
- `child_agent_id`
- `delegated_credit_limit_cents`
- `delegated_credit_used_cents`
- `is_active`
- `created_at`
- `updated_at`

### 9.3 卡密批次表

V1 最重要的新增表之一。

建议不要只在单张卡密上做结算，而是引入“批次”：

- 便于导出
- 便于对账
- 便于一批一批结算

建议字段：

- `batch_id`
- `creator_agent_id`
- `owner_agent_id`
- `direct_parent_agent_id`
- `root_master_agent_id`
- `plan_code`
- `quantity`
- `duration_days`
- `unit_price_cents`
- `total_amount_cents`
- `settlement_status`
- `payment_status`
- `exported_at`
- `remark`
- `created_at`

### 9.4 卡密表扩展

现有 `activation_cards` 建议增加：

- `batch_id`
- `creator_agent_id`
- `owner_agent_id`
- `direct_parent_agent_id`
- `root_master_agent_id`
- `settlement_unit_price_cents`
- `settlement_status`

这样即使脱离批次单独查询卡密，也能追踪归属。

### 9.5 代理资金流水表

记录余额、授信、收款、冲销。

建议字段：

- `id`
- `agent_id`
- `type`
- `direction`
- `amount_cents`
- `balance_after_cents`
- `related_batch_id`
- `related_settlement_id`
- `remark`
- `operator_id`
- `created_at`

这里建议区分两类账：

- 平台账
  - 只记录平台与总代之间的余额、授信、应收。
- 渠道账
  - 记录总代与其下级之间的余额、授信、应收。

这样能清晰体现“下级生成卡密，平台扣总代额度，下级向总代结算”的规则。

同时建议每次额度变更都记录流水：

- 平台给总代调额
- 总代给下级分配额度
- 回收下级额度
- 扣减实际额度占用
- 释放额度占用

### 9.6 结算单表

如果后续对账会比较正式，建议单独有结算单。

建议字段：

- `settlement_id`
- `parent_agent_id`
- `child_agent_id`
- `period_start`
- `period_end`
- `amount_cents`
- `paid_amount_cents`
- `status`
- `confirmed_at`
- `confirmed_by`
- `remark`
- `created_at`

V1 如果想先轻一点，也可以先不做完整结算单，只做“批次应收 + 资金流水”。

## 10. 推荐的结算责任链

这是本次拍板后的核心规则。

### 10.1 平台与总代

- 平台只管理总代。
- 平台 TG 管理员只确认总代的充值、授信、收款、结算。
- 平台只扣总代的余额和授信额度。
- 平台可以给总代调总额度，但不直接给总代下级发额度。

### 10.2 总代与下级

- 总代理负责管理自己整条下级代理链路。
- 总代理可以为自己的直接下级配置受限额度。
- 下级代理生成卡密时，平台侧先扣总代额度。
- 下级代理的收款默认流向总代，由总代自行确认和管理。
- 如果存在更下一级代理，则继续由其直接上级逐级负责。

### 10.3 平台主账与渠道分账

- 平台主账只看总代欠款、总代余额、总代授信占用。
- 总代内部如何向各级代理收款，是总代责任域。
- 系统应保留整条代理链，用于审计和报表，但平台主账只汇总到总代。

## 11. 推荐的后台操作流程

### 11.1 省级初始化

- 平台内部创建省级部署。
- 初始化一个省级运营入口。
- 创建首个超管或省级管理员初始化账号。
- 完成初始化账号首登改密。
- 绑定初始化管理员的 TG 账号。
- 为该省创建唯一总代账号。

### 11.2 总代理开下级代理

- 总代理创建下级代理账号。
- 为下级代理设置结算模式。
- 为下级代理设置授信额度或初始余额。
- 为下级代理配置每种卡密规格的拿货价。
- 为下级代理配置受限额度。
- 如果需要继续多级分销，则由下级代理继续创建自己的下级。

### 11.3 下级代理生成卡密

- 下级代理选择规格、数量、前缀。
- 系统按直接父子价格关系计算本次应收。
- 系统先校验该下级代理自己的受限额度。
- 系统再校验对应总代总额度是否足够。
- 系统创建卡密批次。
- 系统生成卡密明细。
- 系统自动写入资金流水 / 应收记录。
- 平台账扣减对应总代余额或授信。
- 渠道账挂到该下级代理与其直接上级之间。

### 11.4 代理导出卡密

- 支持按批次导出。
- 支持导出 XLSX / CSV。
- 导出时保留批次号，方便核账。
- 支持在 H5 列表页勾选后批量复制卡密。
- 单次复制建议限制为 5 到 10 个卡密，避免误操作一次性复制过多。
- 复制结果建议支持两种格式：
  - 纯卡密换行
  - `卡密 + 规格 + 批次号` 的带注释格式

### 11.5 分级结算

- 平台查看总代未结算批次与额度占用。
- 总代理查看自己下级代理的未结算批次。
- 按批次或按时间段汇总应收。
- 线下收款后由责任上级点击确认。
- 系统把批次或结算单状态改为已结算。

## 12. 对现有系统的影响评估

### 12.1 对用户侧业务影响

影响应尽量很小。

保持不变的部分：

- 用户激活卡密流程。
- 用户授权与续费逻辑。
- Bot 与任务系统。

需要调整但不影响用户感知的部分：

- 卡密生成来源从“平台 admin”扩展为“代理后台”。
- 卡密表增加归属与结算字段。

### 12.2 对 admin 侧影响

主要变化集中在 admin：

- 单一 `X-Admin-Token` 模式将不够用。
- 需要改为后台账号、角色、权限（RBAC）体系。
- 需要支持多个超管账号并存。
- 需要支持初始化管理员账号流程。
- 需要支持后台管理员与 TG 账号绑定。
- 需要从“一个后台”升级为“角色化后台”。
- 卡密管理页要新增代理维度、批次维度、结算维度。
- H5 页面需要兼容不同角色进入后的能力裁剪。
- H5 页面需要补“导出 Excel”“批量复制 5-10 个卡密”“额度管理”“TG 绑定状态”。
- 审计日志需要记录“哪个代理做了什么”。
- 需要支持 TG 管理确认流，且确认责任按层级划分。

### 12.2.1 H5 页面能力建议

建议 H5 继续作为统一后台承载，不额外拆原生后台。

V1 建议至少包含这些页面或模块：

- 登录页
  - 支持后台账号密码登录
  - 支持首次登录改密提醒
- 安全中心
  - 查看 TG 绑定状态
  - 发起 TG 绑定 / 解绑
- 代理管理页
  - 创建直接下级
  - 查看下级列表
  - 配置下级结算模式
  - 配置下级受限额度
  - 配置下级拿货价
- 额度管理页
  - 超管配置总代总额度
  - 上级代理配置下级受限额度
  - 查看额度占用与剩余额度
- 卡密批次页
  - 生成卡密
  - 按批次查看
  - 导出 Excel
  - 勾选复制 5-10 个卡密
- 结算确认页
  - 查看待确认记录
  - 确认 / 驳回
  - 展示 TG 审批状态
- 审计日志页
  - 查看关键操作记录

界面兼容建议：

- 仍沿用现有 H5 后台技术栈，不需要另起一套前端。
- 页面能力按角色动态裁剪，而不是为每个角色做独立前端。
- 列表操作优先保留现有“导出 XLSX”能力，再补充“批量复制卡密”。

### 12.3 对数据库影响

这是本次改动的主要工作量来源。

需要新增：

- 代理账号体系
- 代理价格体系
- 卡密批次
- 资金流水 / 结算台账

现有表里最关键的改动会在：

- `activation_cards`
- `admin_audit_logs`
- 后续可能新增 agent 相关表

## 13. 权限与风控建议

V1 至少要做这些限制：

- 任意代理只能看到自己及自己下级的数据。
- 总代理能看到自己整条下级链路的数据。
- 下级代理超出允许额度后禁止继续生成。
- 总代理给下级分配的受限额度总和不能超过自己可分配额度。
- 下级代理不能修改自己的受限额度，只能由直接上级调整。
- 已导出的批次不能随意删除。
- 卡密价格按生成时快照结算，不受后续调价影响。
- 审计日志必须记录生成人、归属人、上级、IP、时间。
- 平台侧若总代额度不足，则总代及其整条下级链路都应禁止继续向平台拿卡。

## 14. 建议的实施顺序

为了降低风险，建议按下面顺序推进。

### 阶段 1：只打地基

- 明确角色模型。
- 补齐数据库表结构。
- 先保留现有 root admin 能力。
- 不改用户侧逻辑。

### 阶段 2：代理账号与结算后台

- 新增总代 / 多级代理登录与权限。
- 新增卡密批次、导出、应收、余额页面。
- 新增人工收款 / 充值入口。
- 新增 TG 管理确认链。

### 阶段 3：报表与风控

- 逾期未结算报表。
- 代理树额度控制。
- 批次统计与激活转化分析。

### 阶段 4：再决定是否接支付

如果后面业务量足够大，再考虑：

- 充值自动到账
- 订单回调
- 自动放卡

这样不会在第一阶段把系统复杂度拉得太高。

## 15. 本次讨论已确认的关键规则

目前按你的最新意见，建议将以下规则视为已确认：

1. 每个省独立部署服务和数据库。
2. 业务支持多级代理。
3. 默认预付，白名单代理可授信。
4. 平台 TG 管理员只确认总代。
5. 总代理确认自己下级代理，更下级继续逐级确认。
6. 下级代理生成卡密时，平台侧扣的是总代额度。
7. 下级代理的收款先到总代，由总代负责其下级账务。
8. 当前 admin 体系需要升级为账号、角色、权限体系。
9. `super_admin` 允许存在多个账号。
10. 系统需要支持初始化管理员账号。
11. 后台管理员账号需要与 TG 账号绑定。
12. 总代理可以为下级代理配置受限额度。
13. 下级代理生成卡密时，同时受“自身受限额度”和“总代总额度”双重约束。

## 16. 我的建议结论

如果目标是“先尽快上线代理体系，不把项目拖进支付系统”，我建议最终拍板为：

- 每省一套独立服务，不做跨省混库。
- 保留当前 root admin 作为省级最高后台。
- 新增支持多级的代理账号树。
- 支持多个超管账号与初始化账号流程。
- 支持后台管理员与 TG 账号绑定。
- 卡密结算按“生成批次”记账，不按最终激活记账。
- 不接支付网关，先走线下收款 + 分级确认。
- 新代理默认预付，白名单代理可开授信额度。
- 平台只管理总代主账；总代负责下级分账与确认。
- 总代可向下级分配受限额度，但平台最终只扣总代总额度。

这条路线对现有用户业务影响最小，也最符合你现在的担心点。

## 17. 与当前代码现状的对应关系

下面这些现状是本方案的重要依据：

- 当前后台鉴权是单一 `X-Admin-Token`，不适合代理分层与多级确认。
- 当前 `activation_cards` 只有“是否使用、使用者、过期时间”等字段，没有代理归属与账务字段。
- 当前 admin 已支持卡密批量生成和 XLSX 导出，说明“发卡能力”已有基础，可在此之上扩展。
- 当前购买入口只是外部联系方式配置，不是支付系统，因此 V1 完全可以不接支付。

---

这份文档是讨论稿。  
建议下一步不要马上改代码，而是按第 15 节已确认规则继续细化；规则确认后再拆数据库迁移、后端接口、前端页面和权限改造。

## 18. 数据库表结构草案

这一节不是最终 DDL，而是开发前的结构草案。

### 18.1 后台账号表 `admin_accounts`

用途：

- 承载超管、省级管理员、总代、下级代理的后台登录账号。

建议字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | bigint pk | 主键 |
| `username` | varchar(64) unique | 登录名 |
| `password_hash` | varchar(255) | 密码哈希 |
| `role_code` | varchar(32) | `super_admin` / `province_admin` / `master_agent` / `sub_agent` |
| `province_code` | varchar(32) | 省份编码 |
| `parent_account_id` | bigint null | 直接上级账号 ID |
| `root_master_account_id` | bigint null | 省总代账号 ID |
| `level_depth` | int | 层级深度，总代为 0 |
| `status` | varchar(20) | active / disabled / locked |
| `settlement_mode` | varchar(20) | prepaid / credit / hybrid |
| `is_credit_whitelisted` | bool | 是否授信白名单 |
| `credit_limit_cents` | bigint | 本账号总额度 |
| `allocated_credit_limit_cents` | bigint | 已分配给下级的额度总和 |
| `credit_used_cents` | bigint | 已占用额度 |
| `balance_cents` | bigint | 余额 |
| `display_name` | varchar(100) | 展示名称 |
| `contact_name` | varchar(100) null | 联系人 |
| `contact_phone` | varchar(50) null | 联系方式 |
| `created_by` | bigint null | 创建人账号 ID |
| `last_login_at` | timestamp null | 最近登录时间 |
| `created_at` | timestamp | 创建时间 |
| `updated_at` | timestamp | 更新时间 |

建议索引：

- `idx_admin_accounts_role_status`
- `idx_admin_accounts_parent`
- `idx_admin_accounts_root_master`
- `idx_admin_accounts_province_role`

### 18.2 后台账号 TG 绑定表 `admin_account_tg_bindings`

用途：

- 保存后台账号与 TG 账号的绑定关系。

建议字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | bigint pk | 主键 |
| `admin_account_id` | bigint unique | 后台账号 ID |
| `tg_user_id` | bigint unique | TG 用户 ID |
| `tg_username` | varchar(100) null | TG 用户名 |
| `bind_status` | varchar(20) | pending / bound / unbound / expired |
| `bind_code` | varchar(32) null | 一次性绑定码 |
| `bind_code_expires_at` | timestamp null | 绑定码过期时间 |
| `bound_at` | timestamp null | 绑定完成时间 |
| `unbound_at` | timestamp null | 解绑时间 |
| `bound_by_account_id` | bigint null | 谁发起绑定 |
| `created_at` | timestamp | 创建时间 |
| `updated_at` | timestamp | 更新时间 |

建议索引：

- `idx_admin_tg_bindings_account`
- `idx_admin_tg_bindings_tg_user`
- `idx_admin_tg_bindings_status`

### 18.3 代理额度配置表 `agent_credit_limits`

用途：

- 保存“直接上级给直接下级分配的受限额度”。

建议字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | bigint pk | 主键 |
| `parent_account_id` | bigint | 直接上级账号 ID |
| `child_account_id` | bigint | 直接下级账号 ID |
| `delegated_credit_limit_cents` | bigint | 分配额度 |
| `delegated_credit_used_cents` | bigint | 已使用额度 |
| `is_active` | bool | 是否有效 |
| `last_adjusted_by` | bigint | 最近调整人 |
| `created_at` | timestamp | 创建时间 |
| `updated_at` | timestamp | 更新时间 |

唯一约束建议：

- `uq_agent_credit_limits_parent_child`

### 18.4 代理价格表 `agent_plan_prices`

用途：

- 保存直接上级给直接下级的卡密结算价。

建议字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | bigint pk | 主键 |
| `parent_account_id` | bigint | 直接上级账号 ID |
| `child_account_id` | bigint | 直接下级账号 ID |
| `plan_code` | varchar(32) | 卡密规格 |
| `settlement_price_cents` | bigint | 结算价 |
| `is_active` | bool | 是否有效 |
| `created_at` | timestamp | 创建时间 |
| `updated_at` | timestamp | 更新时间 |

唯一约束建议：

- `uq_agent_plan_prices_parent_child_plan`

### 18.5 卡密批次表 `card_batches`

用途：

- 承载一次卡密生成行为的业务主单据。

建议字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `batch_id` | varchar(36) pk | 批次号 |
| `province_code` | varchar(32) | 省份编码 |
| `creator_account_id` | bigint | 实际点击生成人 |
| `owner_account_id` | bigint | 批次归属账号 |
| `direct_parent_account_id` | bigint | 直接上级账号 |
| `root_master_account_id` | bigint | 省总代账号 |
| `plan_code` | varchar(32) | 卡密规格 |
| `quantity` | int | 数量 |
| `duration_days` | int | 时长 |
| `unit_price_cents` | bigint | 单价快照 |
| `total_amount_cents` | bigint | 总金额 |
| `settlement_status` | varchar(20) | pending / partial / settled / cancelled |
| `payment_status` | varchar(20) | unpaid / paid / rejected |
| `export_count` | int | 已导出次数 |
| `last_exported_at` | timestamp null | 最近导出时间 |
| `remark` | text null | 备注 |
| `created_at` | timestamp | 创建时间 |
| `updated_at` | timestamp | 更新时间 |

建议索引：

- `idx_card_batches_owner`
- `idx_card_batches_parent`
- `idx_card_batches_root_master`
- `idx_card_batches_status`
- `idx_card_batches_created_at`

### 18.6 卡密表扩展 `activation_cards`

建议在现有表上增加：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `batch_id` | varchar(36) null | 所属批次 |
| `creator_account_id` | bigint null | 生成人 |
| `owner_account_id` | bigint null | 当前归属账号 |
| `direct_parent_account_id` | bigint null | 直接上级账号 |
| `root_master_account_id` | bigint null | 省总代账号 |
| `settlement_unit_price_cents` | bigint null | 单张结算价快照 |
| `card_source_type` | varchar(20) | platform / agent |
| `copy_status` | varchar(20) | new / copied / exported |

### 18.7 资金流水表 `agent_fund_ledgers`

用途：

- 统一记录余额、授信、充值、冲销、结算确认。

建议字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | bigint pk | 主键 |
| `ledger_scope` | varchar(20) | platform / channel |
| `account_id` | bigint | 当前记账主体 |
| `counterparty_account_id` | bigint null | 对手方账号 |
| `biz_type` | varchar(32) | recharge / allocate_credit / consume_credit / settlement / rollback |
| `direction` | varchar(16) | in / out |
| `amount_cents` | bigint | 金额 |
| `balance_after_cents` | bigint null | 余额变更后 |
| `credit_used_after_cents` | bigint null | 额度占用变更后 |
| `related_batch_id` | varchar(36) null | 关联批次 |
| `related_request_id` | varchar(36) null | 关联审批单 |
| `remark` | text null | 备注 |
| `operator_account_id` | bigint null | 操作人 |
| `created_at` | timestamp | 创建时间 |

### 18.8 审批请求表 `approval_requests`

用途：

- 保存所有需要 TG 或 H5 确认的请求。

建议字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `request_id` | varchar(36) pk | 请求号 |
| `province_code` | varchar(32) | 省份编码 |
| `request_type` | varchar(32) | recharge / settlement / credit_adjust |
| `requester_account_id` | bigint | 发起人 |
| `subject_account_id` | bigint | 业务主体 |
| `approver_account_id` | bigint | 审批人 |
| `status` | varchar(20) | pending / approved / rejected / expired |
| `amount_cents` | bigint null | 金额 |
| `credit_delta_cents` | bigint null | 额度变化 |
| `payload_json` | jsonb | 扩展字段 |
| `approved_at` | timestamp null | 审批时间 |
| `rejected_at` | timestamp null | 驳回时间 |
| `created_at` | timestamp | 创建时间 |
| `updated_at` | timestamp | 更新时间 |

## 19. 后端接口清单草案

### 19.1 认证与账号

- `POST /api/admin-auth/login`
- `POST /api/admin-auth/logout`
- `GET /api/admin-auth/me`
- `POST /api/admin-auth/change-password`
- `POST /api/admin-auth/tg-bind-code`
- `POST /api/admin-auth/tg-unbind`

### 19.2 超管与省级管理员

- `POST /api/admin/provinces/{province_code}/master-agent`
  - 创建本省总代
- `PUT /api/admin/accounts/{account_id}/credit-limit`
  - 配置总代总额度
- `PUT /api/admin/accounts/{account_id}/credit-whitelist`
  - 设置授信白名单
- `GET /api/admin/provinces/{province_code}/overview`
  - 查看本省总览
- `GET /api/admin/provinces/{province_code}/audit-logs`
  - 查看本省审计日志

### 19.3 代理树管理

- `POST /api/agent/accounts`
  - 创建直接下级
- `GET /api/agent/accounts`
  - 查看自己可见范围内代理列表
- `GET /api/agent/accounts/{account_id}`
  - 查看代理详情
- `PUT /api/agent/accounts/{account_id}/settlement-mode`
  - 设置下级结算模式
- `PUT /api/agent/accounts/{account_id}/credit-limit`
  - 配置下级受限额度
- `PUT /api/agent/accounts/{account_id}/plan-prices/{plan_code}`
  - 配置下级拿货价

### 19.4 卡密与批次

- `POST /api/agent/card-batches/generate`
  - 生成卡密批次
- `GET /api/agent/card-batches`
  - 批次列表
- `GET /api/agent/card-batches/{batch_id}`
  - 批次详情
- `GET /api/agent/cards`
  - 卡密列表
- `GET /api/agent/cards/export`
  - 导出 Excel / CSV
- `POST /api/agent/cards/copy`
  - 批量复制卡密，建议限制 5-10 个

### 19.5 审批与结算

- `POST /api/agent/approval-requests/recharge`
  - 发起充值确认
- `POST /api/agent/approval-requests/settlement`
  - 发起结算确认
- `POST /api/agent/approval-requests/credit-adjust`
  - 发起调额确认
- `GET /api/agent/approval-requests/pending`
  - 待审批列表
- `POST /api/agent/approval-requests/{request_id}/approve`
  - H5 审批通过
- `POST /api/agent/approval-requests/{request_id}/reject`
  - H5 审批驳回

### 19.6 TG Bot 回调

- `POST /api/internal/tg-admin/bind-callback`
  - TG 绑定回写
- `POST /api/internal/tg-admin/approve-callback`
  - TG 审批通过
- `POST /api/internal/tg-admin/reject-callback`
  - TG 审批驳回

## 20. H5 页面与按钮权限草案

### 20.1 页面清单

| 页面 | super_admin | province_admin | master_agent | sub_agent |
| --- | --- | --- | --- | --- |
| 登录页 | 是 | 是 | 是 | 是 |
| 安全中心 | 是 | 是 | 是 | 是 |
| 省级总览 | 是 | 是 | 否 | 否 |
| 总代管理页 | 是 | 是 | 否 | 否 |
| 代理管理页 | 只读或部分 | 只读或部分 | 是 | 是 |
| 额度管理页 | 是 | 只读 | 是 | 是 |
| 价格管理页 | 否 | 否 | 是 | 是 |
| 卡密批次页 | 是 | 是 | 是 | 是 |
| 卡密明细页 | 是 | 是 | 是 | 是 |
| 审批中心 | 是 | 是 | 是 | 是 |
| 审计日志页 | 是 | 是 | 仅链路内 | 仅自己 |

### 20.2 关键按钮权限

| 按钮 / 操作 | super_admin | province_admin | master_agent | sub_agent |
| --- | --- | --- | --- | --- |
| 创建总代 | 是 | 是 | 否 | 否 |
| 创建直接下级 | 否 | 否 | 是 | 是 |
| 设置总代总额度 | 是 | 否 | 否 | 否 |
| 设置下级受限额度 | 否 | 否 | 是 | 是 |
| 设置下级拿货价 | 否 | 否 | 是 | 是 |
| 生成卡密 | 可选 | 可选 | 是 | 是 |
| 导出 Excel | 是 | 是 | 是 | 是 |
| 复制 5-10 个卡密 | 是 | 是 | 是 | 是 |
| 审批通过 / 驳回 | 是 | 是 | 是 | 是 |

### 20.3 卡密列表交互建议

- 支持单个卡密复制。
- 支持勾选 5-10 个卡密后批量复制。
- 超过 10 个时，前端提示改用“导出 Excel”。
- 支持“复制纯卡密”与“复制卡密+备注”两种模式。
- 对已使用卡密、已停用卡密给出明显状态标识。
- 支持按批次、规格、归属代理、使用状态筛选。

## 21. TG Bot 消息模板草案

### 21.1 TG 绑定成功

建议内容：

```text
绑定成功
后台账号：{display_name}
角色：{role_name}
省份：{province_name}
绑定 TG：@{tg_username} ({tg_user_id})
时间：{bound_at}
```

### 21.2 充值待确认

建议内容：

```text
充值待确认
申请单号：{request_id}
代理：{account_name}
上级：{parent_name}
金额：{amount_yuan}
当前余额：{balance_before_yuan}
申请时间：{created_at}
请在 TG 或 H5 中确认
```

按钮建议：

- `确认充值`
- `驳回申请`
- `打开H5`

### 21.3 调额待确认

建议内容：

```text
额度调整待确认
申请单号：{request_id}
代理：{account_name}
当前额度：{credit_before_yuan}
调整额度：{credit_delta_yuan}
调整后额度：{credit_after_yuan}
申请时间：{created_at}
```

### 21.4 结算待确认

建议内容：

```text
结算待确认
申请单号：{request_id}
代理：{account_name}
批次数：{batch_count}
结算金额：{amount_yuan}
周期：{period_text}
申请时间：{created_at}
```

### 21.5 审批结果通知

建议内容：

```text
审批结果：{approved_or_rejected}
申请单号：{request_id}
代理：{account_name}
类型：{request_type}
金额/额度：{amount_text}
处理人：{approver_name}
处理时间：{approved_at}
```

## 22. 卡密生成与额度扣减事务时序

这一节是实现时最关键的事务边界。

### 22.1 前置校验

生成卡密前先检查：

1. 当前登录账号是否有生成权限。
2. 当前账号是否处于启用状态。
3. 当前账号是否绑定 TG。
4. 当前账号是否已配置对应规格的拿货价。
5. 当前账号的直接上级关系是否存在。
6. 当前账号自身受限额度是否足够。
7. 对应总代总额度是否足够。
8. 本次生成数量是否超过单次限制。

### 22.2 建议事务顺序

在一个数据库事务内完成：

1. 锁定当前账号行。
2. 锁定直接上级额度配置行。
3. 锁定总代账号行。
4. 再次校验自身受限额度与总代总额度。
5. 创建 `card_batches` 批次记录。
6. 批量写入 `activation_cards`。
7. 更新下级代理已使用受限额度。
8. 更新总代已使用总额度或余额占用。
9. 写入平台账流水。
10. 写入渠道账流水。
11. 写入审计日志。
12. 提交事务。

### 22.3 提交后动作

事务提交后再做：

1. 生成导出文件。
2. 触发 TG 通知。
3. 刷新 H5 列表缓存。
4. 返回前端复制内容或下载地址。

### 22.4 失败回滚原则

- 只要卡密明细、额度扣减、流水记录任一失败，整个事务必须回滚。
- 不允许出现“卡密生成成功但额度没扣”。
- 不允许出现“额度已扣但批次没生成”。
- TG 推送失败不影响事务提交，但要记录重试任务。

### 22.5 并发控制建议

- 对账号额度扣减使用行级锁。
- 对“直接上级 -> 下级”的额度配置使用行级锁。
- 对总代总额度使用行级锁。
- 卡密编码继续保留唯一约束，冲突时重试生成。
- 批量复制不是事务关键路径，不参与额度锁。
