<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useUserStore } from '../stores/user'
import { adminApi, type AdminUser, type CreateUserRequest } from '../api/admin'
import { parseBatchUsers } from '../utils/batchUsers'
import { confirmAction, notify } from '../composables/useUiFeedback'
import AppPageHeader from '../components/ui/AppPageHeader.vue'
import AppModal from '../components/ui/AppModal.vue'
import MacroAnalyticsDashboard from '../components/dashboard/MacroAnalyticsDashboard.vue'

const userStore = useUserStore()
const isSuperAdmin = computed(() => userStore.profile.role === 'admin')

const showAddPwd = ref(false)
const showOwnPwd = ref(false)
const showResetPwdState = ref(false)

// ---- 用户列表 ----
const users = ref<AdminUser[]>([])
const knownClasses = ref<string[]>([])
const loading = ref(false)
const errorMsg = ref('')
const userSearch = ref('')
const roleFilter = ref('')
const statusFilter = ref('')
const classFilter = ref('')
const sortKey = ref<'name' | 'username' | 'class' | 'role'>('name')
const page = ref(1)
const pageSize = ref(20)
const totalUsers = ref(0)
const selectedUserIds = ref<string[]>([])
const bulkAction = ref<'freeze' | 'unfreeze' | 'reset_password' | 'assign_class'>('freeze')
const bulkClass = ref('')
const bulkWorking = ref(false)
const bulkErrors = ref<string[]>([])
const filteredUsers = computed(() => users.value)
const pageCount = computed(() => Math.max(1, Math.ceil(totalUsers.value / pageSize.value)))
const pagedUsers = computed(() => users.value)
const pageIds = computed(() => pagedUsers.value.map(user => user.id))
const allPageSelected = computed(() => pageIds.value.length > 0 && pageIds.value.every(id => selectedUserIds.value.includes(id)))

let searchTimer: ReturnType<typeof setTimeout> | null = null
watch([userSearch, roleFilter, statusFilter, classFilter, sortKey, pageSize], () => {
  page.value = 1
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => void loadUsers(), 300)
})
watch(page, () => void loadUsers())
watch(pageCount, count => { if (page.value > count) page.value = count })

function togglePageSelection() {
  if (allPageSelected.value) {
    selectedUserIds.value = selectedUserIds.value.filter(id => !pageIds.value.includes(id))
  } else {
    selectedUserIds.value = [...new Set([...selectedUserIds.value, ...pageIds.value])]
  }
}

async function applyBulkAction() {
  if (!selectedUserIds.value.length) return
  if (bulkAction.value === 'assign_class' && !bulkClass.value.trim()) {
    notify('请先填写要分配的班级', 'warning')
    return
  }
  const labels = { freeze: '冻结', unfreeze: '解冻', reset_password: '重置默认密码', assign_class: '分配班级' }
  const confirmed = await confirmAction({
    title: `批量${labels[bulkAction.value]}`,
    message: `将对所选 ${selectedUserIds.value.length} 个账号执行“${labels[bulkAction.value]}”，是否继续？`,
    confirmText: '确认执行',
    tone: bulkAction.value === 'freeze' ? 'warning' : 'primary'
  })
  if (!confirmed) return
  bulkWorking.value = true
  bulkErrors.value = []
  try {
    const result = (await adminApi.bulkUserAction({
      user_ids: selectedUserIds.value,
      action: bulkAction.value,
      class_group: bulkClass.value.trim() || undefined
    })).data
    bulkErrors.value = result.errors
    notify(`已处理 ${result.processed} 个账号${result.skipped ? `，跳过 ${result.skipped} 个` : ''}`, result.skipped ? 'warning' : 'success')
    selectedUserIds.value = []
    await loadUsers()
  } catch (error: unknown) {
    notify(error instanceof Error ? error.message : '批量操作失败', 'danger')
  } finally {
    bulkWorking.value = false
  }
}

