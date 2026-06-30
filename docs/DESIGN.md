# 设计说明

## 目标

这套服务面向本机和小规模 GPU 集群的日常占用观察：页面必须实时、信息密度高、开销低，并且能在普通用户权限下长期运行。

## 架构

```mermaid
flowchart LR
  A["NVML sampler<br/>ctypes + libnvidia-ml.so"] --> C["Snapshot collector<br/>0.5s/1s/2s/5s loop"]
  B["nvidia-smi fallback<br/>CSV query"] --> C
  C --> D["FastAPI HTTP<br/>/api/snapshot"]
  C --> E["Local NodeSnapshot wrapper"]
  E --> M["Cluster state<br/>latest by node"]
  A2["Remote agent"] -->|"WS /api/agents/ws"| M
  M --> G["FastAPI HTTP<br/>/api/cluster/snapshot"]
  M --> H["FastAPI WebSocket<br/>/ws/cluster"]
  H --> F["Vite TypeScript UI"]
  M -.optional bounded queue.-> DB["SQLite sink"]
```

单机模式下后端仍然只有一个采样循环。浏览器连接数增加时，不会增加 NVML 调用次数，只会复用 collector 中的最新快照；Web 端切换刷新率时改变的是这个全局采样循环。

集群模式下 manager 维护每个节点的 latest `NodeSnapshot`，再聚合成 `ClusterSnapshot` 推给前端。SSH 只用于安装、写配置、启动、停止和状态查询，不作为实时数据通道；agent 主动通过 WebSocket 回连 manager，不开放入站 HTTP 服务。

## 数据路径

1. 启动时初始化 `NVMLSampler`，加载 `libnvidia-ml.so`。
2. 按全局刷新率读取 GPU 名称、UUID、显存、利用率、温度、功耗、时钟、P-state、Compute Mode、ECC 和 MIG；刷新率可在 Web 端切换为 0.5 秒、1 秒、2 秒或 5 秒。
3. 进程枚举默认每 3 秒执行一次并缓存，实际间隔不低于当前核心刷新率，降低多用户进程查询带来的抖动。
4. 如果 NVML 初始化或单次采样失败，关闭当前 NVML 句柄并执行 `nvidia-smi --query-gpu=... --format=csv,noheader,nounits`。
5. collector 给快照补充序号、当前刷新间隔和 120 点短历史数据。
6. 单机 `Snapshot` 被包装为本地 `NodeSnapshot`，远端 agent 直接上报节点样本。
7. manager 按 `node_id` 维护 latest state，丢弃同节点旧 `seq`，并按本地接收时间标记 stale/offline。
8. WebSocket 客户端收到 `ClusterSnapshot` 后刷新 KPI、节点矩阵、GPU 卡片、任务表和历史曲线。

## 低开销策略

- 不使用 `nvidia-smi -l` 常驻子进程，正常路径不每秒 fork。
- NVML 在服务进程内保持初始化状态，单 collector 串行采样。
- 刷新率是全局运行时设置，浏览器切换不会创建额外 collector。
- 进程列表降频采样，避免 `/proc` 和驱动进程查询影响核心指标刷新。
- 前端不依赖大型图表库，短曲线用 SVG polyline 绘制。
- 后端只保留最近 120 个实时采样点；数据库为可选模块，并通过有界队列异步写入。

## 普通用户权限

部署脚本只使用当前用户目录、`uv`、`npm` 和 `nohup`。不写 `/etc`，不调用 sudo。默认监听 `127.0.0.1`，通过 SSH `-L` 端口转发访问。

## 硬件自适应

项目不假设固定 GPU 数量或型号。GPU 数量、型号、显存、功耗上限、时钟、ECC、MIG 和进程信息都来自本机 NVML 采样结果；NVML 不可用时，再使用 `nvidia-smi --query-gpu` 的 CSV 输出兜底。前端根据集群快照中的节点和 GPU 列表动态生成总览、节点矩阵、卡片和任务表。

## 阶段二数据契约

- `GpuInfo` 增加 `node_id` 和 `gpu_id`；`gpu_id` 默认由 `node_id + gpu uuid` 生成，避免多节点 GPU index 冲突。
- `GpuProcess` 增加 `task_name`、`exe`、`cmdline_hash`、`process_start_time`、`detail_status`，用于任务视图和 session 统计。
- `NodeSnapshot` 表示一个节点的最新状态，包含状态、agent 版本、采样/接收时间和节点 totals。
- `ClusterSnapshot` 由 manager 生成，包含所有节点、集群 totals 和按 `gpu_id` keyed 的短历史曲线。

## 可选数据库

SQLite sink 默认关闭。启用后，实时链路仍然是 `agent sample -> manager latest state -> frontend websocket`；数据库写入走 `manager -> bounded queue -> SQLite writer`。

数据库长期价值围绕任务 session 和 rollup：

- `process_sessions`：用户任务生命周期。
- `process_gpu_usages`：多 GPU 任务与每张 GPU 的显存统计。
- `gpu_metric_samples`：短期原始指标点。
- `gpu_metric_rollups`：降采样曲线。
- `raw_snapshots`：低频调试快照，默认关闭，建议 12 小时保留。

## 参考资料

- NVIDIA NVML API Reference Guide: https://docs.nvidia.com/deploy/nvml-api/index.html
- NVIDIA System Management Interface 文档: https://docs.nvidia.com/deploy/nvidia-smi/index.html
- Grafana dashboard gallery: https://grafana.com/grafana/dashboards/
