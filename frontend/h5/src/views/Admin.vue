<template>
  <div class="admin-page">
    <header class="header">
      <div class="container">
        <h1>管理员后台</h1>
      </div>
    </header>

    <div class="container main">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="卡密与套餐" name="billing">
          <el-row :gutter="12">
            <el-col :xs="24" :lg="14">
              <el-card shadow="hover">
                <template #header>
                  <div class="card-header">套餐配置</div>
                </template>
                <el-table :data="plans" stripe>
                  <el-table-column prop="display_name" label="套餐" min-width="120" />
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
                  <el-table-column label="操作" width="140">
                    <template #default="{ row }">
                      <el-button link type="primary" @click="openPlanDialog(row)">编辑</el-button>
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

          <el-card class="mt12" shadow="hover">
            <template #header>
              <div class="card-header">卡密列表</div>
            </template>
            <div class="toolbar">
              <el-select v-model="cardFilter.plan_code" clearable placeholder="套餐" style="width: 140px">
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
              <el-button @click="loadCards">筛选</el-button>
            </div>
            <el-table :data="cards" stripe class="mt12">
              <el-table-column prop="card_code" label="卡密" min-width="220" />
              <el-table-column prop="plan_code" label="套餐" width="110" />
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
          </el-card>
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
              <el-table-column label="订阅到期" width="170">
                <template #default="{ row }">{{ formatDateTime(row.subscription?.end_at) }}</template>
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
                  <el-button link type="warning" @click="openSubscriptionDialog(row)">改订阅</el-button>
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
                  <el-table-column label="凭证版本" width="110">
                    <template #default="{ row }">{{ row.credentials_version }}</template>
                  </el-table-column>
                  <el-table-column label="最近轮换" width="170">
                    <template #default="{ row }">{{ formatDateTime(row.last_rotated_at) }}</template>
                  </el-table-column>
                  <el-table-column label="状态" width="90">
                    <template #default="{ row }">
                      <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="备注" min-width="140">
                    <template #default="{ row }">{{ row.notes || '-' }}</template>
                  </el-table-column>
                  <el-table-column label="操作" width="200" fixed="right">
                    <template #default="{ row }">
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

    <el-dialog v-model="planDialog.visible" title="编辑套餐" width="420px">
      <el-form label-position="top">
        <el-form-item label="名称">
          <el-input v-model.trim="planDialog.form.display_name" />
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

    <el-dialog v-model="subDialog.visible" title="修改用户订阅" width="460px">
      <el-form label-position="top">
        <el-form-item label="用户">
          <el-input :value="subDialog.userLabel" disabled />
        </el-form-item>
        <el-form-item label="套餐">
          <el-select v-model="subDialog.form.plan_code" clearable style="width: 100%">
            <el-option v-for="p in plans" :key="p.plan_code" :label="p.display_name" :value="p.plan_code" />
          </el-select>
        </el-form-item>
        <el-form-item label="直接设置到期时间（可选）">
          <el-date-picker
            v-model="subDialog.form.end_at"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm:ss"
            style="width: 100%"
            placeholder="选择到期时间"
          />
        </el-form-item>
        <el-form-item label="延长天数（可选，支持负数）">
          <el-input-number v-model="subDialog.form.extend_days" :min="-3650" :max="3650" style="width: 100%" />
        </el-form-item>
        <el-form-item label="设为无效">
          <el-switch v-model="subDialog.form.set_inactive" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="subDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="subDialog.saving" @click="saveSubscription">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="generateCardDialogVisible" title="生成卡密" width="460px">
      <el-form label-position="top">
        <el-form-item label="套餐">
          <el-select v-model="genForm.plan_code" style="width: 100%">
            <el-option v-for="p in plans" :key="p.plan_code" :label="p.display_name" :value="p.plan_code" />
          </el-select>
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="genForm.quantity" :min="1" :max="500" style="width: 100%" />
        </el-form-item>
        <el-form-item label="覆盖时长(天，可选)">
          <el-input-number v-model="genForm.duration_days" :min="1" :max="3650" style="width: 100%" />
        </el-form-item>
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
  AdminPlan,
  AdminPurchaseSettings,
  AdminProxy,
  AdminUserSummary,
} from '@/api/admin'
import {
  adminAddProxy,
  adminAssignProxy,
  adminCheckProxyHealth,
  adminCreateDeveloperApp,
  adminDeleteProxy,
  adminDeleteAccount,
  adminDisableCard,
  adminEnableCard,
  adminGetPurchaseSettings,
  adminGenerateCards,
  adminListDeveloperApps,
  adminListAccountOptions,
  adminListAuditLogs,
  adminListCards,
  adminListPlans,
  adminListProxies,
  adminListUserAccounts,
  adminListUsers,
  adminResetUserPassword,
  adminSetDefaultDeveloperApp,
  adminSetUserDeveloperApp,
  adminUnassignProxy,
  adminUpdateDeveloperApp,
  adminUpdatePurchaseSettings,
  adminUpdatePlan,
  adminUpdateUserSubscription,
  hasAdminToken,
} from '@/api/admin'

