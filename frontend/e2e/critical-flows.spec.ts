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

test('学生三维画像默认展示最新有效轮次并随历史选择更新', async ({ page }) => {
  const measurement = (
    runId: string,
    completedAt: string,
    monitoring: number | null,
    control: number | null,
    evaluation: number | null,
    available = true
  ) => ({
    id: `measurement-${runId}`, user_id: 'student', run_id: runId,
    task_ids: [`task-${runId}`], task_names: [`任务 ${runId}`],
    effective_dialogue_count: available ? 10 : 0,
    dimension_counts: {
      monitoring: monitoring === null ? 0 : monitoring * 10,
      control_debugging: control === null ? 0 : control * 10,
      evaluation: evaluation === null ? 0 : evaluation * 10
    },
    dimension_scores: {
      monitoring, control_debugging: control, evaluation
    },
    score_available: available, source: 'expert_consensus',
    data_version: `coding_batch:${runId}`, calculated_at: completedAt,
    completed_at: completedAt
  })
  await page.route('**/api/reports/metacognition-measurements**', route => route.fulfill({
    json: {
      items: [
        measurement('latest', '2026-08-27T10:00:00', 0.4, 0.3, 0.3),
        measurement('older', '2026-08-25T10:00:00', 0.2, 0.5, 0.1),
        measurement('empty', '2026-08-21T10:00:00', null, null, null, false)
      ],
      page: 1, page_size: 20, total: 3
    }
  }))

  await login(page, 'student')
  const card = page.locator('.macro-analytics-dashboard')
  const history = card.getByRole('combobox', { name: '选择历史测量轮次' })
  await expect(history).toHaveValue('latest')
  await expect(card.getByText('40.0%', { exact: false })).toBeVisible()
  await expect(card.getByText('4 / 10 条', { exact: true })).toBeVisible()

  await history.selectOption('older')
  await expect(card.getByText('20.0%', { exact: false })).toBeVisible()
  await expect(card.getByText('2 / 10 条', { exact: true })).toBeVisible()

  await history.selectOption('empty')
  await expect(card.getByText('本轮暂无足够的有效对话数据', { exact: true })).toBeVisible()
  await expect(card.locator('canvas')).toHaveCount(0)
})

test('学生三维测量接口失败时不显示假雷达', async ({ page }) => {
  await page.route('**/api/reports/metacognition-measurements**', route => route.abort())
  await login(page, 'student')
  const card = page.locator('.macro-analytics-dashboard')
  await expect(card.locator('.alert-danger')).toBeVisible({ timeout: 15_000 })
  await expect(card.locator('canvas')).toHaveCount(0)
})

