# 日常更新：只执行本次需要的操作

## 先判断更新范围

| 本次改动 | 构建/重建 | 数据库迁移 | 备份 |
| --- | --- | --- | --- |
| 只有前端 Vue、CSS、图片、图表或前端 Dockerfile | 仅 frontend | 不执行 | 保留上一版源码包和镜像即可；不重复备份数据库/录音 |
| 后端代码、迁移脚本、Compose 或混合发布 | 按该发布的说明执行 | 有数据库改动或阶段不确定时必须执行 | 数据库改动前做一次最新数据库备份，不重复压缩录音/导出包 |

不要根据页面看起来相似、release.json 的阶段号或登录成功就认定数据库无需迁移。
仅前端流程不能用于后端、Compose 或数据库已经变化的发布。

## 仅前端更新（含静态文件权限修复）

先确认此次包没有需要同步部署的后端变更，且旧版服务已正常运行。
把发布包和配套 SHA256 上传到 `/opt/metacognition`，将下方示例包名替换为实际文件名。
每行单独执行，任何错误都停止。无需运行 backup.sh、无需停止后端或数据库。

```bash
cd /opt/metacognition
sha256sum -c 新部署包.zip.sha256 && unzip -o 新部署包.zip
python3 deploy/verify-release.py /opt/metacognition
docker compose --env-file .env.production build --progress=plain frontend && docker compose --env-file .env.production up -d --no-deps --no-build frontend
curl -fsS --max-time 20 http://127.0.0.1:8080/release.json
```

`--no-deps` 避免重启数据库、后端、worker 或重复运行 migrate。旧前端在构建期间继续服务。
此处的“不停后端”不是无中断保证：前端容器替换期间仍可能有短暂中断，应避开正在录音或提交的测评。

最终镜像已对公开静态目录设置文件 644、目录 755；不会调整 `.env.production`、数据库、录音或模型文件的权限。
新版权限规则写在最终复制 dist 后，正常情况下可复用 Node 依赖和前端构建缓存。

## 涉及数据库的更新

保留必要步骤：校验解压 → 带缓存构建 → 维护窗口停止业务写入 → 一次数据库备份 → 一次显式迁移 → 启动和验收。
不能把它简化成只重建 frontend；不要为了减少命令而省略数据库备份或忽略迁移错误。
不要再单独执行 `build` 后使用 `up --build`；已有镜像应使用 `up --no-build`。
Compose 可能按依赖关系重新检查/运行幂等初始化任务，这是正常情况，不应手动重复触发多轮迁移。

## 磁盘排查与清理边界

磁盘接近满时先停止发起新的构建、大批量训练或导出，不直接删除研究数据。

```bash
df -h /
docker system df
du -xhd1 /opt/metacognition /opt/metacognition-code-backups /opt/metacognition-db-backups /srv/metacognition /var/lib/docker 2>/dev/null
```

这三项只读，不改变磁盘内容；Docker 数据目录若不是 `/var/lib/docker`，可用 `docker info --format '{{.DockerRootDir}}'` 查实际位置。

- 构建缓存：可回收但会影响下次构建速度，应在没有构建任务时评估，优先考虑限定时间/保留量的清理。
- 历史镜像：确认回滚版本后再清理，不执行无差别 `docker system prune -a`，不删除 volumes。
- 历史源码备份、部署 ZIP：确认更新和回滚需求后，仅清理指定旧版本。通常保留当前与最近一次可用回滚版本，不反复复制同一整套源码。
- 导出缓存：先检查是否正在生成/下载，使用应用的导出生命周期处理，不能随意删除仍在使用的文件。
- 数据库、原录音、模型产物及唯一备份：不得自动清理。真实数据持续增长应考虑扩容或将音频迁移到专门存储。

本次没有新增自动删除任务，不会擅自删除服务器上的备份或数据。
