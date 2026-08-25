# 阿里云 Linux 生产部署

本方案面向单台阿里云 Linux 服务器，使用 Docker Compose 运行 MySQL、
FastAPI、ASR Worker 和 Nginx。公网入口推荐继续使用 Cloudflare Tunnel，
服务器安全组不需要开放 80、8000、3306 或 5173。

在 Windows 本地上传前，可运行
`powershell -ExecutionPolicy Bypass -File .\deploy\package.ps1`。
脚本会生成新的部署 ZIP，并自动排除虚拟环境、依赖缓存、运行数据和真实密钥文件。

## 1. 服务器准备

推荐 Ubuntu 24.04 LTS，至少 2 核 CPU、4 GB 内存和 60 GB 数据盘。若在本机
运行语音识别模型，应按模型要求增加 CPU、内存或 GPU。

安装 Docker Engine、Docker Compose Plugin、Git，并设置系统时区：

```bash
sudo timedatectl set-timezone Asia/Shanghai
docker --version
docker compose version
```

阿里云安全组仅保留管理需要的 SSH 来源；MySQL 和应用端口不对公网开放。

## 2. 创建生产配置

```bash
cp .env.production.example .env.production
openssl rand -hex 48
```

编辑 `.env.production`：

- 将所有 `CHANGE_ME` 替换为真实值；
- `SECRET_KEY` 使用上一步生成的随机值；
- `DB_PASSWORD` 与 `MYSQL_ROOT_PASSWORD` 使用不同强密码；
- `BOOTSTRAP_ADMIN_PASSWORD` 设置为至少 12 位的首次管理员密码，不得使用
  `123456`；重复部署不会重置该账号；
- `PUBLIC_HOST`、`CORS_ORIGINS`、`TRUSTED_HOSTS` 使用实际域名；
- 首次部署可保持 `REPORT_USE_LLM=false`、`ASR_PROVIDER=disabled`，登录管理端后
  在“模型服务”页面填写火山方舟与豆包语音配置并运行诊断；
- 不要提交或发送 `.env.production`。

账号业务规则保持为：批量创建和管理员重置默认密码 `123456`，密码最低 6 位。
批量导入格式为“账号、姓名、角色、班级/负责班级”；学生班级和教师负责班级均可留空，
并在创建后分配；多个负责班级使用 `|` 或 `；` 分隔。
使用默认或重置密码的账号可以暂不修改，但每次登录都会收到提醒，直到完成修改。
首次生产管理员不使用默认密码。

## 3. 首次启动

```bash
chmod +x deploy/deploy.sh deploy/backup.sh deploy/verify-backup.sh
./deploy/deploy.sh
docker compose --env-file .env.production ps
docker compose --env-file .env.production logs --tail=100 backend
```

首次启动会依次执行全部数据库迁移、根据 `BOOTSTRAP_ADMIN_*` 创建首位正式管理员，
并发布测评协议 `2026.2`。生产初始化不会导入 `student/teacher/admin` 演示账号。
协议包含两张中文刺激材料及其 SHA-256 摘要，服务端保存任务内容和顺序快照。

Nginx 只监听服务器本机 `127.0.0.1:8080`。若不用 Cloudflare Tunnel，需要
另行配置 HTTPS 入口，不应直接把该 HTTP 端口开放给参与者。

## 4. Cloudflare Tunnel

在 Cloudflare 控制台把公开主机名指向：

```text
Service: http://frontend:80
```

将 Tunnel Token 写入服务器 `.env.production` 的
`CLOUDFLARE_TUNNEL_TOKEN`，然后启动可选 profile：

```bash
docker compose --env-file .env.production --profile tunnel up -d cloudflared
```

不要把 Tunnel Token 写入 Git、聊天记录或公开文档。

## 5. 更新

更新代码前先备份，随后重新构建。数据库迁移会在 API 和 Worker 启动前幂等执行：

```bash
./deploy/backup.sh
git pull
./deploy/deploy.sh
```

