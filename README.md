# Constella

<div align="center" id="constella-badges">

<img src="frontend/public/logo.svg" alt="Constella logo" width="132">

[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-ASGI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![NVIDIA NVML](https://img.shields.io/badge/NVIDIA-NVML-76B900?logo=nvidia&logoColor=white)](https://docs.nvidia.com/deploy/nvml-api/)
[![License](https://img.shields.io/github/license/kuma-loong/Constella)](LICENSE)

</div>

Lightweight realtime NVIDIA GPU monitoring for one server or a small GPU cluster. Every GPU node, including the manager host when local monitoring is enabled, runs the same agent path: NVML first, `nvidia-smi` fallback, WebSocket sample ingest into the manager.

[简体中文](README_zh.md)

## Features

- Selectable agent refresh rate: 0.5s, 1s, 2s, or 5s, broadcast by the manager to connected agents.
- Low overhead: one persistent sampler per GPU node agent, no per-browser GPU polling, latest state kept in memory.
- Manager-agent cluster mode: the manager can start remote agents over SSH, while agents stream samples back over WebSocket.
- Cluster UI routes: `/overview` shows cluster totals and one fabric card per node; `/nodes/<node_id>` shows that node's GPUs and tasks.
- Process list sampled at a lower cadence by default to reduce `/proc` and driver query jitter.
- Per-process task details include user, PID, task name, command line hash, GPU memory, runtime, and process start time when the OS allows reading them.
- `nvidia-smi` fallback when NVML initialization or a sampling call fails.
- Hardware-agnostic NVIDIA dashboard: GPU utilization, memory, power, temperature, clocks, P-state, ECC, MIG, process memory, process runtime, and short history sparklines.
- Optional SQLite history sink for GPU metric rollups, process sessions, and process-GPU usage. See [SQLite History](docs/HISTORY.md).
- User-level deployment: no sudo, no system service required.
- Optional Cloudflare Tunnel deployment keeps the service bound to `127.0.0.1` while exposing it through a hostname. See [Cloudflare Tunnel](docs/CLOUD_TUNNEL.md).

## Layout

```text
src/constella/          Python backend, agent, cluster manager, NVML sampler, API/WebSocket
frontend/               Vite + TypeScript frontend
scripts/                categorized service, cluster, tunnel, maintenance, and dev scripts
docs/                   design and operations notes
tests/                  unit tests
```

## Quick Start

```bash
cd Constella
./scripts/service/setup.sh
./scripts/service/start.sh
```

By default this starts both the manager and a local GPU agent. The manager listens on `127.0.0.1:8765`; the local agent connects back to `ws://127.0.0.1:8765/api/agents/ws`. Use SSH forwarding from your local machine:

```bash
ssh -N -L 8765:127.0.0.1:8765 <user>@<server>
```

Then open:

```text
http://127.0.0.1:8765/overview
```

Set `LOCAL_AGENT=0` when the host should run only the manager:

```bash
LOCAL_AGENT=0 ./scripts/service/start.sh
```

## Cluster Mode

`scripts/service/start.sh` creates `run/agent-token` automatically when the local agent is enabled. To provide your own token file:

```bash
mkdir -p run
umask 077
printf '%s\n' 'replace-with-a-random-token' > run/agent-token
chmod 600 run/agent-token
AGENT_TOKEN_FILE=run/agent-token ./scripts/service/start.sh
```

Create `nodes.yaml` from the example and edit hosts/users:

```bash
cp docs/nodes.example.yaml nodes.yaml
```

Set `manager_hostname` to the local manager-host agent label you want in the UI. `scripts/service/start.sh` uses it as the default `LOCAL_AGENT_NODE_ID`.

Start, inspect, and stop remote agents:

```bash
./scripts/cluster/start.sh
./scripts/cluster/status.sh
./scripts/cluster/stop.sh
```

`constella cluster start` uses SSH only for setup/control. The remote agent token is written through stdin into `~/.constella/run/agent.env` with mode `600`; it is not placed on the remote command line.

Remote GPU nodes do not need `uv`. The manager builds a minimal agent runtime bundle locally and syncs only the agent-side Constella modules plus `websockets`; the remote start script runs it with `python3 -m constella.agent_main`.

## Optional Components

- SQLite history is disabled by default. Enable it only when persisted GPU/task history is needed: [SQLite History](docs/HISTORY.md).
- Cloudflare Tunnel is an optional deployment path for domain access without opening an inbound server port: [Cloudflare Tunnel](docs/CLOUD_TUNNEL.md).

## Commands

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

- `GET /api/health`
- `GET /api/cluster/snapshot`
- `GET /api/settings`
- `PATCH /api/settings`
- `WS /ws/cluster`
- `WS /api/agents/ws`
- `GET /api/history/gpu`
- `GET /api/history/tasks`
- `GET /api/users`
- `GET /api/docs`

Deprecated single-node endpoints are intentionally not compatibility layers: `GET /api/snapshot` returns `410 Gone`, and `WS /ws/gpu` closes immediately. Use the cluster API for local and remote nodes.

## Development

```bash
uv sync
uv run pytest

cd frontend
npm install
npm run build
```

Frontend dev server:

```bash
cd frontend
npm run dev
```

For production, build `frontend/dist`; FastAPI serves the static frontend directly.