async function loadUsers() {
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await adminApi.listUsers({
      page: page.value,
      page_size: pageSize.value,
      search: userSearch.value.trim(),
      role: roleFilter.value,
      account_status: statusFilter.value,
      class_group: classFilter.value,
      sort_by: sortKey.value
    })
    users.value = res.data
    totalUsers.value = Number(res.headers['x-total-count'] ?? res.data.length)
  } catch (e: unknown) {
    errorMsg.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

// ---- 新增/编辑表单 ----
const showAddModal = ref(false)
const addForm = ref<CreateUserRequest>({
  username: '',
  password: '123456',
  name: '',
  role: 'student',
  class_group: '',
  managed_classes: ''
})
const addError = ref('')

async function handleAddUser() {
  if (!addForm.value.username || !addForm.value.name) {
    addError.value = '账号和姓名不能为空'
    return
  }
  try {
    await adminApi.createUser({
      ...addForm.value,
      password: addForm.value.password || '123456',
      class_group: addForm.value.role === 'student' ? addForm.value.class_group : null,
      managed_classes: addForm.value.role === 'teacher' ? addForm.value.managed_classes : null
    })
    showAddModal.value = false
    addForm.value = {
      username: '',
      password: '123456',
      name: '',
      role: 'student',
      class_group: '',
      managed_classes: ''
    }
    addError.value = ''
    await loadUsers()
  } catch (e: unknown) {
    addError.value = e instanceof Error ? e.message : '创建失败'
  }
}

// ---- 批量新增 ----
const batchText = ref('')
const batchError = ref('')
const batchResult = ref('')
const batchSubmitting = ref(false)
const showBatchModal = ref(false)

function openBatchModal() {
  batchError.value = ''
  batchResult.value = ''
  showBatchModal.value = true
}

async function handleBatchAdd() {
  batchError.value = ''
  batchResult.value = ''
  const parsed = parseBatchUsers(batchText.value)
  if (parsed.errors.length > 0) {
    batchError.value = parsed.errors.join('；')
    return
  }
  if (parsed.users.length === 0) {
    batchError.value = '请输入至少一行有效数据'
    return
  }
  batchSubmitting.value = true
  try {
    const response = await adminApi.batchCreateUsers({ users: parsed.users })
    const result = response.data
    batchResult.value = result.message
    if (result.errors.length > 0) {
      batchError.value = result.errors.join('；')
    } else {
      showBatchModal.value = false
      batchText.value = ''
    }
    await loadUsers()
  } catch (e: unknown) {
    batchError.value = e instanceof Error ? e.message : '批量创建失败'
  } finally {
    batchSubmitting.value = false
  }
}

async function loadBatchFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  batchError.value = ''
  batchResult.value = ''
  try {
    batchText.value = await file.text()
  } catch {
    batchError.value = '文件读取失败，请使用 UTF-8 编码的 CSV 或 TXT 文件'
  } finally {
    input.value = ''
  }
}

function downloadBatchTemplate() {
  const content = [
    '账号,姓名,角色,班级/负责班级',
    '2026001,张三,student,2026级1班',
    '2026002,李四,学生,',
    't001,王老师,teacher,2026级1班|2026级2班'
  ].join('\r\n')
  const url = URL.createObjectURL(
    new Blob([`\uFEFF${content}`], { type: 'text/csv;charset=utf-8' })
  )
  const link = document.createElement('a')
  link.href = url
  link.download = '用户批量导入模板.csv'
  link.click()
  URL.revokeObjectURL(url)
}

// ---- 操作 ----
async function toggleStatus(user: AdminUser) {
  const action = user.is_active ? '冻结' : '解冻'
  const confirmed = await confirmAction({
    title: `${action}用户`,
    message: `确定要${action}“${user.name}”（${user.username}）吗？`,
    confirmText: `确认${action}`,
    tone: user.is_active ? 'warning' : 'success'
  })
  if (!confirmed) return
  try {
    await adminApi.toggleStatus(user.id)
    await loadUsers()
    notify(`用户“${user.name}”已${action}`, 'success')
  } catch (e: unknown) {
    notify(e instanceof Error ? e.message : `${action}失败`, 'danger')
  }
}

// ---- 为未分班学生或未设置范围的教师分配班级 ----
const showClassModal = ref(false)
const classTarget = ref<AdminUser | null>(null)
const assignedClass = ref('')
const classError = ref('')
const assigningClass = ref(false)

function openClassAssignment(user: AdminUser) {
  classTarget.value = user
  assignedClass.value = ''
  classError.value = ''
  showClassModal.value = true
}

function chooseExistingClass(className: string) {
  assignedClass.value = className
  classError.value = ''
}

async function confirmClassAssignment() {
  const target = classTarget.value
  const classGroup = assignedClass.value.trim()
  if (!target) return
  if (!classGroup) {
    classError.value = '请输入或选择班级'
    return
  }

  assigningClass.value = true
  classError.value = ''
  try {
    const response = await adminApi.assignUserClass(target.id, classGroup)
    const index = users.value.findIndex(user => user.id === target.id)
    if (index >= 0) users.value[index] = response.data
    showClassModal.value = false
    classTarget.value = null
    assignedClass.value = ''
  } catch (e: unknown) {
    classError.value = e instanceof Error ? e.message : '班级分配失败'
  } finally {
    assigningClass.value = false
  }
}

// ---- 重置密码（模态弹窗） ----
const showResetModal = ref(false)
const resetTarget = ref<AdminUser | null>(null)
const resetNewPwd = ref('123456')
const resetError = ref('')

function openResetPwd(user: AdminUser) {
  resetTarget.value = user
  resetNewPwd.value = '123456'
  resetError.value = ''
  showResetModal.value = true
}

async function confirmResetPwd() {
  if (!resetTarget.value) return
  const target = resetTarget.value
  const pwd = resetNewPwd.value.trim()
  if (pwd.length < 6) { resetError.value = '密码至少需要6位'; return }
  try {
    await adminApi.resetPassword(target.id, pwd)
    showResetModal.value = false
    resetTarget.value = null
    notify(`${target.name} 的密码已重置`, 'success')
  } catch (e: unknown) {
    resetError.value = e instanceof Error ? e.message : '重置失败，请检查权限'
  }
}

