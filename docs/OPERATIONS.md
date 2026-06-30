# 运维手册

## 安装

```bash
cd Constella
./scripts/setup.sh
```

## 后台启动

```bash
./scripts/start.sh
```

可配置项：

```bash
HOST=127.0.0.1 PORT=8765 REFRESH=1.0 PROCESS_REFRESH=3.0 ./scripts/start.sh
```

集群 manager 可额外配置：

```bash
AGENT_TOKEN_FILE=run/agent-token ./scripts/start.sh
DB_PATH=run/constella.db RAW_SNAPSHOT_SECONDS=30 ./scripts/start.sh
```

日志写入 `logs/constella.log`，PID 写入 `run/constella.pid`。

## 访问

推荐只绑定本机地址，通过 SSH 转发：

```bash
ssh -N -L 8765:127.0.0.1:8765 <user>@<server>
```

浏览器访问：

```text
http://127.0.0.1:8765
```

## 集群 agent 管理

准备 manager agent token：

```bash
mkdir -p run
umask 077
printf '%s\n' 'replace-with-a-random-token' > run/agent-token
chmod 600 run/agent-token
AGENT_TOKEN_FILE=run/agent-token ./scripts/start.sh
```

准备节点清单：

```bash
cp docs/nodes.example.yaml nodes.yaml
```

`nodes.yaml` 中的 `manager_url` 必须是 GPU 节点能访问到的 manager WebSocket 地址，例如：

```text
ws://manager-host:8765/api/agents/ws
```

启动、状态、停止：

```bash
./scripts/start_cluster.sh
./scripts/status_cluster.sh
./scripts/stop_cluster.sh
```

重复执行 `start_cluster.sh` 是幂等的：远端 pid 存活时返回 running；pid 过期时清理后重启。

普通用户部署限制：

- 不使用 sudo，不写 `/etc`，不安装 system service。
- agent 默认写入 `~/.constella/run/agent.pid`、`~/.constella/logs/agent.log`、`~/.constella/run/agent-state.json`。
- 节点重启后 agent 不保证自动恢复；重新执行 `./scripts/start_cluster.sh` 即可。
- token 通过 stdin 写入远端 env 文件，不放在 SSH 命令行参数中。

## 可选 SQLite 历史库

启用：

```bash
DB_PATH=run/constella.db RAW_SNAPSHOT_SECONDS=30 ./scripts/start.sh
```

维护：

```bash
./scripts/db_maintenance.sh
```

可调参数：

```bash
DB_PATH=run/constella.db \
ROLLUP_BUCKET_SECONDS=10 \
RAW_RETENTION_SECONDS=43200 \
SESSION_STALE_SECONDS=300 \
./scripts/db_maintenance.sh
```

数据库写入走有界后台队列。实时面板依赖 manager 内存 latest state，数据库慢或关闭时不影响实时 WebSocket 推送。

## Cloudflare Tunnel

如果要通过 Cloudflare 托管的域名访问，推荐使用 Cloudflare Tunnel。这样 GPU 服务仍然只监听 `127.0.0.1:8765`，服务器不需要开放入站端口。

### Cloudflare 后台配置

在 Cloudflare Zero Trust 的 Tunnels 页面为该 Tunnel 添加 Public Hostname：

```text
Hostname: https://gpu.example.com
Service:  http://127.0.0.1:8765
```

如果页面需要保护，给这个 hostname 加 Cloudflare Access 策略，例如只允许指定邮箱登录。

### 安装 cloudflared

普通用户安装到 `~/.local/bin`：

```bash
mkdir -p ~/.local/bin
curl -fL \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
  -o ~/.local/bin/cloudflared
chmod +x ~/.local/bin/cloudflared
~/.local/bin/cloudflared --version
```

### 保存 token

将 Cloudflare 后台给出的 token 保存到本地私有文件：

```bash
mkdir -p run
umask 077
cat > run/cloudflared.env <<'EOF'
CLOUDFLARED_TOKEN='paste-your-token-here'
EOF
chmod 600 run/cloudflared.env
```

不要把 token 写入仓库。`run/` 已被 `.gitignore` 排除。

### 启停和状态

```bash
./scripts/start_tunnel.sh
./scripts/status_tunnel.sh
./scripts/stop_tunnel.sh
```

`start_tunnel.sh` 会通过 `TUNNEL_TOKEN` 环境变量传 token，避免 token 出现在 `ps` 的命令行参数中。日志写入 `logs/cloudflared.log`，PID 写入 `run/cloudflared.pid`。

### 安全注意事项

- GPU 面板包含用户名和进程信息，建议使用 Cloudflare Access。
- 如果 token 曾经出现在聊天、日志或命令行历史中，应在 Cloudflare 后台重新生成并更新 `run/cloudflared.env`。
- 保持 GPU 服务监听 `127.0.0.1`，不要在不需要时绑定 `0.0.0.0`。

## 状态、停止、重启

```bash
./scripts/status.sh
./scripts/stop.sh
./scripts/start.sh
```

## 验证采样

```bash
uv run constella probe --pretty
COUNT=20 ./scripts/bench_probe.sh
```

正常情况下 `probe` 的 `source` 为 `nvml`。如果为 `nvidia-smi`，说明 NVML 路径失败但兜底仍可用；查看 `logs/constella.log` 中的警告。

## 验证集群 API

```bash
curl -s http://127.0.0.1:8765/api/cluster/snapshot
curl -s http://127.0.0.1:8765/api/history/gpu
```

未启用数据库时，历史 API 返回：

```json
{"enabled":false,"items":[]}
```
