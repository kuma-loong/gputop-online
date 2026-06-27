import {
  Activity,
  Clock3,
  Database,
  Gauge,
  ListTree,
  Pause,
  Play,
  RefreshCw,
  Server,
  Thermometer,
  Zap,
  createIcons,
} from "lucide";
import "./styles.css";

const iconSet = {
  Activity,
  Clock3,
  Database,
  Gauge,
  ListTree,
  Pause,
  Play,
  RefreshCw,
  Server,
  Thermometer,
  Zap,
};

type GpuProcess = {
  pid: number;
  name: string;
  gpu_memory_mb: number;
  user?: string | null;
  cmdline?: string | null;
  kind: string;
  runtime_seconds?: number | null;
};

type OtherUserMemory = {
  user: string;
  process_count: number;
  total_memory_mb: number;
  runtime_seconds?: number | null;
};

type GpuInfo = {
  index: number;
  uuid: string;
  name: string;
  pci_bus_id?: string | null;
  utilization_gpu: number;
  utilization_mem: number;
  memory_total_mb: number;
  memory_used_mb: number;
  memory_free_mb: number;
  memory_percent: number;
  temperature_c: number;
  power_watts: number;
  power_limit_watts: number;
  power_percent: number;
  clock_sm_mhz?: number | null;
  clock_mem_mhz?: number | null;
  max_clock_sm_mhz?: number | null;
  max_clock_mem_mhz?: number | null;
  pstate?: string | null;
  compute_mode?: string | null;
  mig_mode?: string | null;
  ecc_mode?: string | null;
  processes: GpuProcess[];
  other_users: OtherUserMemory[];
  error?: string | null;
};

type Snapshot = {
  ok: boolean;
  source: string;
  hostname?: string;
  timestamp?: number;
  elapsed_ms?: number;
  driver_version?: string | null;
  cuda_driver_version?: string | null;
  nvml_version?: string | null;
  error?: string | null;
  seq: number;
  refresh_interval?: number;
  totals: {
    gpu_count: number;
    avg_gpu_utilization: number;
    avg_memory_utilization: number;
    memory_used_mb: number;
    memory_total_mb: number;
    power_watts: number;
    power_limit_watts: number;
    max_temperature_c: number;
    active_processes: number;
  };
  gpus: GpuInfo[];
  history: Record<string, Record<string, number[]>>;
};

const summaryGrid = mustGet<HTMLElement>("summaryGrid");
const gpuGrid = mustGet<HTMLElement>("gpuGrid");
const fabricBand = mustGet<HTMLElement>("fabricBand");
const processRows = mustGet<HTMLElement>("processRows");
const processMeta = mustGet<HTMLElement>("processMeta");
const liveState = mustGet<HTMLElement>("liveState");
const nodeLine = mustGet<HTMLElement>("nodeLine");
const pauseButton = mustGet<HTMLButtonElement>("pauseButton");
const refreshButton = mustGet<HTMLButtonElement>("refreshButton");

let socket: WebSocket | null = null;
let reconnectTimer = 0;
let paused = false;
let lastSnapshot: Snapshot | null = null;

pauseButton.addEventListener("click", () => {
  paused = !paused;
  pauseButton.innerHTML = paused ? icon("play") : icon("pause");
  pauseButton.setAttribute("aria-label", paused ? "Resume stream" : "Pause stream");
  pauseButton.setAttribute("title", paused ? "Resume stream" : "Pause stream");
  setLiveState(paused ? "paused" : socket?.readyState === WebSocket.OPEN ? "live" : "connecting");
  createIcons({ icons: iconSet });
});

refreshButton.addEventListener("click", () => {
  fetchSnapshot();
});

connect();
fetchSnapshot();
createIcons({ icons: iconSet });

function mustGet<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) {
    throw new Error(`Missing element: ${id}`);
  }
  return element as T;
}