如果新版本需要切换正式测评协议，而数据库中仍存在进行中的测评，初始化会主动失败，
以防学生会话与题目版本错配。应先让参与者完成测评，或在管理端确认并放弃无效会话，
再重新部署。已经完成的历史会话和旧任务不会被删除。

## 6. 备份

手动执行：

```bash
./deploy/backup.sh
```

可通过 root 的 cron 每天凌晨执行。脚本同时备份 MySQL、音频和导出文件，
生成 SHA-256，并按照 `BACKUP_RETENTION_DAYS` 清理过期的本机备份。每次备份后
可执行：

```bash
./deploy/verify-backup.sh /srv/metacognition/backups/备份时间目录
```

还应把备份加密复制到另一台
受控设备或对象存储，并在正式采集前完成一次恢复演练。

恢复演练应在独立测试目录或另一台测试服务器进行，不要直接覆盖生产数据。先验证
`SHA256SUMS`，再将 `database.sql` 导入空数据库，并解压
`audio-exports.tar.gz`，最后核对会话数量、音频文件和导出功能。

## 7. 生产安全边界

- `migrate` 容器临时使用数据库 root 账号执行结构迁移；
- API 与 ASR Worker 使用 `DB_USER`，迁移后只保留增删改查权限；
- 后端、MySQL 和 Nginx 均不直接监听公网地址；
- Nginx 对登录接口进行 IP 限流，应用同时按账号记录失败次数并临时锁定；
- 批量创建和重置密码保持 `123456`；用户可暂不修改，但每次登录都会提醒，
  修改后旧 JWT 自动失效；
- `.env.production` 权限为 `0600`，不得提交到代码仓库；
- 管理端保存的模型密钥以 `SECRET_KEY` 派生密钥加密；不要随意更换
  `SECRET_KEY`，更换后需重新录入模型密钥且所有登录令牌失效；
- 前端响应包含 CSP、HSTS、麦克风权限和防嵌入等安全响应头。

## 8. 上线验收

- `https://实际域名/` 可以访问且全程 HTTPS；
- `/api/health/ready` 返回数据库和存储均正常；
- 管理员、教师、学生权限隔离正确；
- 默认密码登录时可以选择暂不修改，之后每次登录仍会提醒；
- 连续错误登录会临时锁定；
- 使用真实浏览器完成录音、提交、ASR、校订和 ZIP 导出；
- 下载的 `recording.wav` 有声音，`audio_index.csv` 显示有效信号；
- 两项正式任务显示协议 `2026.2` 对应的中文图片，朗读和 15 秒静默提醒正常；
- 管理端模型诊断显示 LLM、ASR 和音频公网下载地址可用；
- 重启服务器后所有容器自动恢复；
- 已验证数据库和音频备份可以恢复。
# 元认知分类模型的 2C4G 部署约束

生产服务器为 2 核、4 GiB、无 GPU。模型实验与远程 Embedding API 调用应和业务服务解耦；生产服务器默认只部署通过资源 Benchmark 的轻量分类器。

- 首选候选：TF-IDF + LinearSVC。模型随服务启动加载一次并驻留，所有请求复用同一实例，禁止逐请求读取模型文件。
- Uvicorn 使用 1 个 worker。增加 worker 会复制 Python 进程与模型内存；只有持续压测证明内存安全后才可调整。
- 如果远程 Embedding 的 Macro-F1 明显更高，使用“外部 Embedding API + 本机轻量分类器”；业务容器不携带任何本地大模型权重。
- `research/requirements-training.txt` 仅用于训练机；生产后端不得安装 matplotlib 等评估依赖，也不安装任何本地大模型推理依赖。
- 生产包不应包含训练数据、Notebook、实验缓存、混淆矩阵或任何 Embedding 模型权重。仓库根目录的 Compose 只以 `backend/` 为后端构建上下文，研究目录不会进入后端镜像。

实际选择依据位于 `research/baseline_output/reports/deployment_benchmark.csv` 和 `deployment_recommendation.json`。报告分别给出“科研最佳模型”和“生产推荐模型”，两者允许不同。