const activeTab = ref('billing')
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
const addingProxy = ref(false)
const creatingDeveloperApp = ref(false)
const proxyAssigning = ref<Record<number, boolean>>({})
const proxyHealthChecking = ref<Record<number, boolean>>({})
const userDeveloperAppSaving = ref<Record<number, boolean>>({})
const purchaseSaving = ref(false)

const cardFilter = reactive({
  plan_code: '',
  is_used: undefined as boolean | undefined,
  is_active: undefined as boolean | undefined,
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

const developerAppCreateForm = reactive({
  app_name: '',
  api_id: undefined as number | undefined,
  api_hash: '',
  is_active: true,
  max_accounts: 0,
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
    notes: '',
  },
})

const genForm = reactive({
  plan_code: '',
  quantity: 10,
  duration_days: undefined as number | undefined,
  valid_days: undefined as number | undefined,
  prefix: '',
})

const planDialog = reactive({
  visible: false,
  saving: false,
  planCode: '',
  form: {
    display_name: '',
    price_cents: 20000,
    duration_days: 30,
    is_active: true,
  },
})

const subDialog = reactive({
  visible: false,
  saving: false,
  userId: 0,
  userLabel: '',
  form: {
    plan_code: '' as string | null,
    end_at: '' as string | null,
    extend_days: undefined as number | undefined,
    set_inactive: false,
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
    limit: 100,
  })
  cards.value = res.data || []
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
    ElMessage.warning('请选择套餐')
    return
  }
  generating.value = true
  try {
    await adminGenerateCards({
      plan_code: genForm.plan_code,
      quantity: genForm.quantity,
      duration_days: genForm.duration_days || undefined,
      valid_days: genForm.valid_days || undefined,
      prefix: genForm.prefix || '',
    })
    ElMessage.success('卡密生成成功')
    generateCardDialogVisible.value = false
    await loadCards()
    await loadAuditLogs()
  } finally {
    generating.value = false
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
      price_cents: planDialog.form.price_cents,
      duration_days: planDialog.form.duration_days,
      is_active: planDialog.form.is_active,
    })
    ElMessage.success('套餐已更新')
    planDialog.visible = false
    await loadPlans()
    await loadAuditLogs()
  } finally {
    planDialog.saving = false
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

const openSubscriptionDialog = (user: AdminUserSummary) => {
  subDialog.userId = user.id
  subDialog.userLabel = `${user.username} (#${user.id})`
  subDialog.form.plan_code = user.subscription?.plan_code || null
  subDialog.form.end_at = user.subscription?.end_at ? user.subscription.end_at.slice(0, 19) : null
  subDialog.form.extend_days = undefined
  subDialog.form.set_inactive = false
  subDialog.visible = true
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
      notes: developerAppCreateForm.notes.trim() || undefined,
    })
    ElMessage.success('开发者应用已创建')
    developerAppCreateForm.app_name = ''
    developerAppCreateForm.api_id = undefined
    developerAppCreateForm.api_hash = ''
    developerAppCreateForm.is_active = true
    developerAppCreateForm.max_accounts = 0
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
      notes: developerAppEditDialog.form.notes.trim() || undefined,
    })
    const rotated = Number(response.data?.rotated_accounts || 0)
    ElMessage.success(
      rotated > 0 ? `开发者应用已更新，${rotated} 个账号需要重新登录` : '开发者应用已更新',
    )
    developerAppEditDialog.visible = false
    await loadDeveloperApps()
    await loadUsers()
    await loadAuditLogs()
  } finally {
    developerAppEditDialog.saving = false
  }
}

const setDefaultDeveloperApp = async (appId: number) => {
  await adminSetDefaultDeveloperApp(appId)
  ElMessage.success('默认开发者应用已更新')
  await loadDeveloperApps()
  await loadAuditLogs()
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

const saveSubscription = async () => {
  if (!subDialog.userId) return
  subDialog.saving = true
  try {
    await adminUpdateUserSubscription(subDialog.userId, {
      plan_code: subDialog.form.plan_code || undefined,
      end_at: subDialog.form.end_at || undefined,
      extend_days: subDialog.form.extend_days,
      set_inactive: subDialog.form.set_inactive,
    })
    ElMessage.success('订阅已更新')
    subDialog.visible = false
    await loadUsers()
    await loadAuditLogs()
  } finally {
    subDialog.saving = false
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

.toolbar {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
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
}
</style>
