# GPU Top Online

Lightweight realtime NVIDIA GPU monitoring for a single server. The backend reads GPU metrics through NVML first and falls back to `nvidia-smi`; the frontend receives one-second updates over WebSocket.

[简体中文](README_zh.md)

## Features

- One-second refresh with a single shared backend collector.
- Low overhead: persistent NVML sampler, no per-browser GPU polling, no database.
- Process list sampled at a lower cadence by default to reduce `/proc` and driver query jitter.
- `nvidia-smi` fallback when NVML initialization or a sampling call fails.
- Hardware-agnostic NVIDIA dashboard: GPU utilization, memory, power, temperature, clocks, P-state, ECC, MIG, process memory, process runtime, and short history sparklines.
- User-level deployment: no sudo, no system service required.
- Cloudflare Tunnel friendly: keep the service bound to `127.0.0.1` and expose it through a hostname without opening an inbound server port.

## Layout

```text
src/gputop_online/      Python backend, NVML sampler, nvidia-smi fallback, API/WebSocket
frontend/               Vite + TypeScript frontend
scripts/                user-level setup, service, and tunnel management scripts
docs/                   design and operations notes
tests/                  unit tests
```

## Quick Start

```bash
cd gputop-online
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
uv run gputop-online probe --pretty
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
- `WS /ws/gpu`
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
