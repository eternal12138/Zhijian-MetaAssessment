# Qwen 文本嵌入与全连接分类器

本目录实现“云端生成文本向量、本地或训练节点训练轻量分类器”的版本化流程。系统不会在本机加载 Qwen 大模型；本机只保存向量，并训练一个小型全连接分类器。

## 设计目标

- 通过阿里云百炼兼容接口调用 `qwen3.7-text-embedding`。
- 按文本哈希缓存向量；再次训练时只为新增或改变的文本付费。
- 每次训练生成独立版本，不覆盖旧向量、旧模型和旧评估结果。
- 训练任务状态保存为 JSON，便于后续接入后台任务队列和管理员页面。
- API Key 不进入代码仓库、模型文件、训练结果或日志。
- 发送给嵌入接口的请求只包含 `cleaned_text`，不包含账号、姓名、班级和问卷姓名；正式训练前仍需检查文本中是否残留个人敏感信息。

## 首次配置

1. 安装 `requirements-qwen-api.txt` 中的依赖。
2. 复制 `.env.qwen.example` 为 `.env.qwen`。
3. 在 `.env.qwen` 中填写百炼业务空间 API Key 和 Workspace ID 对应的北京地域地址。
4. 不要把 `.env.qwen` 上传到服务器压缩包或提交到 Git；服务器应使用环境变量或服务器独立的密钥文件。

## 训练流程

先执行不调用远端接口的配置检查：

```powershell
python research/generate_qwen_embeddings.py --dry-run
```

启动一个完整的版本化训练任务：

```powershell
python research/run_qwen_training_job.py --version v1
```

再次加入新标注数据时，生成新数据集和分组五折清单，然后使用新版本名：

```powershell
python research/run_qwen_training_job.py --version v2 --dataset <新训练集.csv> --manifest <新划分清单.csv>
```

公共 SQLite 向量缓存位于 `research/embeddings/qwen_embedding_cache.sqlite3`。版本目录只保存该次训练对应的向量快照与清单，保证可复现。

## 输出内容

- `research/jobs/<任务ID>/status.json`：排队、向量生成、训练、完成或失败状态。
- `research/jobs/<任务ID>/job.log`：该任务日志，不包含 API Key。
- `research/embeddings/<版本>/`：向量、样本映射、嵌入配置。
- `research/results/qwen_fc_<版本>/`：五折模型、OOF 预测、各类指标、ROC、混淆矩阵和最终模型。

## 后续接入系统

后台不应在 HTTP 请求中直接训练。推荐由管理员提交训练请求后写入数据库任务表，再由独立 Worker 调用本任务运行器；前端轮询任务状态。至少需要以下接口：

- `POST /api/admin/model-training/jobs`：创建训练版本。
- `GET /api/admin/model-training/jobs`：查看历史版本和状态。
- `GET /api/admin/model-training/jobs/{id}`：查看进度、指标与错误。
- `POST /api/admin/model-training/jobs/{id}/activate`：人工确认后启用模型。
- `POST /api/admin/model-training/jobs/{id}/cancel`：取消尚未完成的任务。

新模型必须先完成五折评估并由管理员明确启用；训练完成不能自动替换生产模型。