function connect() {
  window.clearTimeout(reconnectTimer);
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${window.location.host}/ws/gpu`);
  setLiveState("connecting");

  socket.addEventListener("open", () => {
    setLiveState(paused ? "paused" : "live");
  });

  socket.addEventListener("message", (event) => {
    const snapshot = JSON.parse(event.data) as Snapshot;
    lastSnapshot = snapshot;
    if (!paused) {
      render(snapshot);
    }
  });

  socket.addEventListener("close", () => {
    setLiveState("offline");
    reconnectTimer = window.setTimeout(connect, 1200);
  });

  socket.addEventListener("error", () => {
    setLiveState("offline");
  });
}

async function fetchSnapshot() {
  try {
    const response = await fetch("/api/snapshot", { cache: "no-store" });
    const snapshot = (await response.json()) as Snapshot;
    lastSnapshot = snapshot;
    render(snapshot);
  } catch {
    setLiveState("offline");
  }
}

function render(snapshot: Snapshot) {
  renderHeader(snapshot);
  renderSummary(snapshot);
  renderFabric(snapshot);
  renderGpuGrid(snapshot);
  renderProcesses(snapshot);
  createIcons({ icons: iconSet });
}

function renderHeader(snapshot: Snapshot) {
  const host = snapshot.hostname || "unknown-host";
  const driver = snapshot.driver_version ? `driver ${snapshot.driver_version}` : "driver unknown";
  const cuda = snapshot.cuda_driver_version ? `cuda ${snapshot.cuda_driver_version}` : "cuda unknown";
  const source = snapshot.source || "none";
  const interval = snapshot.refresh_interval ? `${snapshot.refresh_interval.toFixed(1)}s` : "1.0s";
  const latency = typeof snapshot.elapsed_ms === "number" ? `${snapshot.elapsed_ms.toFixed(1)} ms` : "n/a";
  nodeLine.textContent = `${host} · ${source.toUpperCase()} · ${driver} · ${cuda} · ${interval} · ${latency}`;
  setLiveState(paused ? "paused" : snapshot.ok ? "live" : "error");
}

function renderSummary(snapshot: Snapshot) {
  const totals = snapshot.totals;
  summaryGrid.innerHTML = [
    metricCard("activity", "GPU Avg", `${fmtPct(totals.avg_gpu_utilization)}`, "load", totals.avg_gpu_utilization, "green"),
    metricCard(
      "database",
      "HBM Used",
      `${fmtGiB(totals.memory_used_mb)} / ${fmtGiB(totals.memory_total_mb)}`,
      fmtPct(totals.avg_memory_utilization),
      totals.avg_memory_utilization,
      "cyan",
    ),
    metricCard(
      "zap",
      "Power",
      `${totals.power_watts.toFixed(0)} W / ${totals.power_limit_watts.toFixed(0)} W`,
      totals.power_limit_watts ? fmtPct((totals.power_watts / totals.power_limit_watts) * 100) : "n/a",
      totals.power_limit_watts ? (totals.power_watts / totals.power_limit_watts) * 100 : 0,
      "amber",
    ),
    metricCard("thermometer", "Max Temp", `${totals.max_temperature_c}°C`, "hotspot", Math.min(100, (totals.max_temperature_c / 90) * 100), "red"),
    metricCard("list-tree", "Processes", `${totals.active_processes}`, `${totals.gpu_count} GPUs`, 100, "violet"),
  ].join("");
}

function renderFabric(snapshot: Snapshot) {
  const modelLabel = summarizeGpuModels(snapshot.gpus);
  const label = `${snapshot.totals.gpu_count} GPU node`;
  const chips = snapshot.gpus
    .map(
      (gpu) => `
        <div class="fabric-chip ${statusClass(gpu.utilization_gpu)}">
          <span>GPU${gpu.index}</span>
          <strong>${Math.round(gpu.utilization_gpu)}%</strong>
          <small>${fmtGiB(gpu.memory_used_mb)}</small>
        </div>
      `,
    )
    .join("");
  fabricBand.innerHTML = `
    <div class="fabric-copy">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(modelLabel)}</strong>
    </div>
    <div class="fabric-grid">${chips}</div>
  `;
}

function renderGpuGrid(snapshot: Snapshot) {
  if (!snapshot.gpus.length) {
    gpuGrid.innerHTML = `<div class="empty-panel">${escapeHtml(snapshot.error || "No GPU snapshot available")}</div>`;
    return;
  }
  gpuGrid.innerHTML = snapshot.gpus.map((gpu) => gpuCard(gpu, snapshot.history[String(gpu.index)] || {})).join("");
}

function gpuCard(gpu: GpuInfo, history: Record<string, number[]>) {
  const subtitle = [
    gpu.pstate,
    gpu.compute_mode,
    gpu.mig_mode ? `MIG ${gpu.mig_mode}` : null,
    gpu.ecc_mode ? `ECC ${gpu.ecc_mode}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const clock = [
    gpu.clock_sm_mhz ? `SM ${gpu.clock_sm_mhz} MHz` : null,
    gpu.clock_mem_mhz ? `MEM ${gpu.clock_mem_mhz} MHz` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return `
    <article class="gpu-card">
      <div class="gpu-head">
        <div>
          <span class="gpu-index">GPU ${gpu.index}</span>
          <h3>${escapeHtml(compactGpuName(gpu.name))}</h3>
          <p>${escapeHtml(subtitle || gpu.uuid)}</p>
        </div>
        <div class="temp-badge ${tempClass(gpu.temperature_c)}">${gpu.temperature_c}°C</div>
      </div>

      <div class="spark-wrap">
        ${sparkline(history.gpu || [], "var(--green)", 100)}
      </div>

      <div class="bar-stack">
        ${bar("GPU", gpu.utilization_gpu, `${fmtPct(gpu.utilization_gpu)}`, "green")}
        ${bar("HBM", gpu.memory_percent, `${fmtGiB(gpu.memory_used_mb)} / ${fmtGiB(gpu.memory_total_mb)}`, "cyan")}
        ${bar("Power", gpu.power_percent, `${gpu.power_watts.toFixed(0)} / ${gpu.power_limit_watts.toFixed(0)} W`, "amber")}
      </div>

      <div class="mini-stats">
        <span><i data-lucide="gauge"></i>${fmtPct(gpu.utilization_mem)} mem util</span>
        <span><i data-lucide="clock-3"></i>${escapeHtml(clock || "clock n/a")}</span>
      </div>
    </article>
  `;
}

