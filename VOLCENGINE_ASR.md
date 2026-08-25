# 火山引擎正式 ASR 配置

本项目使用“浏览器字幕用于即时提示、火山引擎录音文件识别用于权威转录”的双层设计。原始录音始终先保存在本系统中，云端识别失败不会导致录音丢失。

## 1. 火山引擎控制台

1. 完成火山引擎实名认证。
2. 进入“豆包语音”并创建语音应用。
3. 开通“录音文件识别 2.0”及其试用额度。
4. 新版控制台创建 API Key；旧版控制台记录 App ID 和 Access Token。
5. 确认资源 ID。推荐值为 `volc.seedasr.auc`，最终以控制台显示为准。
6. 在费用中心设置余额预警，并在试用阶段避免自动转为不受控的后付费调用。

不要把 API Key 放在前端、文档截图、Git 仓库或公开日志中。

## 2. 生产环境变量

复制 `.env.production.example` 为 `.env.production`，然后配置：

```dotenv
ASR_PROVIDER=volcengine
ASR_MODEL=volc.seedasr.auc
ASR_LANGUAGE=zh
ASR_TIMEOUT_SECONDS=300
ASR_MAX_RETRIES=5
ASR_CONFIG_VERSION=volc-seedasr-auc-2026-07

ASR_PUBLIC_BASE_URL=https://www.21050411.xyz
ASR_AUDIO_SIGNING_SECRET=至少32字符的独立随机密钥
ASR_AUDIO_URL_TTL_SECONDS=600

VOLCENGINE_ASR_API_KEY=火山引擎新版控制台APIKey
VOLCENGINE_ASR_APP_ID=
VOLCENGINE_ASR_ACCESS_KEY=
VOLCENGINE_ASR_RESOURCE_ID=volc.seedasr.auc
VOLCENGINE_ASR_SUBMIT_URL=https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit
VOLCENGINE_ASR_QUERY_URL=https://openspeech.bytedance.com/api/v3/auc/bigmodel/query
VOLCENGINE_ASR_QUERY_INTERVAL_SECONDS=3
VOLCENGINE_ASR_MAX_WAIT_SECONDS=600
```

如果使用旧版控制台，将 `VOLCENGINE_ASR_API_KEY` 留空，同时填写：

```dotenv
VOLCENGINE_ASR_APP_ID=旧版AppID
VOLCENGINE_ASR_ACCESS_KEY=旧版AccessToken
```

可在 Linux 服务器生成音频签名密钥：

```bash
openssl rand -hex 32
```

## 3. 音频下载安全

火山引擎通过下列形式的短时地址读取音频：

```text
https://www.21050411.xyz/api/asr-provider/audio/{job_id}?expires=...&signature=...
```

该地址具备以下约束：

- 使用 HMAC-SHA256 签名；
- 默认十分钟后失效；
- 签名与单个 ASR 任务绑定；
- 仅在任务处于 `transcribing` 状态时可下载；
- 实际文件路径必须位于受控音频目录内；
- 响应禁止浏览器和代理缓存；
- 地址不包含姓名、学号或服务器文件路径。

Cloudflare 或其他反向代理必须将 `/api/*` 转发给 FastAPI 后端，且不能要求火山引擎携带网页登录令牌。

## 4. 研究参数

当前 Provider 固定使用：

```text
自动标点：开启
语义顺滑：关闭
数字规整：关闭
句级结果：开启
```

这样可以尽量保留口语重复、自我修正和思考痕迹。每次识别都会同时保存完整原始 JSON、机器转录、分段时间戳和后续教师校订版本。

如果修改模型、热词、语义处理或分段参数，必须同步修改 `ASR_CONFIG_VERSION`，并在实验记录中注明。

## 5. 部署与验证

```bash
docker compose up -d --build backend asr-worker frontend
docker compose logs -f asr-worker
```

正式采集前完成一次真实中文录音验证：

1. 学生完成一项测评并提交。
2. 确认 ASR 状态依次经过 `queued`、`preparing_audio`、`transcribing`、`completed`。
3. 检查教师校订页面是否出现句级转录和时间戳。
4. 播放导出的 WAV，确认有声音且时长正确。
5. 检查导出包是否同时包含原始音频、原始转录、教师校订版本和校验和。
6. 在火山引擎控制台核对已消耗时长。

如果返回“未授权”或资源 ID 错误，不要反复提交正式数据，应先在控制台确认开通的产品与 `VOLCENGINE_ASR_RESOURCE_ID` 完全一致。