async function deleteUser(user: AdminUser) {
  const confirmed = await confirmAction({
    title: '删除用户',
    message: `确定删除“${user.name}”（${user.username}）吗？\n该操作不可撤销。`,
    confirmText: '确认删除',
    tone: 'danger'
  })
  if (!confirmed) return
  try {
    await adminApi.deleteUser(user.id)
    await loadUsers()
    notify(`用户“${user.name}”已删除`, 'success')
  } catch (e: unknown) {
    notify(e instanceof Error ? e.message : '删除失败', 'danger')
  }
}

// ---- 修改自己密码 ----
const showPwdModal = ref(false)
const newPassword = ref('')
const pwdError = ref('')

const pwdStrength = computed(() => {
  const p = newPassword.value
  if (!p) return { score: 0, label: '', class: '', textClass: '' }
  let score = 0
  if (p.length >= 6) score++
  if (/[a-zA-Z]/.test(p) && /\d/.test(p)) score++
  if (/[^a-zA-Z0-9]/.test(p) || p.length >= 10) score++
  if (score <= 1) return { score: 1, label: '弱 (建议包含字母与数字)', class: 'strength-weak', textClass: 'text-weak' }
  if (score === 2) return { score: 2, label: '中 (可加入特殊字符)', class: 'strength-medium', textClass: 'text-medium' }
  return { score: 3, label: '强', class: 'strength-strong', textClass: 'text-strong' }
})

async function changeOwnPwd() {
  if (newPassword.value.length < 6) { pwdError.value = '至少6位'; return }
  try {
    await adminApi.changeOwnPassword(newPassword.value)
    showPwdModal.value = false
    newPassword.value = ''
    pwdError.value = ''
    notify('密码修改成功', 'success')
  } catch (e: unknown) {
    pwdError.value = e instanceof Error ? e.message : '修改失败'
  }
}

onMounted(async () => {
  const classes = await adminApi.listUserClasses().catch(() => null)
  if (classes) knownClasses.value = classes.data
  await loadUsers()
})

// ---- 角色/状态标签样式 ----
function roleClass(r: string) { return r === 'admin' ? 'badge bg-danger' : r === 'teacher' ? 'badge bg-warning text-dark' : 'badge bg-info text-dark' }
function roleLabel(r: string) { return r === 'admin' ? '管理员' : r === 'teacher' ? '教师' : '学生' }
function userClassLabel(user: AdminUser) {
  if (user.role === 'teacher') return user.managed_classes || '未分配'
  if (user.role === 'student') return user.class_group || '未分班'
  return '-'
}
</script>