function renderProcesses(snapshot: Snapshot) {
  type Row = {
    gpu: number;
    user: string;
    pid: string;
    name: string;
    memory: number;
    runtime: number | null;
    kind: string;
    title: string;
  };

  const rows: Row[] = [];
  for (const gpu of snapshot.gpus) {
    for (const process of gpu.processes || []) {
      rows.push({
        gpu: gpu.index,
        user: process.user || "self",
        pid: String(process.pid),
        name: process.name,
        memory: process.gpu_memory_mb,
        runtime: process.runtime_seconds ?? null,
        kind: process.kind,
        title: process.cmdline || process.name,
      });
    }
    for (const other of gpu.other_users || []) {
      rows.push({
        gpu: gpu.index,
        user: other.user,
        pid: `${other.process_count} procs`,
        name: "other user workload",
        memory: other.total_memory_mb,
        runtime: other.runtime_seconds ?? null,
        kind: "aggregate",
        title: `${other.process_count} processes`,
      });
    }
  }

  rows.sort((a, b) => a.gpu - b.gpu || b.memory - a.memory || (b.runtime || 0) - (a.runtime || 0));
  processMeta.textContent = `${rows.length} visible`;
  if (!rows.length) {
    processRows.innerHTML = `<tr><td colspan="7" class="empty">no active compute processes</td></tr>`;
    return;
  }

  processRows.innerHTML = rows
    .slice(0, 32)
    .map(
      (row) => `
      <tr title="${escapeAttr(row.title)}">
        <td><span class="gpu-pill">GPU${row.gpu}</span></td>
        <td>${escapeHtml(row.user)}</td>
        <td>${escapeHtml(row.pid)}</td>
        <td>${escapeHtml(row.name)}</td>
        <td>${fmtGiB(row.memory)}</td>
        <td>${fmtDuration(row.runtime)}</td>
        <td>${escapeHtml(row.kind)}</td>
      </tr>
    `,
    )
    .join("");
}

