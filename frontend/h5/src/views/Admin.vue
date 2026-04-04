<template>
  <div class="admin-page">
    <header class="header">
      <div class="container">
        <div class="brand-header">
          <img class="brand-logo" src="/quanqiu.png" alt="全球通" />
          <h1>全球通 · 管理后台</h1>
        </div>
      </div>
    </header>

    <div class="container main">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="卡密与授权" name="licenses">
          <el-tabs v-model="licenseSubTab">
            <el-tab-pane label="配置中心" name="config">
              <el-row :gutter="12">
                <el-col :xs="24" :lg="14">
                  <el-card shadow="hover">
                    <template #header>
                      <div class="card-header card-header-between">
                        <span>Key规格配置</span>
                        <el-button type="primary" size="small" @click="openCreatePlanDialog">新增Key规格</el-button>
                      </div>
                    </template>
                    <el-table :data="plans" stripe>
                      <el-table-column prop="display_name" label="Key规格" min-width="120" />
                      <el-table-column label="价格" width="110">
                        <template #default="{ row }">¥{{ row.price_yuan }}</template>
                      </el-table-column>
                      <el-table-column prop="duration_days" label="时长(天)" width="110" />
                      <el-table-column prop="billing_cycle" label="周期" width="100" />
                      <el-table-column label="状态" width="90">
                        <template #default="{ row }">
                          <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag>
                        </template>
                      </el-table-column>
                      <el-table-column label="操作" width="200">
                        <template #default="{ row }">
                          <el-button link type="primary" @click="openPlanDialog(row)">编辑</el-button>
                          <el-button link type="danger" @click="deletePlan(row)">删除</el-button>
                        </template>
                      </el-table-column>
                    </el-table>
                  </el-card>
                </el-col>

                <el-col :xs="24" :lg="10">
                  <el-card shadow="hover">
                    <template #header>
                      <div class="card-header">快捷操作</div>
                    </template>
                    <el-button type="primary" @click="generateCardDialogVisible = true">生成卡密</el-button>
                  </el-card>

                  <el-card class="mt12" shadow="hover">
                    <template #header>
                      <div class="card-header">购买入口配置</div>
                    </template>
                    <el-form label-position="top">
                      <el-form-item label="购买链接（Telegram 个人或 Bot）">
                        <el-input
                          v-model.trim="purchaseSettings.purchase_url"
                          placeholder="https://t.me/your_account_or_bot"
                        />
                      </el-form-item>
                      <el-form-item label="购买按钮文案">
                        <el-input
                          v-model.trim="purchaseSettings.purchase_button_text"
                          placeholder="联系 Telegram 购买"
                        />
                      </el-form-item>
                      <el-button type="primary" :loading="purchaseSaving" @click="savePurchaseSettings">
                        保存购买入口
                      </el-button>
                    </el-form>
                  </el-card>
                </el-col>
              </el-row>
            </el-tab-pane>

            <el-tab-pane label="Key与授权数据" name="data">
              <el-card shadow="hover">
                <template #header>
                  <div class="card-header">Key列表</div>
                </template>
                <div class="stats-row">
                  <div class="stats-item">
                    <div class="stats-label">总数</div>
                    <div class="stats-value">{{ cardStats.total }}</div>
                  </div>
                  <div class="stats-item">
                    <div class="stats-label">已用</div>
                    <div class="stats-value text-warning">{{ cardStats.used }}</div>
                  </div>
                  <div class="stats-item">
                    <div class="stats-label">未用</div>
                    <div class="stats-value text-success">{{ cardStats.unused }}</div>
                  </div>
                </div>
                <div class="toolbar">
                  <el-select v-model="cardFilter.plan_code" clearable placeholder="Key规格" style="width: 140px">
                    <el-option v-for="p in plans" :key="p.plan_code" :label="p.display_name" :value="p.plan_code" />
                  </el-select>
                  <el-select v-model="cardFilter.is_used" clearable placeholder="使用状态" style="width: 130px">
                    <el-option label="未使用" :value="false" />
                    <el-option label="已使用" :value="true" />
                  </el-select>
                  <el-select v-model="cardFilter.is_active" clearable placeholder="启用状态" style="width: 130px">
                    <el-option label="启用" :value="true" />
                    <el-option label="停用" :value="false" />
                  </el-select>
                  <el-select v-model="cardSort.sort_by" placeholder="时间字段" style="width: 140px">
                    <el-option label="创建时间" value="created_at" />
                    <el-option label="使用时间" value="used_at" />
                    <el-option label="过期时间" value="expires_at" />
                  </el-select>
                  <el-select v-model="cardSort.sort_order" placeholder="排序" style="width: 110px">
                    <el-option label="倒序" value="desc" />
                    <el-option label="正序" value="asc" />
                  </el-select>
                  <el-button @click="applyCardFilters">筛选</el-button>
                  <el-button type="primary" :loading="exportingCards" @click="exportCardsXlsx">导出XLSX</el-button>
                </div>
                <el-table :data="cards" stripe class="mt12">
                  <el-table-column prop="card_code" label="卡密" min-width="220" />
                  <el-table-column prop="plan_code" label="规格" width="110" />
                  <el-table-column label="绑定账号" min-width="160">
                    <template #default="{ row }">
                      {{ row.bound_account_name || (row.bound_account_id ? `${row.bound_account_id.slice(0, 8)}...` : '未绑定') }}
                    </template>
                  </el-table-column>
                  <el-table-column label="授权到期" width="170">
                    <template #default="{ row }">{{ formatDateTime(row.authorization_end_at) }}</template>
                  </el-table-column>
                  <el-table-column label="状态" width="120">
                    <template #default="{ row }">
                      <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="使用" width="100">
                    <template #default="{ row }">
                      <el-tag :type="row.is_used ? 'warning' : 'success'">{{ row.is_used ? '已使用' : '未使用' }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="过期时间" width="170">
                    <template #default="{ row }">{{ formatDateTime(row.expires_at) }}</template>
                  </el-table-column>
                  <el-table-column label="使用时间" width="170">
                    <template #default="{ row }">{{ formatDateTime(row.used_at) }}</template>
                  </el-table-column>
                  <el-table-column label="操作" width="120">
                    <template #default="{ row }">
                      <el-button
                        v-if="row.is_active"
                        link
                        type="danger"
                        :disabled="row.is_used"
                        @click="toggleCard(row.card_code, false)"
                      >
                        停用
                      </el-button>
                      <el-button v-else link type="primary" :disabled="row.is_used" @click="toggleCard(row.card_code, true)">
                        启用
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <el-pagination
                  class="mt12"
                  background
                  layout="total, sizes, prev, pager, next"
                  :total="cardsPagination.total"
                  :current-page="cardsPagination.currentPage"
                  :page-size="cardsPagination.pageSize"
                  :page-sizes="[20, 50, 100]"
                  @current-change="handleCardsPageChange"
                  @size-change="handleCardsSizeChange"
                />
              </el-card>
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>

        <el-tab-pane label="用户与账号" name="users">
          <el-card shadow="hover">
            <template #header>
              <div class="card-header">用户管理</div>
            </template>
            <div class="toolbar">
              <el-input v-model.trim="userSearch" placeholder="搜索用户名/邮箱" style="width: 260px" @keyup.enter="loadUsers" />
              <el-button @click="loadUsers">搜索</el-button>
              <el-button @click="loadUsers">刷新</el-button>
            </div>
            <el-table :data="users" stripe class="mt12">
              <el-table-column prop="id" label="用户ID" width="90" />
              <el-table-column prop="username" label="用户名" min-width="130" />
              <el-table-column prop="email" label="邮箱" min-width="170" />
              <el-table-column label="账号数" width="90">
                <template #default="{ row }">{{ row.account_count }}</template>
              </el-table-column>
              <el-table-column label="已登录TG账号" width="120">
                <template #default="{ row }">
                  <el-tag>{{ row.account_count }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="最近到期" width="170">
                <template #default="{ row }">{{ formatDateTime(row.current_authorization?.end_at) }}</template>
              </el-table-column>
              <el-table-column label="当前授权" width="150">
                <template #default="{ row }">
                  <el-tag :type="row.current_authorization?.status === 'active' ? 'success' : 'info'">
                    {{ row.current_authorization?.status === 'active' ? '已授权' : '未授权' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="开发者应用" min-width="260">
                <template #default="{ row }">
                  <div class="user-dev-app-cell">
                    <el-select
                      v-model="userDeveloperAppDraft[row.id]"
                      clearable
                      filterable
                      placeholder="默认策略"
                      style="width: 160px"
                    >
                      <el-option
                        v-for="app in developerApps"
                        :key="app.id"
                        :label="`${app.app_name} (#${app.id})`"
                        :value="app.id"
                      />
                    </el-select>
                    <el-button
                      size="small"
                      type="primary"
                      :loading="userDeveloperAppSaving[row.id] === true"
                      @click="saveUserDeveloperApp(row)"
                    >
                      保存
                    </el-button>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="300" fixed="right">
                <template #default="{ row }">
                  <el-button link type="primary" @click="openAccountsDrawer(row)">账号列表</el-button>
                  <el-button link type="danger" @click="resetPassword(row.id)">重置密码</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-tab-pane>

        <el-tab-pane label="开发者应用" name="developer-apps">
          <el-row :gutter="12">
            <el-col :xs="24" :lg="24">
              <el-card shadow="hover">
                <template #header>
                  <div class="card-header">开发者应用列表</div>
                </template>
                <div class="toolbar">
                  <el-select v-model="developerAppSettings.assignment_mode" style="width: 180px">
                    <el-option label="轮询分配" value="round_robin" />
                    <el-option label="权重优先" value="weight" />
                  </el-select>
                  <el-input
                    v-model.trim="developerAppSettings.alert_tg_user_ids_text"
                    placeholder="管理员告警 TG 用户ID，多个用逗号分隔"
                    style="width: 360px"
                  />
                  <el-button type="primary" :loading="developerAppSettingsSaving" @click="saveDeveloperAppSettings">
                    保存策略
                  </el-button>
                </div>
                <el-alert
                  class="mt12"
                  type="info"
                  :closable="false"
                  title="新账号默认按“轮询主选、权重兜底”分配开发者应用；已绑定账号保持粘性。"
                />
                <div class="toolbar">
                  <el-button type="primary" @click="developerAppCreateDialogVisible = true">新增开发者应用</el-button>
                  <el-button @click="loadDeveloperApps">刷新</el-button>
                </div>
                <el-table :data="developerApps" stripe class="mt12">
                  <el-table-column label="#" width="72">
                    <template #default="{ row }">{{ row.id }}</template>
                  </el-table-column>
                  <el-table-column prop="app_name" label="应用名" min-width="140" />
                  <el-table-column prop="api_id" label="API_ID" width="110" />
                  <el-table-column label="默认" width="90">
                    <template #default="{ row }">
                      <el-tag :type="row.is_default ? 'success' : 'info'">
                        {{ row.is_default ? '默认' : '否' }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="容量" width="130">
                    <template #default="{ row }">
                      {{ row.account_usage }}/{{ row.max_accounts > 0 ? row.max_accounts : '∞' }}
                    </template>
                  </el-table-column>
                  <el-table-column label="权重" width="90">
                    <template #default="{ row }">{{ row.selection_weight }}</template>
                  </el-table-column>
                  <el-table-column label="凭证版本" width="110">
                    <template #default="{ row }">{{ row.credentials_version }}</template>
                  </el-table-column>
                  <el-table-column label="健康状态" width="120">
                    <template #default="{ row }">
                      <el-tag
                        :type="row.health_status === 'healthy' ? 'success' : row.health_status === 'unhealthy' ? 'danger' : 'info'"
                      >
                        {{
                          row.health_status === 'healthy'
                            ? '健康'
                            : row.health_status === 'unhealthy'
                              ? '异常'
                              : row.health_status === 'disabled'
                                ? '停用'
                                : '检测中'
                        }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="最近检测" width="170">
                    <template #default="{ row }">{{ formatDateTime(row.last_health_check_at) }}</template>
                  </el-table-column>
                  <el-table-column label="最近耗时" width="100">
                    <template #default="{ row }">{{ row.last_health_latency_ms ? `${row.last_health_latency_ms}ms` : '-' }}</template>
                  </el-table-column>
                  <el-table-column label="最近轮换" width="170">
                    <template #default="{ row }">{{ formatDateTime(row.last_rotated_at) }}</template>
                  </el-table-column>
                  <el-table-column label="最近错误" min-width="220">
                    <template #default="{ row }">{{ row.last_health_error || '-' }}</template>
                  </el-table-column>
                  <el-table-column label="状态" width="90">
                    <template #default="{ row }">
                      <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="备注" min-width="140">
                    <template #default="{ row }">{{ row.notes || '-' }}</template>
                  </el-table-column>
                  <el-table-column label="操作" width="260" fixed="right">
                    <template #default="{ row }">
                      <el-button
                        link
                        type="warning"
                        :loading="developerAppHealthChecking[row.id] === true"
                        @click="checkDeveloperApp(row.id)"
                      >
                        检测
                      </el-button>
                      <el-button link type="primary" @click="openDeveloperAppEdit(row)">编辑</el-button>
                      <el-button link :disabled="row.is_default" @click="setDefaultDeveloperApp(row.id)">设为默认</el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </el-card>
            </el-col>
          </el-row>
        </el-tab-pane>

        <el-tab-pane label="代理配置" name="proxies">
          <el-row :gutter="12">
            <el-col :xs="24" :lg="24">
              <el-card shadow="hover">
                <template #header>
                  <div class="card-header">代理列表</div>
                </template>
                <div class="toolbar">
                  <el-button type="primary" @click="proxyCreateDialogVisible = true">新增代理</el-button>
                  <el-button @click="loadProxies">刷新代理</el-button>
                  <el-button @click="loadProxyAccounts">刷新账号选项</el-button>
                </div>
                <el-table :data="proxies" stripe class="mt12">
                  <el-table-column label="地址" min-width="180">
                    <template #default="{ row }">
                      {{ row.host }}:{{ row.port }}
                    </template>
                  </el-table-column>
                  <el-table-column prop="proxy_type" label="类型" width="110" />
                  <el-table-column label="健康" width="140">
                    <template #default="{ row }">
                      <el-tag :type="row.is_healthy ? 'success' : 'danger'">
                        {{ row.is_healthy ? '健康' : '异常' }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="分配账号" min-width="270">
                    <template #default="{ row }">
                      <el-select
                        v-model="proxyAssignDraft[row.proxy_id]"
                        filterable
                        clearable
                        placeholder="选择账号"
                        style="width: 100%"
                      >
                        <el-option
                          v-for="acc in proxyAccounts"
                          :key="acc.account_id"
                          :label="acc.label"
                          :value="acc.account_id"
                        />
                      </el-select>
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="280">
                    <template #default="{ row }">
                      <el-button
                        size="small"
                        :loading="proxyHealthChecking[row.proxy_id] === true"
                        @click="checkProxy(row.proxy_id)"
                      >
                        检查
                      </el-button>
                      <el-button
                        size="small"
                        type="primary"
                        :loading="proxyAssigning[row.proxy_id] === true"
                        @click="assignProxy(row.proxy_id)"
                      >
                        分配
                      </el-button>
                      <el-button
                        size="small"
                        :disabled="!row.assigned_account_id"
                        @click="unassignProxy(row.proxy_id)"
                      >
                        解绑
                      </el-button>
                      <el-button size="small" type="danger" @click="removeProxy(row.proxy_id)">删除</el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </el-card>
            </el-col>
          </el-row>
        </el-tab-pane>

        <el-tab-pane label="操作审计日志" name="audit">
          <el-card shadow="hover">
            <template #header>
              <div class="card-header">管理员操作日志</div>
            </template>
            <div class="toolbar">
              <el-input
                v-model.trim="auditFilter.action"
                placeholder="按动作编码过滤，如 admin.delete_account"
                style="width: 280px"
                @keyup.enter="loadAuditLogs"
              />
              <el-input
                v-model.trim="auditFilter.target_type"
                placeholder="目标类型，如 user/account/card"
                style="width: 220px"
                @keyup.enter="loadAuditLogs"
              />
              <el-input
                v-model.trim="auditFilter.target_id"
                placeholder="目标ID，如 user_id/account_id"
                style="width: 220px"
                @keyup.enter="loadAuditLogs"
              />
              <el-input-number
                v-model="auditFilter.developer_app_id"
                :min="1"
                placeholder="开发者应用ID"
                controls-position="right"
                style="width: 180px"
              />
              <el-button @click="loadAuditLogs">筛选</el-button>
            </div>
            <el-table :data="auditLogs" stripe class="mt12">
              <el-table-column prop="id" label="#" width="72" />
              <el-table-column prop="created_at" label="时间" width="170">
                <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
              </el-table-column>
              <el-table-column prop="actor" label="操作者" width="130" />
              <el-table-column label="动作" min-width="220">
                <template #default="{ row }">
                  {{ row.action_label || row.action }}
                </template>
              </el-table-column>
              <el-table-column label="目标" min-width="180">
                <template #default="{ row }">
                  {{ row.target_type_label || row.target_type || '-' }} / {{ row.target_id || '-' }}
                </template>
              </el-table-column>
              <el-table-column label="开发者应用" width="110">
                <template #default="{ row }">{{ row.developer_app_id || '-' }}</template>
              </el-table-column>
              <el-table-column prop="ip_address" label="IP" width="130" />
              <el-table-column label="变更前" min-width="220">
                <template #default="{ row }">
                  <span>{{ renderJson(row.old_value) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="变更后" min-width="220">
                <template #default="{ row }">
                  <span>{{ renderJson(row.new_value) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="详情" min-width="260">
                <template #default="{ row }">
                  <span>{{ renderDetail(row.detail) }}</span>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-tab-pane>
      </el-tabs>
    </div>

    <el-dialog v-model="planDialog.visible" title="编辑Key规格" width="420px">
        <el-form label-position="top">
        <el-form-item label="名称">
          <el-input v-model.trim="planDialog.form.display_name" />
        </el-form-item>
        <el-form-item label="计费周期">
          <el-input v-model.trim="planDialog.form.billing_cycle" placeholder="monthly/yearly/custom" />
        </el-form-item>
        <el-form-item label="价格（分）">
          <el-input-number v-model="planDialog.form.price_cents" :min="1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="时长（天）">
          <el-input-number v-model="planDialog.form.duration_days" :min="1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="planDialog.form.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="planDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="planDialog.saving" @click="savePlan">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="planCreateDialog.visible" title="新增Key规格" width="440px">
      <el-form label-position="top">
        <el-form-item label="Key规格编码">
          <el-input v-model.trim="planCreateDialog.form.plan_code" placeholder="例如 quarterly_90d" />
        </el-form-item>
        <el-form-item label="显示名称">
          <el-input v-model.trim="planCreateDialog.form.display_name" placeholder="例如 90天Key" />
        </el-form-item>
        <el-form-item label="计费周期">
          <el-input v-model.trim="planCreateDialog.form.billing_cycle" placeholder="monthly/yearly/custom" />
        </el-form-item>
        <el-form-item label="价格（分）">
          <el-input-number v-model="planCreateDialog.form.price_cents" :min="1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="时长（天）">
          <el-input-number v-model="planCreateDialog.form.duration_days" :min="1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="planCreateDialog.form.sort_order" :min="0" style="width: 100%" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="planCreateDialog.form.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="planCreateDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="planCreateDialog.saving" @click="createPlan">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="generateCardDialogVisible" title="生成卡密" width="460px">
      <el-form label-position="top">
        <el-form-item label="Key规格">
          <el-select v-model="genForm.plan_code" style="width: 100%">
            <el-option v-for="p in plans" :key="p.plan_code" :label="p.display_name" :value="p.plan_code" />
          </el-select>
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="genForm.quantity" :min="1" :max="500" style="width: 100%" />
        </el-form-item>
        <el-alert
          type="info"
          :closable="false"
          title="卡密时长统一使用所选Key规格配置，不再支持覆盖时长。"
        />
        <el-form-item label="卡密有效期(天，可选)">
          <el-input-number v-model="genForm.valid_days" :min="1" :max="3650" style="width: 100%" />
        </el-form-item>
        <el-form-item label="前缀(可选)">
          <el-input v-model.trim="genForm.prefix" placeholder="例如 MTH-" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="generateCardDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="generating" @click="handleGenerateCards">生成</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="developerAppCreateDialogVisible" title="新增开发者应用" width="460px">
      <el-form label-position="top">
        <el-form-item label="应用名称">
          <el-input v-model.trim="developerAppCreateForm.app_name" placeholder="例如 官方应用A" />
        </el-form-item>
        <el-form-item label="API_ID">
          <el-input-number
            v-model="developerAppCreateForm.api_id"
            :min="1"
            :step="1"
            controls-position="right"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="API_HASH">
          <el-input v-model.trim="developerAppCreateForm.api_hash" type="password" show-password />
        </el-form-item>
        <el-form-item label="最大账号数（0=不限制）">
          <el-input-number
            v-model="developerAppCreateForm.max_accounts"
            :min="0"
            :step="1"
            controls-position="right"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="分配权重">
          <el-input-number
            v-model="developerAppCreateForm.selection_weight"
            :min="1"
            :step="1"
            controls-position="right"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model.trim="developerAppCreateForm.notes" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="developerAppCreateForm.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="developerAppCreateDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="creatingDeveloperApp" @click="createDeveloperApp">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="proxyCreateDialogVisible" title="新增代理" width="460px">
      <el-form label-position="top">
        <el-form-item label="类型">
          <el-select v-model="proxyForm.proxy_type" style="width: 100%">
            <el-option label="SOCKS5" value="socks5" />
            <el-option label="HTTP" value="http" />
            <el-option label="MTPROTO" value="mtproto" />
          </el-select>
        </el-form-item>
        <el-form-item label="Host">
          <el-input v-model.trim="proxyForm.host" placeholder="127.0.0.1" />
        </el-form-item>
        <el-form-item label="Port">
          <el-input-number v-model="proxyForm.port" :min="1" :max="65535" style="width: 100%" />
        </el-form-item>
        <el-form-item label="用户名(可选)">
          <el-input v-model.trim="proxyForm.username" />
        </el-form-item>
        <el-form-item label="密码(可选)">
          <el-input v-model="proxyForm.password" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="proxyCreateDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="addingProxy" @click="addProxy">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="developerAppEditDialog.visible" title="编辑开发者应用" width="460px">
      <el-form label-position="top">
        <el-form-item label="应用名称">
          <el-input v-model.trim="developerAppEditDialog.form.app_name" />
        </el-form-item>
        <el-form-item label="API_HASH（留空表示不改）">
          <el-input v-model.trim="developerAppEditDialog.form.api_hash" type="password" show-password />
        </el-form-item>
        <el-form-item label="最大账号数（0=不限制）">
          <el-input-number
            v-model="developerAppEditDialog.form.max_accounts"
            :min="0"
            controls-position="right"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="分配权重">
          <el-input-number
            v-model="developerAppEditDialog.form.selection_weight"
            :min="1"
            controls-position="right"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model.trim="developerAppEditDialog.form.notes" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="developerAppEditDialog.form.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="developerAppEditDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="developerAppEditDialog.saving" @click="saveDeveloperAppEdit">
          保存
        </el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="accountsDrawer.visible" title="用户账号列表" size="70%">
      <el-table :data="accountsDrawer.accounts" stripe>
        <el-table-column prop="account_id" label="账号ID" min-width="220" />
        <el-table-column prop="username" label="TG用户名" min-width="120" />
        <el-table-column prop="phone" label="手机号" width="140" />
        <el-table-column prop="developer_app_id" label="开发者应用ID" width="120" />
        <el-table-column prop="health_status" label="健康状态" width="110" />
        <el-table-column prop="messages_sent" label="发送数" width="90" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button link type="danger" @click="deleteAccount(row.account_id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type {
  AdminAccount,
  AdminAccountOption,
  AdminAuditLog,
  AdminCard,
  AdminDeveloperApp,
  AdminDeveloperAppSettings,
  AdminPlan,
  AdminPurchaseSettings,
  AdminProxy,
  AdminUserSummary,
} from '@/api/admin'
import {
  adminAddProxy,
  adminAssignProxy,
  adminCheckProxyHealth,
  adminCheckDeveloperAppHealth,
  adminCreatePlan,
  adminCreateDeveloperApp,
  adminDeletePlan,
  adminDeleteProxy,
  adminDeleteAccount,
  adminDisableCard,
  adminEnableCard,
  adminExportCardsXlsx,
  adminGetPurchaseSettings,
  adminGenerateCards,
  adminListDeveloperApps,
  adminListAccountOptions,
  adminListAuditLogs,
  adminListCards,
  adminGetDeveloperAppSettings,
  adminListPlans,
  adminListProxies,
  adminListUserAccounts,
  adminListUsers,
  adminResetUserPassword,
  adminSetDefaultDeveloperApp,
  adminSetUserDeveloperApp,
  adminUnassignProxy,
  adminUpdateDeveloperApp,
  adminUpdateDeveloperAppSettings,
  adminUpdatePurchaseSettings,
  adminUpdatePlan,
  hasAdminToken,
} from '@/api/admin'

const activeTab = ref('licenses')
const licenseSubTab = ref('config')
const router = useRouter()

const plans = ref<AdminPlan[]>([])
const cards = ref<AdminCard[]>([])
const users = ref<AdminUserSummary[]>([])
const developerApps = ref<AdminDeveloperApp[]>([])
const auditLogs = ref<AdminAuditLog[]>([])
const proxies = ref<AdminProxy[]>([])
const proxyAccounts = ref<AdminAccountOption[]>([])
const userSearch = ref('')
const generateCardDialogVisible = ref(false)
const proxyCreateDialogVisible = ref(false)
const developerAppCreateDialogVisible = ref(false)
const generating = ref(false)
const exportingCards = ref(false)
const addingProxy = ref(false)
const creatingDeveloperApp = ref(false)
const developerAppSettingsSaving = ref(false)
const proxyAssigning = ref<Record<number, boolean>>({})
const proxyHealthChecking = ref<Record<number, boolean>>({})
const developerAppHealthChecking = ref<Record<number, boolean>>({})
const userDeveloperAppSaving = ref<Record<number, boolean>>({})
const purchaseSaving = ref(false)
const cardsPagination = reactive({
  currentPage: 1,
  pageSize: 20,
  total: 0,
})
const cardStats = reactive({
  total: 0,
  used: 0,
  unused: 0,
})

const cardFilter = reactive({
  plan_code: '',
  is_used: undefined as boolean | undefined,
  is_active: undefined as boolean | undefined,
})
const cardSort = reactive({
  sort_by: 'created_at' as 'created_at' | 'used_at' | 'expires_at',
  sort_order: 'desc' as 'asc' | 'desc',
})

const auditFilter = reactive({
  action: '',
  target_type: '',
  target_id: '',
  developer_app_id: undefined as number | undefined,
})

const proxyForm = reactive({
  proxy_type: 'socks5',
  host: '',
  port: 1080,
  username: '',
  password: '',
})

const proxyAssignDraft = reactive<Record<number, string>>({})
const purchaseSettings = reactive<AdminPurchaseSettings>({
  purchase_url: '',
  purchase_button_text: '联系 Telegram 购买',
})

const userDeveloperAppDraft = reactive<Record<number, number | null>>({})
const developerAppSettings = reactive<AdminDeveloperAppSettings>({
  assignment_mode: 'round_robin',
  alert_tg_user_ids: [],
  alert_tg_user_ids_text: '',
})

const developerAppCreateForm = reactive({
  app_name: '',
  api_id: undefined as number | undefined,
  api_hash: '',
  is_active: true,
  max_accounts: 0,
  selection_weight: 100,
  notes: '',
})

const developerAppEditDialog = reactive({
  visible: false,
  saving: false,
  appId: 0,
  form: {
    app_name: '',
    api_hash: '',
    is_active: true,
    max_accounts: 0,
    selection_weight: 100,
    notes: '',
  },
})

const genForm = reactive({
  plan_code: '',
  quantity: 10,
  valid_days: undefined as number | undefined,
  prefix: '',
})

const planDialog = reactive({
  visible: false,
  saving: false,
  planCode: '',
  form: {
    display_name: '',
    billing_cycle: 'monthly',
    price_cents: 20000,
    duration_days: 30,
    is_active: true,
  },
})

const planCreateDialog = reactive({
  visible: false,
  saving: false,
  form: {
    plan_code: '',
    display_name: '',
    billing_cycle: 'custom',
    price_cents: 10000,
    duration_days: 30,
    sort_order: 0,
    is_active: true,
  },
})

const accountsDrawer = reactive({
  visible: false,
  userId: 0,
  accounts: [] as AdminAccount[],
})

const formatDateTime = (value?: string | null) => {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  const hh = String(date.getHours()).padStart(2, '0')
  const mm = String(date.getMinutes()).padStart(2, '0')
  return `${y}-${m}-${d} ${hh}:${mm}`
}

const parseBlobErrorMessage = async (error: any): Promise<string> => {
  const fallback = error?.message || '请求失败'
  const data = error?.response?.data
  if (!data) return fallback
  if (data instanceof Blob) {
    try {
      const text = await data.text()
      const json = JSON.parse(text)
      return json?.detail || fallback
    } catch {
      return fallback
    }
  }
  return data?.detail || fallback
}

const loadPlans = async () => {
  const res = await adminListPlans()
  plans.value = res.data || []
  if (!genForm.plan_code && plans.value[0]) {
    genForm.plan_code = plans.value[0].plan_code
  }
}

const loadPurchaseSettings = async () => {
  const res = await adminGetPurchaseSettings()
  purchaseSettings.purchase_url = res.data?.purchase_url || ''
  purchaseSettings.purchase_button_text = res.data?.purchase_button_text || '联系 Telegram 购买'
}

const loadCards = async () => {
  const res = await adminListCards({
    plan_code: cardFilter.plan_code || undefined,
    is_used: cardFilter.is_used,
    is_active: cardFilter.is_active,
    sort_by: cardSort.sort_by,
    sort_order: cardSort.sort_order,
    limit: cardsPagination.pageSize,
    offset: (cardsPagination.currentPage - 1) * cardsPagination.pageSize,
  })
  cards.value = res.data?.items || []
  cardsPagination.total = Number(res.data?.total || 0)
  cardStats.total = Number(res.data?.stats?.total || 0)
  cardStats.used = Number(res.data?.stats?.used || 0)
  cardStats.unused = Number(res.data?.stats?.unused || 0)
}

const applyCardFilters = async () => {
  cardsPagination.currentPage = 1
  await loadCards()
}

const handleCardsPageChange = async (page: number) => {
  cardsPagination.currentPage = page
  await loadCards()
}

const handleCardsSizeChange = async (size: number) => {
  cardsPagination.pageSize = size
  cardsPagination.currentPage = 1
  await loadCards()
}

const deletePlan = async (row: AdminPlan) => {
  try {
    await ElMessageBox.confirm(
      `将删除 Key规格「${row.display_name}」，并自动停用该规格下所有未使用卡密；已使用卡密仅保留历史记录。确认继续吗？`,
      '删除Key规格',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }

  const res = await adminDeletePlan(row.plan_code)
  ElMessage.success(
    `Key规格已删除，已停用未使用卡密 ${res.data?.disabled_unused_cards || 0} 个，保留已使用卡密 ${res.data?.used_cards_kept || 0} 个`,
  )
  await Promise.all([loadPlans(), loadCards(), loadAuditLogs()])
}

const loadUsers = async () => {
  const res = await adminListUsers({ search: userSearch.value || undefined, limit: 100 })
  users.value = res.data || []
  for (const user of users.value) {
    userDeveloperAppDraft[user.id] = user.developer_app_id ?? null
  }
}

const loadDeveloperApps = async () => {
  const res = await adminListDeveloperApps()
  developerApps.value = res.data?.apps || []
  if (res.data?.settings) {
    developerAppSettings.assignment_mode = res.data.settings.assignment_mode || 'round_robin'
    developerAppSettings.alert_tg_user_ids = res.data.settings.alert_tg_user_ids || []
    developerAppSettings.alert_tg_user_ids_text = res.data.settings.alert_tg_user_ids_text || ''
  }
}

const loadDeveloperAppSettings = async () => {
  const res = await adminGetDeveloperAppSettings()
  developerAppSettings.assignment_mode = res.data?.assignment_mode || 'round_robin'
  developerAppSettings.alert_tg_user_ids = res.data?.alert_tg_user_ids || []
  developerAppSettings.alert_tg_user_ids_text = res.data?.alert_tg_user_ids_text || ''
}

const loadAuditLogs = async () => {
  const res = await adminListAuditLogs({
    action: auditFilter.action || undefined,
    target_type: auditFilter.target_type || undefined,
    target_id: auditFilter.target_id || undefined,
    developer_app_id: auditFilter.developer_app_id,
    limit: 200,
  })
  auditLogs.value = res.data || []
}

const loadProxies = async () => {
  const res = await adminListProxies()
  proxies.value = res.data || []
  for (const p of proxies.value) {
    proxyAssignDraft[p.proxy_id] = p.assigned_account_id || proxyAssignDraft[p.proxy_id] || ''
  }
}

const loadProxyAccounts = async () => {
  const res = await adminListAccountOptions({ limit: 500 })
  proxyAccounts.value = res.data || []
}

const loadAll = async () => {
  await Promise.all([
    loadPlans(),
    loadPurchaseSettings(),
    loadCards(),
    loadDeveloperApps(),
    loadDeveloperAppSettings(),
    loadUsers(),
    loadAuditLogs(),
    loadProxies(),
    loadProxyAccounts(),
  ])
}

const savePurchaseSettings = async () => {
  if (!purchaseSettings.purchase_url.trim()) {
    ElMessage.warning('请填写购买链接')
    return
  }
  purchaseSaving.value = true
  try {
    await adminUpdatePurchaseSettings({
      purchase_url: purchaseSettings.purchase_url.trim(),
      purchase_button_text: purchaseSettings.purchase_button_text.trim() || '联系 Telegram 购买',
    })
    ElMessage.success('购买入口已更新')
    await loadAuditLogs()
  } finally {
    purchaseSaving.value = false
  }
}

const handleGenerateCards = async () => {
  if (!genForm.plan_code) {
    ElMessage.warning('请选择Key规格')
    return
  }
  generating.value = true
  try {
    await adminGenerateCards({
      plan_code: genForm.plan_code,
      quantity: genForm.quantity,
      valid_days: genForm.valid_days || undefined,
      prefix: genForm.prefix || '',
    })
    ElMessage.success('卡密生成成功')
    generateCardDialogVisible.value = false
    await loadCards()
    await loadAuditLogs()
  } catch (error: any) {
    const message = error?.response?.data?.detail || error?.message || '卡密生成失败，请稍后重试'
    ElMessage.error(message)
  } finally {
    generating.value = false
  }
}

const exportCardsXlsx = async () => {
  exportingCards.value = true
  try {
    const blob = await adminExportCardsXlsx({
      plan_code: cardFilter.plan_code || undefined,
      is_used: cardFilter.is_used,
      is_active: cardFilter.is_active,
    })
    const now = new Date()
    const stamp = [
      now.getFullYear(),
      String(now.getMonth() + 1).padStart(2, '0'),
      String(now.getDate()).padStart(2, '0'),
      '_',
      String(now.getHours()).padStart(2, '0'),
      String(now.getMinutes()).padStart(2, '0'),
      String(now.getSeconds()).padStart(2, '0'),
    ].join('')
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `cards_export_${stamp}.xlsx`
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch (error: any) {
    const message = await parseBlobErrorMessage(error)
    ElMessage.error(message)
  } finally {
    exportingCards.value = false
  }
}

const toggleCard = async (cardCode: string, enable: boolean) => {
  if (enable) {
    await adminEnableCard(cardCode)
  } else {
    await adminDisableCard(cardCode)
  }
  ElMessage.success(enable ? '卡密已启用' : '卡密已停用')
  await loadCards()
  await loadAuditLogs()
}

const openPlanDialog = (plan: AdminPlan) => {
  planDialog.planCode = plan.plan_code
  planDialog.form.display_name = plan.display_name
  planDialog.form.billing_cycle = plan.billing_cycle
  planDialog.form.price_cents = plan.price_cents
  planDialog.form.duration_days = plan.duration_days
  planDialog.form.is_active = plan.is_active
  planDialog.visible = true
}

const savePlan = async () => {
  if (!planDialog.planCode) return
  planDialog.saving = true
  try {
    await adminUpdatePlan(planDialog.planCode, {
      display_name: planDialog.form.display_name,
      billing_cycle: planDialog.form.billing_cycle,
      price_cents: planDialog.form.price_cents,
      duration_days: planDialog.form.duration_days,
      is_active: planDialog.form.is_active,
    })
    ElMessage.success('Key规格已更新')
    planDialog.visible = false
    await loadPlans()
    await loadAuditLogs()
  } finally {
    planDialog.saving = false
  }
}

const openCreatePlanDialog = () => {
  planCreateDialog.form.plan_code = ''
  planCreateDialog.form.display_name = ''
  planCreateDialog.form.billing_cycle = 'custom'
  planCreateDialog.form.price_cents = 10000
  planCreateDialog.form.duration_days = 30
  planCreateDialog.form.sort_order = 0
  planCreateDialog.form.is_active = true
  planCreateDialog.visible = true
}

const createPlan = async () => {
  if (!planCreateDialog.form.plan_code.trim()) {
    ElMessage.warning('请填写Key规格编码')
    return
  }
  if (!planCreateDialog.form.display_name.trim()) {
    ElMessage.warning('请填写显示名称')
    return
  }
  planCreateDialog.saving = true
  try {
    await adminCreatePlan({
      plan_code: planCreateDialog.form.plan_code.trim(),
      display_name: planCreateDialog.form.display_name.trim(),
      billing_cycle: planCreateDialog.form.billing_cycle.trim() || 'custom',
      price_cents: Number(planCreateDialog.form.price_cents),
      duration_days: Number(planCreateDialog.form.duration_days),
      sort_order: Number(planCreateDialog.form.sort_order || 0),
      is_active: Boolean(planCreateDialog.form.is_active),
    })
    ElMessage.success('Key规格已创建')
    planCreateDialog.visible = false
    await loadPlans()
    await loadAuditLogs()
  } finally {
    planCreateDialog.saving = false
  }
}

const resetPassword = async (userId: number) => {
  const promptResult = await ElMessageBox.prompt('请输入新密码（至少6位）', '重置密码', {
    inputType: 'password',
    inputPattern: /^.{6,128}$/,
    inputErrorMessage: '密码长度需在 6-128 位',
    confirmButtonText: '确定',
    cancelButtonText: '取消',
  })
  const newPassword = String((promptResult as any).value || '')
  await adminResetUserPassword(userId, newPassword)
  ElMessage.success('密码重置成功')
  await loadAuditLogs()
}

const createDeveloperApp = async () => {
  if (!developerAppCreateForm.app_name.trim()) {
    ElMessage.warning('请输入应用名称')
    return
  }
  if (!developerAppCreateForm.api_id) {
    ElMessage.warning('请输入 API_ID')
    return
  }
  if (!developerAppCreateForm.api_hash.trim()) {
    ElMessage.warning('请输入 API_HASH')
    return
  }
  creatingDeveloperApp.value = true
  try {
    await adminCreateDeveloperApp({
      app_name: developerAppCreateForm.app_name.trim(),
      api_id: Number(developerAppCreateForm.api_id),
      api_hash: developerAppCreateForm.api_hash.trim(),
      is_active: developerAppCreateForm.is_active,
      max_accounts: Number(developerAppCreateForm.max_accounts || 0),
      selection_weight: Number(developerAppCreateForm.selection_weight || 100),
      notes: developerAppCreateForm.notes.trim() || undefined,
    })
    ElMessage.success('开发者应用已创建')
    developerAppCreateForm.app_name = ''
    developerAppCreateForm.api_id = undefined
    developerAppCreateForm.api_hash = ''
    developerAppCreateForm.is_active = true
    developerAppCreateForm.max_accounts = 0
    developerAppCreateForm.selection_weight = 100
    developerAppCreateForm.notes = ''
    developerAppCreateDialogVisible.value = false
    await loadDeveloperApps()
    await loadAuditLogs()
  } finally {
    creatingDeveloperApp.value = false
  }
}

const openDeveloperAppEdit = (app: AdminDeveloperApp) => {
  developerAppEditDialog.appId = app.id
  developerAppEditDialog.form.app_name = app.app_name
  developerAppEditDialog.form.api_hash = ''
  developerAppEditDialog.form.is_active = app.is_active
  developerAppEditDialog.form.max_accounts = app.max_accounts
  developerAppEditDialog.form.selection_weight = app.selection_weight
  developerAppEditDialog.form.notes = app.notes || ''
  developerAppEditDialog.visible = true
}

const saveDeveloperAppEdit = async () => {
  if (!developerAppEditDialog.appId) return
  if (!developerAppEditDialog.form.app_name.trim()) {
    ElMessage.warning('应用名称不能为空')
    return
  }
  developerAppEditDialog.saving = true
  try {
    const response = await adminUpdateDeveloperApp(developerAppEditDialog.appId, {
      app_name: developerAppEditDialog.form.app_name.trim(),
      api_hash: developerAppEditDialog.form.api_hash.trim() || undefined,
      is_active: developerAppEditDialog.form.is_active,
      max_accounts: Number(developerAppEditDialog.form.max_accounts || 0),
      selection_weight: Number(developerAppEditDialog.form.selection_weight || 100),
      notes: developerAppEditDialog.form.notes.trim() || undefined,
    })
    const rotated = Number(response.data?.rotated_accounts || 0)
    ElMessage.success(
      rotated > 0 ? `开发者应用已更新，${rotated} 个账号需要重新绑定` : '开发者应用已更新',
    )
    developerAppEditDialog.visible = false
    await loadDeveloperApps()
    await loadUsers()
    await loadAuditLogs()
  } finally {
    developerAppEditDialog.saving = false
  }
}

const saveDeveloperAppSettings = async () => {
  developerAppSettingsSaving.value = true
  try {
    await adminUpdateDeveloperAppSettings({
      assignment_mode: developerAppSettings.assignment_mode,
      alert_tg_user_ids: developerAppSettings.alert_tg_user_ids_text || '',
    })
    ElMessage.success('开发者应用分配设置已更新')
    await Promise.all([loadDeveloperApps(), loadAuditLogs()])
  } finally {
    developerAppSettingsSaving.value = false
  }
}

const setDefaultDeveloperApp = async (appId: number) => {
  await adminSetDefaultDeveloperApp(appId)
  ElMessage.success('默认开发者应用已更新')
  await loadDeveloperApps()
  await loadAuditLogs()
}

const checkDeveloperApp = async (appId: number) => {
  developerAppHealthChecking.value[appId] = true
  try {
    const res = await adminCheckDeveloperAppHealth(appId)
    const migrated = res.data?.migrated_account_ids?.length || 0
    const stalled = res.data?.stalled_account_ids?.length || 0
    ElMessage.success(`检测完成：${res.data?.current_status || 'unknown'}，迁移 ${migrated} 个，待处理 ${stalled} 个`)
    await Promise.all([loadDeveloperApps(), loadUsers(), loadAuditLogs()])
  } finally {
    developerAppHealthChecking.value[appId] = false
  }
}

const saveUserDeveloperApp = async (user: AdminUserSummary) => {
  userDeveloperAppSaving.value[user.id] = true
  try {
    await adminSetUserDeveloperApp(user.id, userDeveloperAppDraft[user.id])
    ElMessage.success(`用户 ${user.username} 的开发者应用已更新`)
    await loadUsers()
    await loadAuditLogs()
  } finally {
    userDeveloperAppSaving.value[user.id] = false
  }
}

const openAccountsDrawer = async (user: AdminUserSummary) => {
  accountsDrawer.userId = user.id
  const res = await adminListUserAccounts(user.id)
  accountsDrawer.accounts = res.data || []
  accountsDrawer.visible = true
}

const deleteAccount = async (accountId: string) => {
  await ElMessageBox.confirm(`确定删除账号 ${accountId} 吗？`, '删除账号', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  })
  await adminDeleteAccount(accountId)
  ElMessage.success('账号已删除')
  accountsDrawer.accounts = accountsDrawer.accounts.filter((a) => a.account_id !== accountId)
  await loadUsers()
  await loadAuditLogs()
}

const renderDetail = (detail: Record<string, any> | null) => {
  if (!detail) return '-'
  const text = JSON.stringify(detail)
  return text.length > 120 ? `${text.slice(0, 120)}...` : text
}

const renderJson = (value: Record<string, any> | null | undefined) => {
  if (!value) return '-'
  const text = JSON.stringify(value)
  return text.length > 160 ? `${text.slice(0, 160)}...` : text
}

const addProxy = async () => {
  if (!proxyForm.host || !proxyForm.port) {
    ElMessage.warning('请填写代理 host 和端口')
    return
  }
  addingProxy.value = true
  try {
    await adminAddProxy({
      proxy_type: proxyForm.proxy_type,
      host: proxyForm.host,
      port: Number(proxyForm.port),
      username: proxyForm.username || undefined,
      password: proxyForm.password || undefined,
    })
    ElMessage.success('代理添加成功')
    proxyForm.host = ''
    proxyForm.port = 1080
    proxyForm.username = ''
    proxyForm.password = ''
    proxyCreateDialogVisible.value = false
    await loadProxies()
    await loadAuditLogs()
  } finally {
    addingProxy.value = false
  }
}

const checkProxy = async (proxyId: number) => {
  proxyHealthChecking.value[proxyId] = true
  try {
    const res = await adminCheckProxyHealth(proxyId)
    if (res.data.is_healthy) {
      ElMessage.success(`健康检查通过 (${res.data.response_time_ms}ms)`)
    } else {
      ElMessage.warning(res.data.error || '代理异常')
    }
    await loadProxies()
    await loadAuditLogs()
  } finally {
    proxyHealthChecking.value[proxyId] = false
  }
}

const assignProxy = async (proxyId: number) => {
  const accountId = proxyAssignDraft[proxyId]
  if (!accountId) {
    ElMessage.warning('请先选择要分配的账号')
    return
  }
  proxyAssigning.value[proxyId] = true
  try {
    await adminAssignProxy(proxyId, accountId)
    ElMessage.success('代理分配成功')
    await loadProxies()
    await loadAuditLogs()
  } finally {
    proxyAssigning.value[proxyId] = false
  }
}

const unassignProxy = async (proxyId: number) => {
  await adminUnassignProxy(proxyId)
  ElMessage.success('代理已解绑')
  await loadProxies()
  await loadAuditLogs()
}

const removeProxy = async (proxyId: number) => {
  await ElMessageBox.confirm(`确认删除代理 #${proxyId} 吗？`, '删除代理', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  })
  await adminDeleteProxy(proxyId)
  ElMessage.success('代理已删除')
  await loadProxies()
  await loadAuditLogs()
}

watch(activeTab, async (tab) => {
  if (tab === 'audit') {
    await loadAuditLogs()
  }
})

onMounted(async () => {
  if (!hasAdminToken()) {
    router.replace('/admin')
    return
  }
  await loadAll()
})
</script>

<style scoped>
.admin-page {
  min-height: 100vh;
  background: #f7f8fa;
}

.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 12px;
}

.header {
  background: #fff;
  border-bottom: 1px solid #ebeef5;
}

.brand-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-logo {
  width: 72px;
  height: auto;
  display: block;
}

h1 {
  margin: 8px 0 0;
  font-size: 24px;
}

.main {
  padding-top: 12px;
}

.card-header {
  font-weight: 600;
}

.card-header-between {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.toolbar {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}

.stats-item {
  padding: 12px 14px;
  border: 1px solid #ebeef5;
  border-radius: 10px;
  background: #fafafa;
}

.stats-label {
  color: #909399;
  font-size: 13px;
}

.stats-value {
  margin-top: 6px;
  font-size: 24px;
  font-weight: 700;
  color: #303133;
}

.text-warning {
  color: #e6a23c;
}

.text-success {
  color: #67c23a;
}

.user-dev-app-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.mt12 {
  margin-top: 12px;
}

@media (max-width: 768px) {
  h1 {
    font-size: 20px;
  }

  .stats-row {
    grid-template-columns: 1fr;
  }
}
</style>
