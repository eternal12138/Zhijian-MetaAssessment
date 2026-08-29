# 最近报告：审阅、重新 AI 分析与发布

- 按 `generated_at DESC, id DESC` 排序后分页。界面显示最近生成时间（带 UTC 时区的接口时间转为浏览器本地时间）和报告版本。
- 草稿、编码待复核、编码已复核均为未发布状态；编码已复核不等于报告已经审阅或发布。
- 单条点击“重新 AI 分析”，或勾选当前页草稿后批量执行。选择不跨页；批量逐份执行，展示每份结果，可停止后续任务。需保持页面打开，离开页面会停止发送后续任务，已发送的请求可能继续完成。
- 仅重新生成报告画像和建议，使用当前启用的报告提示词及已有证据，不重跑 ASR、清洗、三分类或人工编码。服务器仍检查教师管理范围和数据质量门槛。
- 成功时替换原草稿，递增 `version_no`、更新生成时间，并要求重新审阅；不是新增一份可回滚的历史草稿。失败时保留原草稿，AI 未启用/返回不完整不能以规则兜底冒充 AI 成功。
- 已发布/归档报告禁止重算，自动完成新专家批次时也不会覆盖已发布报告。原始编码和新批次仍可保留。
- 更新与发布共享报告行锁；请求绑定 `expected_generated_at`，过期页面需刷新。生成时间改变后旧发布确认失效。
- 入口复用 `POST /api/research/analysis/runs/{run_id}`，请求体为 `report_only=true, reanalyze=false, expected_generated_at=当前报告生成时间`。批量前端串行调用，不把多份 LLM 分析塞进一个长 HTTP 请求。
- 每次调用保留分析任务与审计记录，包含结果状态、旧生成时间和成功后的报告版本。不新增数据库迁移或依赖。

验证：后端 `python -m unittest tests.test_report_review_flow tests.test_dashboard_pagination`；前端 `node --test tests/recent-reports.test.mjs tests/report-review.test.mjs tests/section-pagination.test.mjs`。