function metricCard(iconName: string, label: string, value: string, meta: string, percent: number, tone: string) {
  return `
    <article class="metric-card tone-${tone}">
      <div class="metric-icon">${icon(iconName)}</div>
      <div>
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(value)}</strong>
        <small>${escapeHtml(meta)}</small>
      </div>
      <div class="metric-rail"><span style="width:${clamp(percent)}%"></span></div>
    </article>
  `;
}

function bar(label: string, value: number, meta: string, tone: string) {
  return `
    <div class="bar-row tone-${tone}">
      <div class="bar-label">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(meta)}</strong>
      </div>
      <div class="bar-track"><span style="width:${clamp(value)}%"></span></div>
    </div>
  `;
}

function sparkline(values: number[], color: string, max: number) {
  const width = 180;
  const height = 46;
  if (values.length < 2) {
    return `<svg class="spark" viewBox="0 0 ${width} ${height}" role="img" aria-label="GPU history"></svg>`;
  }
  const points = values
    .map((value, index) => {
      const x = (index / Math.max(1, values.length - 1)) * width;
      const y = height - (clamp(value) / max) * (height - 6) - 3;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return `
    <svg class="spark" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="GPU history">
      <polyline points="${points}" style="stroke:${color}"></polyline>
    </svg>
  `;
}

function setLiveState(state: "connecting" | "live" | "paused" | "offline" | "error") {
  liveState.className = `live-pill is-${state}`;
  liveState.innerHTML = `<span></span>${state}`;
}

function icon(name: string) {
  return `<i data-lucide="${name}"></i>`;
}

function compactGpuName(name: string) {
  return name.replace(/^NVIDIA\s+/, "");
}

function summarizeGpuModels(gpus: GpuInfo[]) {
  if (!gpus.length) {
    return "No GPU detected";
  }
  const counts = new Map<string, number>();
  for (const gpu of gpus) {
    counts.set(gpu.name, (counts.get(gpu.name) || 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([name, count]) => `${count}x ${name.replace(/^NVIDIA\s+/, "")}`)
    .join(" · ");
}

function fmtGiB(mib: number) {
  if (!Number.isFinite(mib)) {
    return "n/a";
  }
  return `${(mib / 1024).toFixed(mib >= 10240 ? 1 : 2)} GiB`;
}

function fmtPct(value: number) {
  if (!Number.isFinite(value)) {
    return "n/a";
  }
  return `${value.toFixed(value % 1 ? 1 : 0)}%`;
}

function fmtDuration(seconds: number | null) {
  if (seconds === null || !Number.isFinite(seconds)) {
    return "n/a";
  }
  if (seconds < 60) {
    return `${Math.max(0, Math.floor(seconds))}s`;
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return `${minutes}m ${Math.floor(seconds % 60)}s`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${hours}h ${minutes % 60}m`;
  }
  const days = Math.floor(hours / 24);
  return `${days}d ${hours % 24}h`;
}

function clamp(value: number) {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, value));
}

function statusClass(value: number) {
  if (value >= 80) return "is-hot";
  if (value >= 35) return "is-active";
  return "is-idle";
}

function tempClass(value: number) {
  if (value >= 80) return "is-hot";
  if (value >= 65) return "is-warm";
  return "is-cool";
}

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (char) => {
    const map: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    };
    return map[char] || char;
  });
}

function escapeAttr(value: string) {
  return escapeHtml(value).replace(/\n/g, " ");
}
