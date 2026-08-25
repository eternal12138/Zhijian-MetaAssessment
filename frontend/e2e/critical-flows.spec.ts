import { expect, test, type Page } from '@playwright/test'

async function login(page: Page, username: 'student' | 'teacher' | 'admin') {
  await page.goto('/login')
  await page.locator('#login-username').fill(username)
  await page.locator('#login-password').fill('123456')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL(url => !url.pathname.endsWith('/login'))
  const deferButton = page.getByRole('button', { name: '暂不修改', exact: true })
  // The password reminder is loaded after the route transition. Give it a
  // short bounded window instead of checking visibility at a single instant.
  try {
    await deferButton.waitFor({ state: 'visible', timeout: 1_500 })
    await deferButton.click()
    await deferButton.waitFor({ state: 'hidden', timeout: 10_000 })
  } catch {
    // Accounts that already changed their password do not show the reminder.
  }
}

test('登录页 Logo 可进入太阳系彩蛋并控制模拟', async ({ page }) => {
  await page.goto('/login')
  await page.getByRole('button', { name: '进入太阳系模拟彩蛋' }).click()
  await expect(page).toHaveURL(/\/cosmos$/)
  await expect(page.getByRole('heading', { name: '太阳系轨道模拟' })).toBeVisible()
  await expect(page.locator('canvas[aria-label="动态太阳系轨道模拟"]')).toBeVisible()
  const pauseButton = page.getByRole('button', { name: /暂停模拟/ })
  await pauseButton.click()
  await expect(page.getByText('已暂停', { exact: true })).toBeVisible()
})

test('两个彩蛋在桌面、平板和手机视口下保持可用且不溢出', async ({ page }) => {
  const viewports = [
    { name: '桌面', width: 1440, height: 900 },
    { name: '平板', width: 820, height: 1180 },
    { name: '手机', width: 390, height: 844 }
  ]

  await page.goto('/login')
  await page.getByRole('button', { name: '进入太阳系模拟彩蛋' }).click()
  for (const viewport of viewports) {
    await page.setViewportSize(viewport)
    await expect(page.locator('.cosmos-controls')).toBeVisible()
    const cosmosOverflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(cosmosOverflow, `${viewport.name}太阳系页面发生横向溢出`).toBeLessThanOrEqual(1)
  }

  await login(page, 'student')
  const hero = page.locator('.planet-orbit-container').first()
  await expect(hero).toBeVisible()
  await hero.dblclick()
  const dialog = page.getByRole('dialog', { name: '滑动变祖器' })
  await expect(dialog).toBeVisible()

  for (const viewport of viewports) {
    await page.setViewportSize(viewport)
    await expect(dialog).toBeVisible()
    const box = await dialog.boundingBox()
    expect(box, `${viewport.name}校准器应位于可视区域`).not.toBeNull()
    expect(box!.x).toBeGreaterThanOrEqual(-1)
    expect(box!.y).toBeGreaterThanOrEqual(-1)
    expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width + 1)
    expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height + 1)
  }
})

test('学生只读取已发布报告，未发布运行显示处理进度', async ({ page }) => {
  let analysisRequests = 0
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().includes('/research/analysis/runs/')) {
      analysisRequests += 1
    }
  })
  await login(page, 'student')
  await expect(page.getByText('已发布报告', { exact: true })).toBeVisible()
  await page.goto('/report?run=e2e-unpublished-run')
  await expect(page.getByText('报告正在处理中', { exact: true })).toBeVisible()
  expect(analysisRequests).toBe(0)
})

test('教师中心单个分区失败时保留其他工作区', async ({ page }) => {
  await page.route('**/api/research/analytics', route => route.abort())
  await login(page, 'teacher')
  await expect(page.getByText(/统计指标暂时加载失败/)).toBeVisible()
  await expect(page.getByText('任务顺序分配', { exact: true })).toBeVisible()
})

test('管理员用户列表使用服务端分页并可进入数据管理', async ({ page }) => {
  const usersRequest = page.waitForRequest(request =>
    request.url().includes('/api/admin/users?') && request.url().includes('page_size=20')
  )
  await login(page, 'admin')
  await page.goto('/users')
  await usersRequest
  await expect(page.getByText(/管理学生、教师和管理员账号/)).toBeVisible()
  await page.goto('/data-management')
  await expect(page.getByRole('heading', { name: /数据管理/ }).first()).toBeVisible()
})

test('测评设备检查显示实时波形并可发现本地恢复快照', async ({ page }) => {
  const run = {
    id: 'e2e-recovery-run',
    user_id: 'e2e-student-id',
    status: 'active',
    current_stage: 'device_check',
    protocol_version: 'e2e-v1',
    questionnaire_enabled: true,
    questionnaire_source: 'e2e',
    task_order_code: 'AB',
    order_assignment_id: null,
    consented_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    completed_at: null,
    sessions: [],
    questionnaire_answers: [],
    questionnaire_participant_name: null
  }
  const protocol = {
    version: 'e2e-v1',
    questionnaire_enabled: true,
    questionnaire_source: 'e2e',
    task_order_code: 'AB',
    order_source: 'active_run',
    tasks: [
      { id: 'task-a', title: '任务一', description: '', scenario: '任务一题干', estimated_minutes: 5, protocol_order: 1, stimulus_data: null },
      { id: 'task-b', title: '任务二', description: '', scenario: '任务二题干', estimated_minutes: 5, protocol_order: 2, stimulus_data: null }
    ],
    questionnaire_items: [],
    likert_labels: {},
    narration_assets: []
  }
  await login(page, 'student')
  await page.route('**/api/assessment/protocol', route => route.fulfill({ json: protocol }))
  await page.route('**/api/assessment/runs/current', route => route.fulfill({ json: run }))
  await page.goto('/assessment')
  await expect(page.getByRole('heading', { name: '设备检查' })).toBeVisible()
  await expect(page.getByRole('img', { name: '麦克风波形尚未开始' })).toBeVisible()

  await page.evaluate(async snapshot => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('Zhijian_Assessment_Offline_DB', 1)
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction('assessment_snapshots', 'readwrite')
      transaction.objectStore('assessment_snapshots').put(snapshot)
      transaction.oncomplete = () => resolve()
      transaction.onerror = () => reject(transaction.error)
    })
    db.close()
  }, {
    id: `${run.user_id}:${run.id}`,
    userId: run.user_id,
    runId: run.id,
    protocolId: protocol.version,
    currentPhase: 'device_check',
    currentTaskIndex: 0,
    practiceAnswer: '',
    practiceCompleted: false,
    questionnaireAnswers: {},
    participantName: '',
    activeSessionId: null,
    updatedAt: Date.now(),
    checksum: 'e2e',
    status: 'active'
  })
  await page.reload()
  await expect(page.getByRole('dialog', { name: '检测到未完成的测评' })).toBeVisible()
  await expect(page.getByRole('button', { name: '一键恢复测评' })).toBeVisible()
})
