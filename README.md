# AI 元认知测评系统

前端采用 Vue 3、TypeScript、Vite 和 Bootstrap 5 搭建，视觉参考 Skydash 的明亮卡片式管理后台布局。

## 本地一键启动

在项目根目录打开 PowerShell：

双击 `dev.cmd` 可以启动完整的本地开发环境，并在启动失败时保留错误窗口。
也可以在 PowerShell 中运行：

```powershell
.\dev.ps1
```

脚本会依次：

1. 检查 `backend/.env`，缺失时从 `.env.example` 创建。
2. 检查 Python 3.11+，创建或验证 `backend/.venv`。
3. 安装后端和前端依赖。
4. 验证 MySQL 端口、账号和数据库名称。
5. 幂等执行当前项目的数据库迁移与标准测评协议初始化。
6. 当 `LLM_BASE_URL` 指向本机时，检查并尝试启动 Ollama。
7. 启动 FastAPI 与 Vite，并等待健康检查通过。

常用参数：

```powershell
# 重启由本项目记录的开发进程
.\dev.ps1 -Restart

# 已安装依赖时跳过 pip/pnpm install
.\dev.ps1 -SkipInstall

# 启动完成后打开浏览器
.\dev.ps1 -OpenBrowser

# 使用其他端口
.\dev.ps1 -BackendPort 8080 -FrontendPort 3000
```

停止服务：

```powershell
.\stop.ps1
```

运行日志和 PID 保存在 `.dev/`，不会依赖当前用户名、盘符或项目的绝对路径。

默认地址：

- 前端：<http://127.0.0.1:5173>
- 后端：<http://127.0.0.1:8000>
- API 文档：<http://127.0.0.1:8000/docs>

## 环境配置与迁移

- 后端只从 `backend/.env` 读取环境配置，配置文件位置锚定到后端目录。
- `AUDIO_UPLOAD_DIR` 可以是绝对路径；相对路径会相对于 `backend/` 解析。
- 数据库中的新音频记录只保存相对于音频根目录的路径，避免写入本机盘符。
- 前端统一请求同源 `/api`。开发环境由 Vite 代理到 FastAPI，生产环境建议由 Nginx/Caddy 反向代理。
- `frontend/pnpm-workspace.yaml` 不包含本机 pnpm store 的绝对路径。
- `.venv`、`node_modules`、`.env`、上传文件和运行日志不会进入版本控制。

云端部署时至少需要修改：

```dotenv
# backend/.env
APP_DEBUG=false
ENABLE_API_DOCS=false
ALLOW_PUBLIC_REGISTRATION=false
SECRET_KEY=替换为高强度随机值
DB_HOST=数据库主机名
DB_PASSWORD=数据库密码
CORS_ORIGINS=https://你的域名
LLM_BASE_URL=https://模型服务地址/v1
LLM_API_KEY=模型服务密钥
AUDIO_UPLOAD_DIR=/srv/metacognition/uploads/audio
```

数据库结构以 SQLAlchemy 模型和 `backend/scripts/migrate_all.py` 为准。
`dev.ps1` 仅在 `APP_DEBUG=true` 时幂等创建 `student`、`teacher`、`admin`
三个本地演示账号，初始密码均为 `123456`。生产环境的 `migrate` 容器会先在
`.env.production` 指定的 `DB_NAME` 中幂等建表，再执行全部版本迁移和协议发布；
不会导入演示账号，而是通过 `BOOTSTRAP_ADMIN_*` 创建首位正式管理员。

从第一阶段数据库升级到第二阶段标准化测评协议时执行：

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\migrate_phase2.py
```

数据库迁移与正式协议发布已经分离：迁移只调整结构，
`scripts/seed_protocol.py` 发布协议 `2026.2` 的两项任务、中文刺激材料元数据和
附录二所指的 24 道任务后问卷。问卷对应 Zepeda & Nokes-Malach（2023）的
三维度任务型元认知量表，采用 1–7 点评分，其中第 17 题反向计分。
`migrate_phase11.py` 为测评固化量表版本，并保留早期 12 题开发版历史记录，
避免升级后错误解释旧数据。

第三阶段增加字幕证据编码、完整测评报告和人工复核字段：

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\migrate_phase3.py
```

`dev.ps1` 会自动幂等执行第二、第三阶段迁移。报告默认采用规则基线，并在
`REPORT_USE_LLM=true` 且模型服务可用时对未匹配片段进行 LLM 辅助编码。
模型不可用会自动降级，不会阻止报告生成。