<template>
  <div class="admin-page">
    <!-- 工具栏 -->
    <AppPageHeader
      eyebrow="系统管理"
      title="用户与权限"
      icon="bi-people-fill"
      :description="userSearch.trim() ? `找到 ${totalUsers} 个匹配账号` : `管理学生、教师和管理员账号，共 ${totalUsers} 个账号`"
      compact
    >
      <template #actions>
        <button class="btn btn-sm btn-outline-secondary" @click="showPwdModal = true">
          <i class="bi bi-key me-1"></i>修改密码
        </button>
        <button class="btn btn-sm btn-outline-primary" @click="openBatchModal">
          <i class="bi bi-upload me-1"></i>批量导入
        </button>
        <button class="btn btn-sm btn-primary" @click="showAddModal = true">
          <i class="bi bi-plus-lg me-1"></i>新增用户
        </button>
      </template>
    </AppPageHeader>

    <!-- 错误提示 -->
    <div v-if="errorMsg" class="alert alert-danger py-2">{{ errorMsg }}</div>
    <div v-if="batchResult && !showBatchModal" class="alert alert-success py-2">
      {{ batchResult }}
    </div>

    <div class="user-list-card">
      <div class="user-list-toolbar">
        <div class="user-search">
          <i class="bi bi-search user-search-icon" aria-hidden="true"></i>
          <input
            v-model="userSearch"
            type="search"
            class="form-control"
            placeholder="输入姓名或账号查找用户"
            aria-label="按姓名或账号查找用户"
          />
          <button
            v-if="userSearch"
            class="user-search-clear"
            type="button"
            aria-label="清除查找内容"
            title="清除"
            @click="userSearch = ''"
          >
            <i class="bi bi-x-lg"></i>
          </button>
        </div>
        <span class="user-list-count">
          <i class="bi bi-people me-1"></i>{{ filteredUsers.length }} 人
        </span>
      </div>

      <div class="user-filter-row">
        <select v-model="roleFilter" class="form-select form-select-sm" aria-label="按角色筛选">
          <option value="">全部角色</option><option value="student">学生</option><option value="teacher">教师</option><option value="admin">管理员</option>
        </select>
        <select v-model="classFilter" class="form-select form-select-sm" aria-label="按班级筛选">
          <option value="">全部班级</option><option v-for="item in knownClasses" :key="item" :value="item">{{ item }}</option>
        </select>
        <select v-model="statusFilter" class="form-select form-select-sm" aria-label="按状态筛选">
          <option value="">全部状态</option><option value="active">正常</option><option value="frozen">已冻结</option>
        </select>
        <select v-model="sortKey" class="form-select form-select-sm" aria-label="用户排序方式">
          <option value="name">按姓名排序</option><option value="username">按账号排序</option><option value="class">按班级排序</option><option value="role">按角色排序</option>
        </select>
      </div>

      <div v-if="isSuperAdmin && selectedUserIds.length" class="bulk-action-bar">
        <strong>已选 {{ selectedUserIds.length }} 人</strong>
        <select v-model="bulkAction" class="form-select form-select-sm">
          <option value="freeze">冻结账号</option><option value="unfreeze">解冻账号</option>
          <option value="reset_password">重置密码为 123456</option><option value="assign_class">分配/调整班级</option>
        </select>
        <input v-if="bulkAction === 'assign_class'" v-model="bulkClass" class="form-control form-control-sm" list="bulk-known-classes" placeholder="输入班级" />
        <datalist id="bulk-known-classes"><option v-for="item in knownClasses" :key="item" :value="item" /></datalist>
        <button class="btn btn-sm btn-primary" :disabled="bulkWorking" @click="applyBulkAction">
          <span v-if="bulkWorking" class="spinner-border spinner-border-sm me-1" />执行
        </button>
        <button class="btn btn-sm btn-light" @click="selectedUserIds = []">取消选择</button>
      </div>
      <div v-if="bulkErrors.length" class="alert alert-warning m-3 mt-0 py-2 small">
        <strong>以下账号未处理：</strong>{{ bulkErrors.slice(0, 5).join('；') }}<span v-if="bulkErrors.length > 5"> 等 {{ bulkErrors.length }} 条</span>
      </div>

      <!-- 用户表格 -->
      <div class="table-responsive">
        <table class="table table-hover align-middle mb-0">
        <thead class="table-light">
          <tr>
            <th v-if="isSuperAdmin" class="selection-cell"><input type="checkbox" class="form-check-input" :checked="allPageSelected" aria-label="选择本页用户" @change="togglePageSelection" /></th>
            <th>账号</th><th>姓名</th><th>角色</th><th>班级/负责班级</th><th>状态</th><th class="text-end">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading"><td :colspan="isSuperAdmin ? 7 : 6" class="text-center text-muted py-4">加载中…</td></tr>
          <tr v-else-if="users.length === 0 && userSearch.trim()">
            <td :colspan="isSuperAdmin ? 7 : 6" class="empty-users">
              <i class="bi bi-search"></i>
              <span>没有找到与“{{ userSearch.trim() }}”匹配的用户</span>
              <button class="btn btn-sm btn-outline-primary" type="button" @click="userSearch = ''">
                清除查找
              </button>
            </td>
          </tr>
          <tr v-else-if="users.length === 0">
            <td :colspan="isSuperAdmin ? 7 : 6" class="empty-users">
              <i class="bi bi-person-x"></i>
              <span>暂无用户</span>
            </td>
          </tr>
          <tr v-for="u in pagedUsers" :key="u.id" :class="{ 'table-secondary': !u.is_active }">
            <td v-if="isSuperAdmin" class="selection-cell" data-label="选择"><input v-model="selectedUserIds" type="checkbox" class="form-check-input" :value="u.id" :aria-label="`选择 ${u.name}`" /></td>
            <td data-label="账号"><code>{{ u.username }}</code></td>
            <td data-label="姓名">{{ u.name }}</td>
            <td data-label="角色"><span :class="roleClass(u.role)">{{ roleLabel(u.role) }}</span></td>
            <td data-label="班级/负责班级">
              <div class="class-cell">
                <span :class="{ 'text-muted': (u.role === 'student' && !u.class_group) || (u.role === 'teacher' && !u.managed_classes) }">
                  {{ userClassLabel(u) }}
                </span>
                <button
                  v-if="isSuperAdmin && ((u.role === 'student' && !u.class_group) || (u.role === 'teacher' && !u.managed_classes))"
                  class="btn btn-sm btn-outline-primary"
                  type="button"
                  @click="openClassAssignment(u)"
                >
                  <i class="bi bi-diagram-3 me-1"></i>{{ u.role === 'teacher' ? '设置负责班级' : '分配班级' }}
                </button>
              </div>
            </td>
            <td data-label="状态">
              <span :class="u.is_active ? 'text-success' : 'text-danger'">
                {{ u.is_active ? '正常' : '已冻结' }}
              </span>
            </td>
            <td class="text-end" data-label="操作">
              <div class="user-row-actions">
                <button
                  class="btn btn-sm action-btn"
                  :class="u.is_active ? 'btn-outline-warning' : 'btn-outline-success'"
                  type="button"
                  @click="toggleStatus(u)"
                >
                  <i class="bi me-1" :class="u.is_active ? 'bi-lock' : 'bi-unlock'"></i>
                  {{ u.is_active ? '冻结' : '解冻' }}
                </button>
                <button class="btn btn-sm btn-outline-secondary action-btn" type="button" @click="openResetPwd(u)">
                  <i class="bi bi-key me-1"></i>重置密码
                </button>
                <button
                  v-if="isSuperAdmin"
                  class="btn btn-sm btn-outline-danger action-btn"
                  type="button"
                  @click="deleteUser(u)"
                >
                  <i class="bi bi-trash3 me-1"></i>删除
                </button>
              </div>
            </td>
          </tr>
        </tbody>
        </table>
      </div>
      <div v-if="totalUsers > pageSize" class="list-pagination">
        <span>第 {{ page }} / {{ pageCount }} 页 · 共 {{ totalUsers }} 个账号</span>
        <label class="d-flex align-items-center gap-2">每页
          <select v-model.number="pageSize" class="form-select form-select-sm"><option :value="20">20</option><option :value="50">50</option><option :value="100">100</option></select>
        </label>
        <div class="btn-group btn-group-sm">
          <button class="btn btn-outline-secondary" :disabled="page <= 1" @click="page--">上一页</button>
          <button class="btn btn-outline-secondary" :disabled="page >= pageCount" @click="page++">下一页</button>
        </div>
      </div>
    </div>

    <!-- ===== 新增用户弹窗 ===== -->
    <AppModal
      :open="showAddModal"
      title="新增用户"
      icon="bi-person-plus"
      @close="showAddModal = false"
    >
      <div class="mb-2">
        <label class="form-label-sm" for="add-username">账号</label>
        <input id="add-username" v-model="addForm.username" class="form-control form-control-sm" placeholder="学号/教工号" />
      </div>
      <div class="mb-2">
        <label class="form-label-sm" for="add-password">密码</label>
        <div class="input-with-action">
          <input
            id="add-password"
            v-model="addForm.password"
            :type="showAddPwd ? 'text' : 'password'"
            class="form-control form-control-sm"
            placeholder="默认 123456"
          />
          <button
            v-if="addForm.password"
            type="button"
            class="input-action-btn"
            :aria-label="showAddPwd ? '隐藏密码' : '显示密码'"
            @click="showAddPwd = !showAddPwd"
          >
            <i class="bi" :class="showAddPwd ? 'bi-eye-slash-fill' : 'bi-eye-fill'"></i>
          </button>
        </div>
      </div>
      <div class="mb-2">
        <label class="form-label-sm" for="add-name">姓名</label>
        <input id="add-name" v-model="addForm.name" class="form-control form-control-sm" placeholder="真实姓名" />
      </div>
      <div class="mb-2">
        <label class="form-label-sm" for="add-role">角色</label>
        <select id="add-role" v-model="addForm.role" class="form-select form-select-sm">
          <option value="student">学生</option><option value="teacher">教师</option><option value="admin">管理员</option>
        </select>
      </div>
      <div v-if="addForm.role === 'student'" class="mb-2">
        <label class="form-label-sm" for="add-class-group">所属班级（选填）</label>
        <input id="add-class-group" v-model="addForm.class_group" class="form-control form-control-sm" placeholder="可留空，创建后再分配" />
        <div class="form-text">未填写时将显示为“未分班”，可在用户列表中单独或批量分配。</div>
      </div>
      <div v-else-if="addForm.role === 'teacher'" class="mb-2">
        <label class="form-label-sm" for="add-managed-classes">负责班级（选填）</label>
        <input id="add-managed-classes" v-model="addForm.managed_classes" class="form-control form-control-sm" placeholder="可留空；多个班级用 | 或 ；分隔" />
        <div class="form-text">未填写时教师暂不具备班级数据范围，可在用户列表中后续设置。</div>
      </div>
      <div v-if="addError" class="text-danger small mb-2">{{ addError }}</div>
      <template #footer>
        <div class="d-flex gap-2 justify-content-end w-100">
          <button class="btn btn-sm btn-secondary" @click="showAddModal = false">取消</button>
          <button class="btn btn-sm btn-primary" @click="handleAddUser">确认创建</button>
        </div>
      </template>
    </AppModal>

    <!-- ===== 批量导入弹窗 ===== -->
    <AppModal
      :open="showBatchModal"
      title="批量导入用户"
      icon="bi-upload"
      max-width="680px"
      @close="showBatchModal = false"
    >
      <p class="text-muted small mb-2">
        每行格式：<code>账号,姓名,角色,班级/负责班级</code>。学生班级和教师负责班级均可留空并在导入后分配；
        多个负责班级用 <code>|</code> 或 <code>；</code> 分隔。默认密码为 123456。
      </p>
      <div class="d-flex flex-wrap gap-2 mb-2">
        <label class="btn btn-sm btn-outline-secondary mb-0">
          <i class="bi bi-file-earmark-arrow-up me-1"></i>选择 CSV/TXT
          <input class="visually-hidden" type="file" accept=".csv,.txt,text/csv,text/plain" @change="loadBatchFile" />
        </label>
        <button class="btn btn-sm btn-outline-secondary" type="button" @click="downloadBatchTemplate">
          <i class="bi bi-download me-1"></i>下载模板
        </button>
      </div>
      <label class="visually-hidden" for="batch-user-data">批量用户数据</label>
      <textarea
        id="batch-user-data"
        v-model="batchText"
        class="form-control mb-2"
        rows="9"
        placeholder="2026001,张三,student,2026级1班&#10;2026002,李四,学生,&#10;t001,王老师,teacher,2026级1班|2026级2班"
      ></textarea>
      <div v-if="batchResult" class="alert alert-success small py-2 mb-2">{{ batchResult }}</div>
      <div v-if="batchError" class="text-danger small mb-2">{{ batchError }}</div>
      <template #footer>
        <div class="d-flex gap-2 justify-content-end w-100">
          <button class="btn btn-sm btn-secondary" :disabled="batchSubmitting" @click="showBatchModal = false">取消</button>
          <button class="btn btn-sm btn-primary" :disabled="batchSubmitting" @click="handleBatchAdd">
            <span v-if="batchSubmitting" class="spinner-border spinner-border-sm me-1"></span>
            导入
          </button>
        </div>
      </template>
    </AppModal>

    <!-- ===== 学生/教师补充分班信息弹窗 ===== -->
    <AppModal
      :open="showClassModal"
      :title="classTarget?.role === 'teacher' ? '设置负责班级' : '分配班级'"
      icon="bi-diagram-3"
      @close="showClassModal = false"
    >
      <p class="text-muted small">
        {{ classTarget?.role === 'teacher' ? '教师' : '学生' }}：<strong>{{ classTarget?.name }}</strong>（{{ classTarget?.username }}）
      </p>
      <div v-if="knownClasses.length" class="mb-3">
        <label class="form-label-sm">选择已有班级</label>
        <div class="class-option-list" role="listbox" aria-label="已有班级">
          <button
            v-for="className in knownClasses"
            :key="className"
            class="class-option"
            :class="{ active: assignedClass === className }"
            type="button"
            role="option"
            :aria-selected="assignedClass === className"
            @click="chooseExistingClass(className)"
          >
            <span class="class-option-icon">
              <i class="bi bi-people-fill"></i>
            </span>
            <span class="class-option-name">{{ className }}</span>
            <i
              class="bi ms-auto"
              :class="assignedClass === className ? 'bi-check-circle-fill' : 'bi-chevron-right'"
            ></i>
          </button>
        </div>
      </div>
      <div v-if="knownClasses.length" class="class-divider">
        <span>或输入新班级</span>
      </div>
      <div class="mb-2">
        <label class="form-label-sm" for="assigned-class-name">
          {{ knownClasses.length ? '新班级名称' : (classTarget?.role === 'teacher' ? '负责班级' : '所属班级') }}
        </label>
        <input
          id="assigned-class-name"
          v-model="assignedClass"
          class="form-control form-control-sm"
          maxlength="64"
          :placeholder="knownClasses.length ? '例如：2026级3班' : '输入班级名称'"
          @keyup.enter="confirmClassAssignment"
        />
        <div class="form-text">分配后将用于教师数据权限、班级统计和任务管理。</div>
      </div>
      <div v-if="classError" class="text-danger small mb-2">{{ classError }}</div>
      <template #footer>
        <div class="d-flex gap-2 justify-content-end w-100">
          <button
            class="btn btn-sm btn-secondary"
            :disabled="assigningClass"
            @click="showClassModal = false"
          >
            取消
          </button>
          <button
            class="btn btn-sm btn-primary"
            :disabled="assigningClass || !assignedClass.trim()"
            @click="confirmClassAssignment"
          >
            <span v-if="assigningClass" class="spinner-border spinner-border-sm me-1"></span>
            {{ classTarget?.role === 'teacher' ? '确认设置' : '确认分配' }}
          </button>
        </div>
      </template>
    </AppModal>

    <!-- ===== 修改密码弹窗 ===== -->
    <AppModal
      :open="showPwdModal"
      title="修改密码"
      icon="bi-key"
      @close="showPwdModal = false"
    >
      <p class="text-muted small">当前用户：{{ userStore.profile.name }}</p>
      <div class="mb-3">
        <label class="form-label-sm" for="own-new-password">新密码</label>
        <div class="input-with-action">
          <input
            id="own-new-password"
            v-model="newPassword"
            :type="showOwnPwd ? 'text' : 'password'"
            class="form-control form-control-sm"
            placeholder="至少6位"
          />
          <button
            v-if="newPassword"
            type="button"
            class="input-action-btn"
            :aria-label="showOwnPwd ? '隐藏密码' : '显示密码'"
            @click="showOwnPwd = !showOwnPwd"
          >
            <i class="bi" :class="showOwnPwd ? 'bi-eye-slash-fill' : 'bi-eye-fill'"></i>
          </button>
        </div>
        <div v-if="newPassword" class="password-strength-wrap">
          <div class="password-strength-bar">
            <div class="password-strength-fill" :class="pwdStrength.class"></div>
          </div>
          <div class="password-strength-hint">
            <span>密码强度</span>
            <strong :class="pwdStrength.textClass">{{ pwdStrength.label }}</strong>
          </div>
        </div>
      </div>
      <div v-if="pwdError" class="text-danger small mb-2">{{ pwdError }}</div>
      <template #footer>
        <div class="d-flex gap-2 justify-content-end w-100">
          <button class="btn btn-sm btn-secondary" @click="showPwdModal = false">取消</button>
          <button class="btn btn-sm btn-primary" @click="changeOwnPwd">确认</button>
        </div>
      </template>
    </AppModal>

    <!-- ===== 重置密码弹窗 ===== -->
    <AppModal
      :open="showResetModal"
      title="重置密码"
      icon="bi-arrow-repeat"
      @close="showResetModal = false"
    >
      <p class="text-muted small">用户：<strong>{{ resetTarget?.name }}</strong>（{{ resetTarget?.username }}）</p>
      <div class="mb-2">
        <label class="form-label-sm" for="reset-new-password">新密码</label>
        <div class="input-with-action">
          <input
            id="reset-new-password"
            v-model="resetNewPwd"
            :type="showResetPwdState ? 'text' : 'password'"
            class="form-control form-control-sm"
            placeholder="至少6位"
            @keyup.enter="confirmResetPwd"
          />
          <button
            v-if="resetNewPwd"
            type="button"
            class="input-action-btn"
            :aria-label="showResetPwdState ? '隐藏密码' : '显示密码'"
            @click="showResetPwdState = !showResetPwdState"
          >
            <i class="bi" :class="showResetPwdState ? 'bi-eye-slash-fill' : 'bi-eye-fill'"></i>
          </button>
        </div>
      </div>
      <div v-if="resetError" class="text-danger small mb-2">{{ resetError }}</div>
      <template #footer>
        <div class="d-flex gap-2 justify-content-end w-100">
          <button class="btn btn-sm btn-secondary" @click="showResetModal = false">取消</button>
          <button class="btn btn-sm btn-primary" @click="confirmResetPwd">确认重置</button>
        </div>
      </template>
    </AppModal>
  </div>
