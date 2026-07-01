# Constella

一个普通用户级的 NVIDIA GPU 实时监控服务，支持本机和轻量集群模式。所有 GPU 节点，包括启用本机监控时的 manager 主机，都走同一条 agent 路径：NVML 优先、`nvidia-smi` 兜底、WebSocket 上报到 manager。

## 功能

- 可选 agent 刷新率：支持 0.5 秒、1 秒、2 秒、5 秒，由 manager 下发给已连接 agent。
- 低开销采样：每个 GPU 节点 agent 只有一个常驻采样器，多个浏览器共享 manager 内存中的最新快照，避免重复访问 GPU 驱动。
- 集群 manager-agent 模式：manager 通过 SSH 启动远端 agent，agent 通过 WebSocket 持续回传节点快照。
- 集群前端路径：`/overview` 展示集群 totals 和按节点拆分的 fabric 卡片，`/nodes/<node_id>` 展示该节点的 GPU 卡片和任务表。
- 低抖动进程采样：核心 GPU 指标按当前刷新率更新，进程列表默认每 3 秒刷新一次。
- NVML 优先：直接通过 `ctypes` 调用 `libnvidia-ml.so`，无需 sudo，无需在系统安装 Python 包。
- `nvidia-smi` 兜底：NVML 初始化失败或权限受限时仍能显示 GPU 基础指标。
- 进程明细：尽力展示用户、PID、任务名、命令行哈希、GPU 显存、运行时间和进程启动时间。
- 硬件自适应：自动解析本机 NVIDIA GPU 数量和型号，展示 GPU 利用率、显存、功耗、温度、时钟、P-state、ECC、MIG、进程占用、运行时间和短历史曲线。
- 可选 SQLite 历史模块：记录 GPU rollup、任务 session 和任务-GPU 使用关系，详见 [SQLite 历史库](docs/HISTORY.md)。
- 单服务部署：FastAPI 同时提供 API、WebSocket 和静态前端。
- 可选 Cloudflare Tunnel 部署：服务可继续监听 `127.0.0.1`，不暴露服务器端口，详见 [Cloudflare Tunnel](docs/CLOUD_TUNNEL.md)。

## 项目结构

```text
src/constella/          Python 后端、agent、cluster manager、NVML 采样、WebSocket
frontend/               Vite + TypeScript 前端
scripts/                按 service、cluster、tunnel、maintenance、dev 分类的脚本
docs/                   设计和运维文档
tests/                  单元测试
```

## 快速部署

```bash
cd Constella
./scripts/service/setup.sh
./scripts/service/start.sh
```

默认会同时启动 manager 和本机 GPU agent。manager 监听 `127.0.0.1:8765`，本机 agent 连接 `ws://127.0.0.1:8765/api/agents/ws`。在本地电脑执行：

```bash
ssh -N -L 8765:127.0.0.1:8765 <user>@<server>
```

然后打开 `http://127.0.0.1:8765/overview`。

如果这台机器只作为 manager，不采集本机 GPU：

```bash
LOCAL_AGENT=0 ./scripts/service/start.sh
```

## 集群模式

本机 agent 开启时，`scripts/service/start.sh` 会自动创建 `run/agent-token`。如需使用指定 token 文件：

```bash
mkdir -p run
umask 077
printf '%s\n' 'replace-with-a-random-token' > run/agent-token
chmod 600 run/agent-token
AGENT_TOKEN_FILE=run/agent-token ./scripts/service/start.sh
```

复制示例节点清单并编辑主机名和用户：

```bash
cp docs/nodes.example.yaml nodes.yaml
```

`manager_hostname` 用来配置 manager 主机本机 agent 在页面上的显示名。`scripts/service/start.sh` 会把它作为默认 `LOCAL_AGENT_NODE_ID`。

启动、查看和停止远端 agent：

```bash
./scripts/cluster/start.sh
./scripts/cluster/status.sh
./scripts/cluster/stop.sh
```

`constella cluster start` 只把 SSH 用作安装、写配置和启停控制。agent token 通过 stdin 写入远端 `~/.constella/run/agent.env`，权限为 `600`，不会出现在远端命令行参数中。

远端 GPU 节点不需要安装 `uv`。manager 会在本地构建最小 agent runtime，只同步 agent 侧需要的 Constella 模块和 `websockets`，远端启动脚本使用 `python3 -m constella.agent_main` 运行。

## 可选组件

- SQLite 历史库默认关闭，只在需要持久化 GPU/任务历史时启用。配置和维护见 [SQLite 历史库](docs/HISTORY.md)。
- Cloudflare Tunnel 是可选部署方式，用于在不开放服务器入站端口的情况下绑定域名访问。配置见 [Cloudflare Tunnel](docs/CLOUD_TUNNEL.md)。

## 常用命令

```bash
./scripts/service/status.sh
./scripts/service/stop.sh
HOST=127.0.0.1 PORT=8765 REFRESH=1.0 PROCESS_REFRESH=3.0 ./scripts/service/start.sh
LOCAL_AGENT=0 ./scripts/service/start.sh
uv run constella probe --pretty
uv run constella agent
uv run constella cluster start --nodes nodes.yaml
uv run constella cluster status --nodes nodes.yaml
uv run constella cluster stop --nodes nodes.yaml
COUNT=20 ./scripts/dev/bench_probe.sh
```

## API

- `GET /api/health`：服务健康状态。
- `GET /api/cluster/snapshot`：当前集群快照。
- `GET /api/settings`：当前运行时设置。
- `PATCH /api/settings`：更新全局刷新率。
- `WS /ws/cluster`：实时集群快照流。
- `WS /api/agents/ws`：agent 上报通道。
- `GET /api/history/gpu`：可选 GPU 历史指标。
- `GET /api/history/tasks`：可选任务历史。
- `GET /api/users`：可选用户任务聚合。
- `GET /api/docs`：FastAPI OpenAPI 文档。

旧单机接口不再作为兼容层维护：`GET /api/snapshot` 返回 `410 Gone`，`WS /ws/gpu` 会立即关闭。本机和远端节点都统一使用 cluster API。

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