报告属于阶段性学习反馈：当前没有正式常模，不展示虚构百分位，也不能用于
临床诊断、高风险筛选或替代专业心理测量。低置信度编码进入教师/管理员的
`/review` 人工复核页面，人工分数优先于模型分数。

站内通知使用 `backend/scripts/migrate_phase5.py` 创建。系统会在测评完成、
报告生成、出现待复核编码和人工复核完成时写入隐私安全的消息摘要。通知只
允许跳转到站内路径，不保存完整录音、字幕正文、密码或模型密钥。

第四阶段增加版本化方法模板、分析任务、双人独立编码、分歧裁决、报告发布、
受控实名研究导出、审计日志和基础研究指标：

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\migrate_phase4.py
```

`dev.ps1` 会自动幂等执行第二、第三、第四阶段、任务顺序和站内通知迁移。当前内置的
`coding_prompt`、`scoring_standard` 和 `intervention_templates` 均为
`draft-1` 开发模板。管理员可在“研究管理”页面创建新版本并立即启用，
历史版本不会被覆盖。

第六阶段使用 `backend/scripts/migrate_phase6.py` 创建测评交互事件时间线。
事件按会话和客户端事件 ID 幂等保存，记录录音、语音活动、15 秒静默提醒、
中性提示播放、音频上传和任务提交等过程信息。`dev.ps1` 会自动执行该迁移。

第四阶段暂按“某维度编码证据数 ÷ 全部有效字幕片段数”计算行为频次，并将
行为分与任务后问卷分分别展示。开发模板中保留暂定融合权重，但在完成正式
样本验证前，综合分和等级仍属于阶段性反馈。

标准测评的两项任务不再对所有学生使用同一个固定顺序。教师可以在“教师中心”
手动分配 AB/BA，也可以勾选学生后一键执行平衡分配；教师只能操作其
`managed_classes` 范围内的学生，管理员可以操作全部学生。分配仅影响学生
下一次新建的测评，已经开始的测评继续使用创建时保存的顺序快照，避免中途
换序。相关幂等迁移为：

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\migrate_task_order.py
```

教师与研究工作流：

1. 管理员创建编码批次，并固定分配三个不同账号：编码员 A、编码员 B、仲裁员。
2. 系统将权威转录的全部片段建立为独立编码单元，不只抽取 AI 已识别的片段。
3. A/B 分别独立盲编，提交前不显示 AI 结果或另一名编码员的结果。
4. 两人维度一致时自动形成双人共识；不一致时只进入指定第三方仲裁员的队列。
5. 仲裁完成后形成最终人工编码，再与独立保存的 AI 结果进行人机一致性比较。
6. 所有编码单元形成共识后，批次自动完成，并重新生成所涉及测评的报告。
7. 研究中心分别展示人际一致率、Cohen κ，以及人机 Cohen κ、频次
   Pearson r、MAE 和分维度精确率/召回率/F1。
8. 问卷 CSV 与转录候选 ZIP 均属于受控实名导出。ZIP 可选择是否包含标准 WAV，
   并按中文目录分别保存用户信息、原转录、AI 候选和人工接受文本；双人盲编、
   共识与仲裁结果通过独立的专家训练数据 CSV 导出。只有获授权的教师和管理员
   能够导出，创建、下载凭证和下载行为均写入审计日志。具体口径见
   `EXPERIMENT_DATA.md` 与 `EXPERT_DATASET.md`。

固定双人编码工作流使用 `backend/scripts/migrate_phase12.py` 创建数据表。
本地 `dev.ps1` 和服务器 `backend/scripts/migrate_all.py` 都会幂等执行该迁移，
因此同一份代码可以直接部署到现有服务器，不需要手工修改数据库。

管理员创建编码批次前可以按班级、学生、任务及测评完成日期筛选，并预览
学生数、完整测评数、会话数和权威转录片段数。系统默认排除已经进入其他
编码批次的片段；如确需开展复测编码，可由管理员显式关闭该保护。批次创建时
会固化实际编码单元、筛选条件和数量摘要。相关幂等迁移为
`backend/scripts/migrate_phase13.py`，本地和生产迁移入口均已包含。

后端基础回归测试：

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`dev.ps1` 用于 Windows 本地开发。正式云服务器建议使用 Nginx + systemd、
Docker Compose 或 Kubernetes 托管前后端、MySQL 和模型服务，不使用 Vite
开发服务器对外提供生产流量。