</template>

<style scoped>
.admin-page { max-width: 1200px; margin: 0 auto; }

.admin-toolbar-actions .btn {
  min-height: 36px;
  padding-inline: .85rem;
  border-radius: 9px;
  font-weight: 600;
}
.user-list-card {
  position: relative;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: linear-gradient(150deg, rgba(75, 73, 172, .035), transparent 38%), var(--color-surface);
  box-shadow: var(--shadow-sm), inset 0 1px rgba(255, 255, 255, .45);
}
.user-list-card::before {
  content: '';
  position: absolute;
  z-index: 3;
  top: 0;
  right: 0;
  left: 0;
  height: 2px;
  pointer-events: none;
  background: linear-gradient(90deg, var(--color-primary), var(--color-info), transparent 86%);
  opacity: .65;
}
.user-list-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem;
  border-bottom: 1px solid var(--color-border);
  background: linear-gradient(100deg, var(--color-primary-soft), var(--color-surface-subtle) 48%, var(--color-surface));
}

.user-filter-row,
.bulk-action-bar {
  display: flex;
  align-items: center;
  gap: .65rem;
  padding: .75rem 1rem;
  border-top: 1px solid var(--color-border);
}
.user-filter-row .form-select { width: min(180px, 100%); }
.bulk-action-bar { background: var(--color-surface-subtle); }
.bulk-action-bar strong { white-space: nowrap; color: var(--color-primary); }
.bulk-action-bar .form-select { max-width: 220px; }
.bulk-action-bar .form-control { max-width: 200px; }
.selection-cell { width: 44px; text-align: center; }
.list-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: .8rem 1rem;
  border-top: 1px solid var(--color-border);
  color: var(--color-text-muted);
  font-size: .82rem;
}
.user-list-card .table-responsive { max-height: 68vh; }
.user-list-card thead th { position: sticky; top: 0; z-index: 2; }
.user-search {
  position: relative;
  width: min(100%, 420px);
}
.user-search .form-control {
  height: 42px;
  padding-left: 2.55rem;
  padding-right: 2.5rem;
  border-color: var(--color-border);
  border-radius: 11px;
  background: var(--color-surface);
  color: var(--color-text);
}
.user-search .form-control:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 .22rem var(--focus-ring);
}
.user-search-icon {
  position: absolute;
  top: 50%;
  left: .9rem;
  z-index: 2;
  color: var(--color-text-muted);
  transform: translateY(-50%);
  pointer-events: none;
}
.user-search-clear {
  position: absolute;
  top: 50%;
  right: .65rem;
  z-index: 2;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  padding: 0;
  border: 0;
  border-radius: 8px;
  color: var(--color-text-muted);
  background: transparent;
  transform: translateY(-50%);
}
.user-search-clear:hover {
  color: var(--color-primary);
  background: var(--color-primary-soft);
}
.user-list-count {
  flex: 0 0 auto;
  padding: .4rem .65rem;
  border-radius: 999px;
  color: var(--color-primary);
  background: var(--color-primary-soft);
  font-size: .78rem;
  font-weight: 600;
}
.user-list-card thead th {
  padding-block: .8rem;
  border-bottom-color: var(--color-border);
  color: var(--color-text-secondary);
  font-size: .76rem;
  font-weight: 700;
  white-space: nowrap;
}
.user-list-card tbody td { padding-block: .8rem; }
.user-row-actions {
  display: flex;
  justify-content: flex-end;
  gap: .4rem;
  flex-wrap: wrap;
}
.action-btn {
  min-height: 36px;
  border-radius: 8px;
  font-size: .75rem;
  font-weight: 600;
  white-space: nowrap;
}
.empty-users {
  height: 180px;
  color: var(--color-text-muted) !important;
  text-align: center;
}
.empty-users > i {
  display: block;
  margin-bottom: .5rem;
  font-size: 1.7rem;
}
.empty-users > span { display: block; margin-bottom: .65rem; }
.class-cell {
  display: flex;
  align-items: center;
  gap: .5rem;
  flex-wrap: wrap;
}
.class-cell .btn { white-space: nowrap; }
.class-option-list {
  display: grid;
  gap: .5rem;
  max-height: 220px;
  padding: .25rem;
  overflow-y: auto;
  border-radius: 12px;
  background: var(--color-surface-subtle);
}
.class-option {
  display: flex;
  align-items: center;
  gap: .65rem;
  width: 100%;
  padding: .7rem .8rem;
  border: 1px solid var(--color-border);
  border-radius: 10px;
  color: var(--color-text);
  background: var(--color-surface);
  text-align: left;
  transition: border-color .18s ease, box-shadow .18s ease, background .18s ease;
}
.class-option:hover {
  border-color: var(--color-primary-hover);
  background: var(--color-primary-soft);
}
.class-option.active {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-soft);
  box-shadow: 0 0 0 2px var(--focus-ring);
}
.class-option-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  border-radius: 999px;
  color: var(--color-primary);
  background: var(--color-primary-soft);
}
.class-option-name {
  min-width: 0;
  overflow-wrap: anywhere;
  font-size: .875rem;
  font-weight: 600;
}
.class-divider {
  display: flex;
  align-items: center;
  gap: .75rem;
  margin: .25rem 0 .85rem;
  color: var(--color-text-muted);
  font-size: .75rem;
}
.class-divider::before,
.class-divider::after {
  content: '';
  height: 1px;
  flex: 1;
  background: var(--color-border);
}
@media (max-width: 575.98px) {
  .admin-toolbar-actions { width: 100%; flex-wrap: wrap; }
  .admin-toolbar-actions .btn { flex: 1 1 calc(50% - .5rem); min-height: 40px; }
  .user-list-toolbar { align-items: stretch; flex-direction: column; }
  .user-filter-row,
  .bulk-action-bar { align-items: stretch; flex-direction: column; }
  .user-filter-row .form-select,
  .bulk-action-bar .form-select,
  .bulk-action-bar .form-control,
  .bulk-action-bar .btn { width: 100%; max-width: none; min-height: 42px; }
  .user-search { width: 100%; }
  .user-list-count { align-self: flex-start; }
  .user-list-card .table-responsive { overflow: visible; }
  .user-list-card .table-responsive::before { display: none; }
  .user-list-card table { min-width: 0; }
  .user-list-card thead { display: none; }
  .user-list-card tbody { display: grid; gap: .75rem; padding: .75rem; }
  .user-list-card tbody tr {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: .75rem 1rem;
    padding: .9rem;
    border: 1px solid var(--color-border);
    border-radius: 12px;
    background: var(--color-surface);
  }
  .user-list-card tbody td {
    display: block;
    min-width: 0;
    padding: 0;
    border: 0;
    text-align: left !important;
  }
  .user-list-card tbody td[data-label]::before {
    content: attr(data-label);
    display: block;
    margin-bottom: .25rem;
    color: var(--color-text-muted);
    font-size: .68rem;
    font-weight: 700;
  }
  .user-list-card tbody td[data-label="班级/负责班级"],
  .user-list-card tbody td[data-label="操作"] { grid-column: 1 / -1; }
  .user-list-card tbody td[colspan] { grid-column: 1 / -1; }
  .user-row-actions { justify-content: flex-start; min-width: 0; }
  .action-btn { min-height: 40px; }
}
.batch-modal { max-width: 680px; }
</style>
