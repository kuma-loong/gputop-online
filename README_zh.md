# GPU Top Online

一个普通用户级的 NVIDIA GPU 实时监控服务。后端优先使用 NVML API 采集，失败时使用 `nvidia-smi` 兜底；前端通过 WebSocket 每秒刷新，适合在服务器上后台运行后用 SSH 端口转发或 Cloudflare Tunnel 访问。

## 功能

- 1 秒刷新：单个后台 collector 采样，多个浏览器共享快照，避免重复访问 GPU 驱动。
- 低抖动进程采样：核心 GPU 指标每秒刷新，进程列表默认每 3 秒刷新一次。
- NVML 优先：直接通过 `ctypes` 调用 `libnvidia-ml.so`，无需 sudo，无需在系统安装 Python 包。
- `nvidia-smi` 兜底：NVML 初始化失败或权限受限时仍能显示 GPU 基础指标。
- 硬件自适应：自动解析本机 NVIDIA GPU 数量和型号，展示 GPU 利用率、显存、功耗、温度、时钟、P-state、ECC、MIG、进程占用、运行时间和短历史曲线。
- 单服务部署：FastAPI 同时提供 API、WebSocket 和静态前端。
- Cloudflare Tunnel 支持：服务可继续监听 `127.0.0.1`，不暴露服务器端口。

## 项目结构

```text
src/gputop_online/      Python 后端、NVML 采样、nvidia-smi 兜底、WebSocket
frontend/               Vite + TypeScript 前端
scripts/                普通用户级安装、启动、停止、状态检查脚本
docs/                   设计和运维文档
tests/                  单元测试
```

## 快速部署

```bash
cd gputop-online
./scripts/setup.sh
./scripts/start.sh
```

默认监听 `127.0.0.1:8765`。在本地电脑执行：

```bash
ssh -N -L 8765:127.0.0.1:8765 <user>@<server>
```

然后打开 `http://127.0.0.1:8765`。

## Cloudflare Tunnel 部署

推荐用 Cloudflare Tunnel 暴露域名访问，同时让 GPU 服务继续只监听本机地址：

```bash
HOST=127.0.0.1 PORT=8765 ./scripts/start.sh
```

Cloudflare 后台的 Public Hostname 配置：

```text
Hostname: https://gpu.example.com
Service:  http://127.0.0.1:8765
```

普通用户安装 `cloudflared`：

```bash
mkdir -p ~/.local/bin
curl -fL \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
  -o ~/.local/bin/cloudflared
chmod +x ~/.local/bin/cloudflared
~/.local/bin/cloudflared --version
```

保存 token 到本地私有文件。不要提交这个文件：

```bash
mkdir -p run
umask 077
cat > run/cloudflared.env <<'EOF'
CLOUDFLARED_TOKEN='paste-your-token-here'
EOF
chmod 600 run/cloudflared.env
```

启动和检查 Tunnel：

```bash
./scripts/start_tunnel.sh
./scripts/status_tunnel.sh
```

停止 Tunnel：

```bash
./scripts/stop_tunnel.sh
```

安全建议：

- 不要把 token 放在命令行参数中；脚本会通过 `TUNNEL_TOKEN` 环境变量传给 `cloudflared`，避免 token 出现在 `ps` 输出。
- `run/cloudflared.env` 权限应为 `600`，且 `run/` 已被 `.gitignore` 排除。
- GPU 面板包含用户名和进程信息，建议在 Cloudflare Zero Trust 里给域名加 Access 登录策略。
- 如果 token 泄露，应在 Cloudflare 后台重新生成 token，并更新 `run/cloudflared.env`。

## 常用命令

```bash
./scripts/status.sh
./scripts/stop.sh
HOST=127.0.0.1 PORT=8765 REFRESH=1.0 PROCESS_REFRESH=3.0 ./scripts/start.sh
uv run gputop-online probe --pretty
COUNT=20 ./scripts/bench_probe.sh
```

Tunnel 命令：

```bash
./scripts/status_tunnel.sh
./scripts/stop_tunnel.sh
./scripts/start_tunnel.sh
```

## API

- `GET /api/health`：服务健康状态。
- `GET /api/snapshot`：当前 GPU 快照。
- `WS /ws/gpu`：实时快照流。
- `GET /api/docs`：FastAPI OpenAPI 文档。

## 开发

```bash
uv sync
uv run pytest

cd frontend
npm install
npm run build
```

前端开发模式：

```bash
cd frontend
npm run dev
```

生产服务依赖 `frontend/dist`，执行 `npm run build` 后由 FastAPI 直接托管。