阿里云 Linux 单机生产部署已提供 `compose.yaml`、前后端 Dockerfile、Nginx
配置、生产环境模板、幂等迁移入口和备份脚本。部署步骤与验收清单见
`DEPLOY_ALIYUN.md`。生产环境不会改变账号业务规则：批量创建和重置密码默认
仍为 `123456`，密码最低 6 位；用户可以暂不修改初始密码，但每次登录都会提醒。
首次正式管理员必须使用至少 12 位的独立密码。

正式启用手机参与测评前，还需按 `MOBILE_DEVICE_ACCEPTANCE.md` 在真实 iPhone、
Android 手机上验证麦克风授权、锁屏/来电/切后台中断、网络恢复、长录音和数据
闭环。桌面浏览器的移动端模拟不能替代这一项验收。

## 当前页面

- `/`：学生端概览
- `/assessment`：情境测评入口
- `/report`：个人报告
- `/teacher`：教师任务管理
- `/review`：双人独立盲编、指定仲裁与管理员批次人员分配
- `/admin`：研究与系统管理

## 语音测评数据接口

- `POST /api/sessions/{session_id}/audio-chunks`：以 multipart/form-data 上传录音分片。
- `POST /api/sessions/{session_id}/transcripts`：幂等保存浏览器最终转录片段。
- `POST /api/sessions/{session_id}/complete`：校验分片数量、序号、文件尺寸与摘要，完成会话并创建 ASR 任务。
- `GET /api/sessions/{session_id}/asr`：查询异步识别状态与当前权威转录。
- `POST /api/sessions/{session_id}/asr/retry`：在服务配置修复后重试失败任务。
- `GET /api/sessions/{session_id}/transcript-versions`：查询不可变转录版本。
- `POST /api/sessions/{session_id}/transcript-versions/{version_id}/approve`：教师或管理员确认指定版本。
- `POST /api/sessions/{session_id}/transcript-versions/corrections`：以人工校订内容创建新的权威版本。

浏览器字幕只用于测评现场反馈，报告分析以服务端 ASR 或人工校订的权威版本为准。
音频默认保存到 `backend/uploads/audio/<session_id>/`；Worker 按顺序合并浏览器分片，
再用 FFmpeg 转为 16 kHz、单声道 PCM WAV 后提交识别。原分片、合并源文件和规范化
音频均保留受控相对路径，并通过内容摘要防止识别期间被替换。

本地启用权威 ASR 时，在 `backend/.env` 配置：

```dotenv
ASR_PROVIDER=openai_compatible
ASR_BASE_URL=https://your-asr-service.example/v1
ASR_API_KEY=replace-with-secret
ASR_MODEL=whisper-1
FFMPEG_PATH=ffmpeg
```

`ASR_BASE_URL` 应指向提供 `/audio/transcriptions` 的 OpenAI 兼容服务根路径。
如果 FFmpeg 未加入 `PATH`，请把 `FFMPEG_PATH` 设置为该服务器上的绝对路径。
`dev.ps1` 会执行 Phase 7 迁移并启动独立 ASR Worker；生产环境应将
`python scripts/asr_worker.py` 作为独立的 systemd、Docker 或 Kubernetes 工作负载运行。
ASR 未配置时任务会显示为 `waiting_configuration`，系统不会用浏览器字幕冒充权威结果，
报告生成也会返回 `asr_not_ready`。

## 第二阶段标准化测评流程

学生端 `/assessment` 固定按以下顺序运行：

1. 知情同意与数据采集说明。
2. 麦克风和浏览器实时字幕检查。
3. 统一的出声思维说明与算术练习。
4. 按教师/管理员分配的 AB 或 BA 顺序完成投球机和运动员两项任务。
5. 如协议启用，完成附录二 24 题、1–7 点任务后元认知问卷。
6. 完整性确认并提交测评。

正式任务期间不向被试显示元认知维度、评分或策略建议。连续静默 15 秒时，
系统只从四句固定中性提示中依次播放一句，以避免对测量过程产生引导。

本地旧数据库升级由 `dev.ps1` 依次执行幂等迁移；生产服务器统一运行
`deploy/deploy.sh`，由一次性 `migrate` 容器完成建表、升级和协议发布。
其中 `migrate_phase7.py` 创建 ASR 任务、转录版本及片段版本关联字段。
