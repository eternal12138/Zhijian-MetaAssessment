# Cloudflare Tunnel 公网访问

系统正式域名为 `https://www.21050411.xyz`。当前不启用
Cloudflare Access，访问者仍需使用系统自身账号登录。

## Cloudflare 控制台配置

在 Cloudflare 控制台进入 `Networking > Tunnels`，创建一个
remotely-managed Tunnel，并添加 Published application：

```text
Hostname: www.21050411.xyz
Service:  http://frontend:80
```

这是服务器 Docker Compose 的配置：Cloudflare 容器与前端容器位于同一网络，
浏览器对 `/api` 的同源请求由 Nginx 代理到后端，FastAPI、MySQL 和 ASR Worker
不直接暴露到公网。

## Windows 本机启动

安装 `cloudflared` 并确保它已加入 `PATH`。从 Cloudflare 控制台取得 Tunnel
Token 后，将 Token 单独保存为项目目录之外的纯文本文件。不要把 Token 写入
`.env`、脚本、文档或提交到 Git。

若只在 Windows 本机临时调试，可另建开发用 Published application，将 Service
设为 `http://127.0.0.1:5173`。推荐通过当前用户环境变量指定 Token 文件：

```powershell
$env:CLOUDFLARE_TUNNEL_TOKEN_FILE = "C:\安全目录\cloudflare-tunnel.token"
.\dev.ps1 -EnableTunnel
```

也可以只对本次启动指定文件：

```powershell
.\dev.ps1 -EnableTunnel -TunnelTokenFile "C:\安全目录\cloudflare-tunnel.token"
```

停止项目及由脚本启动的 Tunnel：

```powershell
.\stop.ps1
```

若使用其他子域名，需要同时修改 Cloudflare Published application，并在启动时
传入：

```powershell
.\dev.ps1 -EnableTunnel `
  -TunnelHostname "其他子域名.21050411.xyz" `
  -TunnelTokenFile "C:\安全目录\cloudflare-tunnel.token"
```

## 当前安全边界

由于未启用 Cloudflare Access：

- 任何互联网用户都能打开登录页，但未登录用户不能进入受保护业务页面。
- 必须保持 `ALLOW_PUBLIC_REGISTRATION=false`。
- 教师和管理员账号必须使用独立强密码，不共享账号。
- 正式采集录音前，应检查权限控制、审计记录和数据告知同意流程。
- 不应在路由器或防火墙上直接开放 5173、8000、3306 等端口。

Vite Tunnel 适合开发演示和比赛展示。正式云端部署时，应由 Nginx/Caddy 承载
`frontend/dist` 并反向代理 `/api`，Tunnel 再指向该统一入口。
