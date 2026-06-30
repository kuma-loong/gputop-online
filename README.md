# Constella

<div align="center" id="constella-badges">

<img src="frontend/public/logo.svg" alt="Constella logo" width="132">

[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-ASGI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![NVIDIA NVML](https://img.shields.io/badge/NVIDIA-NVML-76B900?logo=nvidia&logoColor=white)](https://docs.nvidia.com/deploy/nvml-api/)
[![License](https://img.shields.io/github/license/kuma-loong/Constella)](LICENSE)

</div>

Lightweight realtime NVIDIA GPU monitoring for one server or a small GPU cluster. The backend reads GPU metrics through NVML first and falls back to `nvidia-smi`; in cluster mode, GPU node agents push snapshots back to a manager over WebSocket.

[简体中文](README_zh.md)

## Features

- Selectable global refresh rate: 0.5s, 1s, 2s, or 5s with a single shared backend collector.
- Low overhead: persistent NVML sampler, no per-browser GPU polling, latest state kept in memory.
- Manager-agent cluster mode: the manager can start remote agents over SSH, while agents stream samples back over WebSocket.
- Process list sampled at a lower cadence by default to reduce `/proc` and driver query jitter.
- Per-process task details include user, PID, task name, command line hash, GPU memory, runtime, and process start time when the OS allows reading them.
- `nvidia-smi` fallback when NVML initialization or a sampling call fails.
- Hardware-agnostic NVIDIA dashboard: GPU utilization, memory, power, temperature, clocks, P-state, ECC, MIG, process memory, process runtime, and short history sparklines.
- Optional SQLite history sink for GPU metric samples, rollups, process sessions, and process-GPU usage.
- User-level deployment: no sudo, no system service required.
- Cloudflare Tunnel friendly: keep the service bound to `127.0.0.1` and expose it through a hostname without opening an inbound server port.

## Layout

```text
src/constella/          Python backend, agent, cluster manager, NVML sampler, API/WebSocket
frontend/               Vite + TypeScript frontend
scripts/                user-level setup, service, and tunnel management scripts
docs/                   design and operations notes
tests/                  unit tests
```

## Quick Start

```bash
cd Constella
./scripts/setup.sh
./scripts/start.sh
```

The service listens on `127.0.0.1:8765` by default. Use SSH forwarding from your local machine:

```bash
ssh -N -L 8765:127.0.0.1:8765 <user>@<server>
```

Then open:

```text
http://127.0.0.1:8765
```

## Cluster Mode

Start the manager with an agent token file:

```bash
mkdir -p run
umask 077
printf '%s\n' 'replace-with-a-random-token' > run/agent-token
chmod 600 run/agent-token
AGENT_TOKEN_FILE=run/agent-token ./scripts/start.sh
```

Create `nodes.yaml` from the example and edit hosts/users:

```bash
cp docs/nodes.example.yaml nodes.yaml
```

Start, inspect, and stop remote agents:

```bash
./scripts/start_cluster.sh
./scripts/status_cluster.sh
./scripts/stop_cluster.sh
```

`constella cluster start` uses SSH only for setup/control. The remote agent token is written through stdin into `~/.constella/run/agent.env` with mode `600`; it is not placed on the remote command line.

## Optional History

Enable SQLite history on the manager:

```bash
DB_PATH=run/constella.db RAW_SNAPSHOT_SECONDS=30 ./scripts/start.sh
```

Maintenance commands:

```bash
./scripts/db_maintenance.sh
uv run constella db rollup --path run/constella.db --bucket-seconds 10
uv run constella db prune-raw --path run/constella.db
uv run constella db close-sessions --path run/constella.db
```

## Cloudflare Tunnel

Cloudflare Tunnel is the recommended way to access the dashboard from a domain while keeping the origin service private.

Keep the GPU service bound to localhost:

```bash
HOST=127.0.0.1 PORT=8765 ./scripts/start.sh
```

In Cloudflare Zero Trust, configure the tunnel Public Hostname like this:

```text
Hostname: https://gpu.example.com
Service:  http://127.0.0.1:8765
```

Install `cloudflared` as the current user:

```bash
mkdir -p ~/.local/bin
curl -fL \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
  -o ~/.local/bin/cloudflared
chmod +x ~/.local/bin/cloudflared
~/.local/bin/cloudflared --version
```

Store the token in a local private env file. Do not commit this file:

```bash
mkdir -p run
umask 077
cat > run/cloudflared.env <<'EOF'
CLOUDFLARED_TOKEN='paste-your-token-here'
EOF
chmod 600 run/cloudflared.env
```

Start and inspect the tunnel:

```bash
./scripts/start_tunnel.sh
./scripts/status_tunnel.sh
```

Stop it:

```bash
./scripts/stop_tunnel.sh
```

Security notes:

- The tunnel scripts pass the token through `TUNNEL_TOKEN`, not as a command-line argument, so it does not appear in `ps` output.
- `run/cloudflared.env` should stay mode `600`; `run/` is ignored by git.
- The dashboard exposes usernames and process information. Protect the hostname with Cloudflare Access unless it is intentionally public.
- If a token leaks, rotate it in Cloudflare and update `run/cloudflared.env`.

## Commands

```bash
./scripts/status.sh
./scripts/stop.sh
HOST=127.0.0.1 PORT=8765 REFRESH=1.0 PROCESS_REFRESH=3.0 ./scripts/start.sh
uv run constella probe --pretty
uv run constella agent
uv run constella cluster start --nodes nodes.yaml
uv run constella cluster status --nodes nodes.yaml
uv run constella cluster stop --nodes nodes.yaml
COUNT=20 ./scripts/bench_probe.sh
```

Tunnel commands:

```bash
./scripts/status_tunnel.sh
./scripts/stop_tunnel.sh
./scripts/start_tunnel.sh
```

## API

- `GET /api/health`
- `GET /api/snapshot`
- `GET /api/cluster/snapshot`
- `GET /api/settings`
- `PATCH /api/settings`
- `WS /ws/gpu`
- `WS /ws/cluster`
- `WS /api/agents/ws`
- `GET /api/history/gpu`
- `GET /api/history/tasks`
- `GET /api/users`
- `GET /api/docs`

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