test('教师中心单个分区失败时保留其他工作区', async ({ page }) => {
  await page.route('**/api/research/analytics', route => route.abort())
  await login(page, 'teacher')
  // The shared API client retries transient GET failures before the section
  // reports its isolated error, so allow that bounded retry window to finish.
  await expect(page.getByText(/统计指标暂时加载失败/)).toBeVisible({ timeout: 20_000 })
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

test('管理员可看到固定协议真人朗读槽位及版本状态', async ({ page }) => {
  await login(page, 'admin')
  await page.route('**/api/admin/narration-assets', route => route.fulfill({
    json: [
      {
        slot_key: 'instructions',
        label: '测评指导语',
        source_text: '请在安静环境中完成测评。',
        category: 'instruction',
        asset: null
      },
      {
        slot_key: 'silence:0',
        label: '静默提示一',
        source_text: '请继续说出你的想法。',
        category: 'silence',
        asset: {
          id: 'narration-1',
          slot_key: 'silence:0',
          label: '静默提示一',
          source_text: '请继续说出你的想法。',
          original_filename: 'silence.wav',
          mime_type: 'audio/wav',
          size_bytes: 2048,
          sha256: 'e2e',
          version: 3,
          is_active: true,
          uploaded_by: 'admin',
          created_at: new Date().toISOString()
        }
      }
    ]
  }))

  await page.goto('/admin')
  await expect(page.getByRole('heading', { name: '固定协议真人朗读' })).toBeVisible()
  await expect(page.getByText('测评指导语', { exact: true })).toBeVisible()
  await expect(page.getByText('未上传，将使用语音回退', { exact: true })).toBeVisible()
  await expect(page.getByText('版本 3', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /试听$/ })).toBeVisible()
})

test('训练完成后持续同步评估汇总而无需刷新页面', async ({ page }) => {
  await login(page, 'admin')
  let jobRequests = 0
  let evaluationRequests = 0
  const now = new Date().toISOString()
  const trainingJob = {
    id: 'e2e-training-job',
    version: 'e2e-auto-refresh',
    stage: 'training',
    progress: 60,
    current_fold: 3,
    total_folds: 5,
    heartbeat_at: now,
    estimated_remaining_seconds: 8,
    sample_count: 120,
    label_distribution: { '1': 40, '2': 40, '3': 40 },
    dataset_fingerprint: 'e2e-fingerprint',
    config_snapshot: {
      experiment_type: 'tfidf_linear_svc',
      feature: 'tfidf',
      classifier: 'linear_svc'
    },
    metrics: null,
    is_active: false,
    artifact_sha256: null,
    cancel_requested: false,
    parent_job_id: null,
    error_message: '',
    created_at: now,
    started_at: now,
    completed_at: null,
    activated_at: null,
    updated_at: now
  }
  await page.route('**/api/research/model-training/jobs', route => {
    jobRequests += 1
    const completed = jobRequests >= 2
    return route.fulfill({
      json: [{
        ...trainingJob,
        status: completed ? 'completed' : 'running',
        stage: completed ? 'completed' : 'training',
        progress: completed ? 100 : 60,
        current_fold: completed ? null : 3,
        estimated_remaining_seconds: completed ? null : 8,
        artifact_sha256: completed ? 'e2e-sha256' : null,
        completed_at: completed ? now : null,
        metrics: completed ? { accuracy: 0.8, macro_f1: 0.75, weighted_f1: 0.78 } : null
      }]
    })
  })
  await page.route('**/api/research/model-training/evaluations', route => {
    evaluationRequests += 1
    return route.fulfill({
      json: {
        schema_version: 1,
        primary_metric: 'macro_f1',
        tie_breakers: ['macro_recall', 'weighted_f1', 'model_version'],
        latest_version_id: null,
        versions: [],
        errors: []
      }
    })
  })

  await page.goto('/admin')
  await expect(page.getByText('e2e-auto-refresh', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('已完成 · 等待人工验收', { exact: true }).first()).toBeVisible({ timeout: 10_000 })
  await expect.poll(() => evaluationRequests, { timeout: 15_000 }).toBeGreaterThanOrEqual(3)
})

test('模型效果对比主动清空后不会被评估刷新回退', async ({ page }) => {
  test.setTimeout(60_000)
  await login(page, 'admin')
  const now = new Date().toISOString()
  let jobRequests = 0
  let evaluationRequests = 0
  const evaluationModel = {
    model_id: 'e2e-comparison-model',
    model_version: 'e2e-comparison-model-v1',
    dataset_id: 'e2e-dataset',
    dataset_version: 'e2e-dataset-v1',
    dataset_fingerprint: 'e2e-comparison-fingerprint',
    comparison_group_id: 'e2e-comparison-version',
    comparison_group_label: 'E2E 对比版本',
    trained_at: now,
    labels: [{ id: 1, name: '标签一' }],
    summary: {
      accuracy: 0.8, macro_precision: 0.8, macro_recall: 0.8,
      weighted_precision: 0.8, weighted_recall: 0.8,
      macro_specificity: 0.8, macro_f1: 0.8, weighted_f1: 0.8,
      macro_auc_ovr: 0.8, cross_entropy: 0.2
    },
    per_class: [],
    confusion_matrix: [[10]],
    confusion_pairs: [],
    cross_validation: {
      fold_count: 5,
      macro_f1_mean: 0.8, macro_f1_std: 0.01, macro_f1_min: 0.79,
      macro_f1_max: 0.81, macro_f1_range: 0.02,
      macro_auc_mean: 0.8, macro_auc_std: 0.01, macro_auc_min: 0.79,
      macro_auc_max: 0.81, macro_auc_range: 0.02,
      macro_f1_interval: { mean: 0.8, std: 0.01, ci95_low: 0.79, ci95_high: 0.81, n: 5 },
      macro_auc_interval: { mean: 0.8, std: 0.01, ci95_low: 0.79, ci95_high: 0.81, n: 5 },
      per_class_auc_intervals: {}, train_macro_f1_mean: 0.82,
      train_test_macro_f1_gap: 0.02, train_sample_counts: [], test_sample_counts: [], folds: [],
      subject_disjoint_audit: { available: true, all_folds_verified: true, maximum_overlap_count: 0, note: '' }
    },
    dataset: {
      version: 'e2e-dataset-v1', fingerprint: 'e2e-comparison-fingerprint',
      sample_count: 10, participant_count: 10, class_count: 1,
      class_distribution: { '1': 10 }, split_strategy: 'group_kfold',
      random_seed: 42, external_holdout: false
    },
    model_info: {
      feature_type: 'embedding', classifier: 'xgboost', embedding_provider: 'remote',
      embedding_model: 'e2e', training_pipeline_version: 1, classifier_parameters: {},
      hyperparameters_tuned: false, hyperparameter_source: 'default', is_active: false
    },
    roc_curves: null, roc_evaluation: null, subject_leakage_risk: false,
    evaluation_warning: null, error_analysis: null,
    evidence_coverage: {
      subject_level_split: true, fold_uncertainty: true, independent_external_holdout: false,
      pairwise_statistical_test: false, cross_task_transfer: false,
      expert_reliability_bound_to_dataset: false, asr_quality_bound_to_dataset: false, notes: {}
    },
    source: {
      type: 'training_evaluation_result', manifest_schema_version: 1,
      legacy_synthesized: false, metrics_sha256: 'e2e-comparison-sha'
    }
  }

  await page.route('**/api/research/model-training/jobs', route => {
    jobRequests += 1
    const completed = jobRequests >= 2
    return route.fulfill({
      json: [{
        id: 'e2e-comparison-refresh-job', version: 'e2e-comparison-refresh',
        status: completed ? 'completed' : 'running', stage: completed ? 'completed' : 'training',
        progress: completed ? 100 : 50, current_fold: completed ? null : 2, total_folds: 5,
        heartbeat_at: now, estimated_remaining_seconds: completed ? null : 5, sample_count: 10,
        label_distribution: { '1': 10 }, dataset_fingerprint: 'e2e-comparison-fingerprint',
        config_snapshot: { experiment_type: 'embedding_xgboost', feature: 'embedding', classifier: 'xgboost' },
        metrics: completed ? { accuracy: 0.8, macro_f1: 0.8, weighted_f1: 0.8 } : null,
        is_active: false, artifact_sha256: completed ? 'e2e-comparison-sha' : null,
        cancel_requested: false, parent_job_id: null, error_message: '',
        created_at: now, started_at: now, completed_at: completed ? now : null,
        activated_at: null, updated_at: now
      }]
    })
  })
  await page.route('**/api/research/model-training/evaluations', route => {
    evaluationRequests += 1
    return route.fulfill({
      json: {
        schema_version: 1, primary_metric: 'macro_f1',
        tie_breakers: ['macro_recall', 'weighted_f1', 'model_version'],
        latest_version_id: 'e2e-comparison-version',
        versions: [{
          version_id: 'e2e-comparison-version', display_version: 'E2E 对比版本',
          dataset_version: 'e2e-dataset-v1', dataset_fingerprint: 'e2e-comparison-fingerprint',
          trained_at: now, comparable: true, comparison_warning: null,
          best_model_id: evaluationModel.model_id, models: [evaluationModel]
        }],
        errors: []
      }
    })
  })

  await page.goto('/admin')
  const comparisonCard = page.locator('.history-comparison-card')
  const picker = comparisonCard.locator('.history-model-picker')
  await expect(picker.getByText(/已选择 1 项/)).toBeVisible()

  await comparisonCard.locator('button', { hasText: '清空' }).click()
  await expect(picker.getByText(/已选择 0 项/)).toBeVisible()
  await expect.poll(() => evaluationRequests, { timeout: 15_000 }).toBeGreaterThanOrEqual(2)
  await expect(picker.getByText(/已选择 0 项/)).toBeVisible()

  await comparisonCard.locator('button', { hasText: '选择各版本最佳' }).click()
  await picker.locator('summary').click()
  await picker.getByRole('checkbox').uncheck()
  await expect(picker.getByText(/已选择 0 项/)).toBeVisible()
  const requestsAfterManualClear = evaluationRequests
  await expect.poll(() => evaluationRequests, { timeout: 15_000 }).toBeGreaterThan(requestsAfterManualClear)
  await expect(picker.getByText(/已选择 0 项/)).toBeVisible()
})

test('训练记录可仅复用参数并在确认后清除', async ({ page }) => {
  await login(page, 'admin')
  let deleted = false
  const now = new Date().toISOString()
  const reusableJob = {
    id: 'e2e-reusable-job',
    version: 'e2e-reusable',
    status: 'completed',
    stage: 'completed',
    progress: 100,
    current_fold: null,
    total_folds: 5,
    heartbeat_at: null,
    estimated_remaining_seconds: null,
    sample_count: 120,
    label_distribution: { '1': 40, '2': 40, '3': 40 },
    dataset_fingerprint: 'e2e-old-dataset',
    config_snapshot: {
      experiment_type: 'tfidf_linear_svc',
      feature: 'tfidf',
      classifier: 'linear_svc',
      dataset_source: 'uploaded',
      dataset_name: '不应复用的旧训练集',
      classifier_parameters: { C: 2, max_iter: 5000, class_weight: 'balanced' },
      hyperparameters_tuned: true
    },
    metrics: { accuracy: 0.8, macro_f1: 0.75, weighted_f1: 0.78 },
    is_active: false,
    artifact_sha256: 'e2e-sha256',
    cancel_requested: false,
    parent_job_id: null,
    error_message: '',
    created_at: now,
    started_at: now,
    completed_at: now,
    activated_at: null,
    updated_at: now
  }
  await page.route('**/api/research/model-training/jobs', route => route.fulfill({
    json: deleted ? [] : [reusableJob]
  }))
  await page.route('**/api/research/model-training/jobs/e2e-reusable-job', route => {
    expect(route.request().method()).toBe('DELETE')
    deleted = true
    return route.fulfill({
      json: {
        status: 'deleted', job_id: reusableJob.id,
        version: reusableJob.version, artifact_removed: true
      }
    })
  })
  await page.route('**/api/research/model-training/evaluations', route => route.fulfill({
    json: {
      schema_version: 1,
      primary_metric: 'macro_f1',
      tie_breakers: ['macro_recall', 'weighted_f1', 'model_version'],
      latest_version_id: null,
      versions: [],
      errors: []
    }
  }))

  await page.goto('/admin')
  await expect(page.getByText('e2e-reusable', { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: /复用参数/ }).first().click()
  const builder = page.locator('#training-builder')
  await expect(builder.getByText(/已复用.*e2e-reusable.*训练集未复用/)).toBeVisible()
  await expect(builder.getByRole('radio', { name: /系统专家金标准/ })).toBeChecked()
  await expect(builder.getByText('不应复用的旧训练集', { exact: true })).toHaveCount(0)

  await page.getByRole('button', { name: /清除记录/ }).click()
  await expect(page.getByText(/永久删除.*训练记录/)).toBeVisible()
  await page.getByRole('button', { name: '永久删除', exact: true }).click()
  await expect.poll(() => deleted).toBe(true)
  await expect(page.getByText('e2e-reusable', { exact: true })).toHaveCount(0)
})

test('训练记录分页显示并支持本页批量清除', async ({ page }) => {
  await login(page, 'admin')
  const now = new Date().toISOString()
  let jobs = Array.from({ length: 8 }, (_, index) => ({
    id: `e2e-batch-${index}`,
    version: `e2e-history-${index}`,
    status: 'completed', stage: 'completed', progress: 100,
    current_fold: null, total_folds: 5, heartbeat_at: null,
    estimated_remaining_seconds: null, sample_count: 90,
    label_distribution: { '1': 30, '2': 30, '3': 30 },
    dataset_fingerprint: `e2e-fingerprint-${index}`,
    config_snapshot: {
      experiment_type: 'tfidf_linear_svc', feature: 'tfidf', classifier: 'linear_svc',
      dataset_name: `数据集-${index}`
    },
    metrics: { accuracy: 0.8, macro_f1: 0.75, weighted_f1: 0.78 },
    is_active: false, artifact_sha256: `e2e-sha-${index}`,
    cancel_requested: false, parent_job_id: null, error_message: '',
    created_at: new Date(Date.now() - index * 1000).toISOString(),
    started_at: now, completed_at: now, activated_at: null, updated_at: now
  }))
  let submittedIds: string[] = []
  await page.route('**/api/research/model-training/jobs', route => route.fulfill({ json: jobs }))
  await page.route('**/api/research/model-training/jobs/batch-delete', async route => {
    const body = route.request().postDataJSON() as { job_ids: string[] }
    submittedIds = body.job_ids
    jobs = jobs.filter(job => !submittedIds.includes(job.id))
    return route.fulfill({
      json: {
        status: 'deleted', deleted_count: submittedIds.length,
        items: submittedIds.map(jobId => ({ status: 'deleted', job_id: jobId, version: jobId, artifact_removed: false }))
      }
    })
  })
  await page.route('**/api/research/model-training/evaluations', route => route.fulfill({
    json: { schema_version: 1, primary_metric: 'macro_f1', tie_breakers: [], latest_version_id: null, versions: [], errors: [] }
  }))

  await page.goto('/admin')
  await expect(page.locator('.training-group-row')).toHaveCount(6)
  await expect(page.getByText('第 1 / 2 页', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '选择本页可删除项', exact: true }).click()
  await expect(page.getByRole('button', { name: /批量清除（6）/ })).toBeEnabled()
  await page.getByRole('button', { name: /批量清除（6）/ }).click()
  await page.getByRole('button', { name: '永久删除 6 条', exact: true }).click()
  await expect.poll(() => submittedIds.length).toBe(6)
  await expect(page.locator('.training-group-row')).toHaveCount(2)
  await expect(page.getByText('共 2 个版本', { exact: true })).toBeVisible()
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
