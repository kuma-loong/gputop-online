# Constella 阶段 2.1 落地计划

本文覆盖阶段 2.1 的架构收敛：本机 GPU 采样不再走 manager 内部 collector，而是和远端 GPU 节点一样，通过 `constella agent -> WS /api/agents/ws -> manager ClusterState -> DB/UI/API`。

**目标原则**

本机和远端必须完全一致：

```text
GPU 节点，包括登录节点 H100
  -> constella agent
  -> WS /api/agents/ws
  -> manager ClusterState
  -> DB / UI / API
```

manager 不再直接采本机 GPU。它只负责接收 agent、维护状态、写数据库、提供 API 和前端。

**1. 废弃旧接口**

废弃：

```text
GET /api/snapshot
WS /ws/gpu
```

保留并作为唯一实时数据接口：

```text
GET /api/cluster/snapshot
WS /ws/cluster
WS /api/agents/ws
```

处理策略建议：

- 第一版可以让 `/api/snapshot` 返回 `410 Gone`，明确告诉调用方改用 `/api/cluster/snapshot`。
- `/ws/gpu` 连接直接关闭，关闭原因指向 `/ws/cluster`。
- 不做“旧格式转换”，避免继续维护单机数据模型。

**2. Manager 纯化**

当前 `constella serve` 内部会创建 `SnapshotCollector`，这需要移除或停用。

目标：

```text
constella serve
  - FastAPI
  - ClusterState
  - agent WebSocket ingest
  - DB sink
  - frontend static files
  - settings API
```

不再包含：

```text
SnapshotCollector
NVMLSampler
nvidia-smi fallback
本机 GPU 采样循环
```

这些全部属于 `constella agent`。

**3. 本机 Local Agent**

`./scripts/service/start.sh` 默认启动两个进程：

```text
manager:     constella serve
local agent: constella agent --manager-url ws://127.0.0.1:8765/api/agents/ws
```

建议环境变量：

```bash
LOCAL_AGENT=1              # 默认开启
LOCAL_AGENT=0              # 只启动 manager
LOCAL_AGENT_NODE_ID=H100   # 显式指定本机节点名
AGENT_TOKEN_FILE=run/agent-token
```

如果没提供 `AGENT_TOKEN_FILE`，`start.sh` 可以自动生成 `run/agent-token`，权限 `600`。

**4. 数据库写入**

不新增本机写库路径。

本机 agent 上报后，复用现有逻辑：

```text
agent sample
  -> cluster_state.ingest_sample(...)
  -> accepted == true
  -> db_sink.submit_node_snapshot(runtime.snapshot)
```

这样本机 H100 会自然写入：

```text
nodes
gpus
gpu_metric_samples
process_sessions
process_gpu_usages
raw_snapshots 可选
```

**5. Settings 语义调整**

现在 `/api/settings` 改的是 manager 内部 collector。以后 collector 在 agent 里，所以语义要改成：

```text
/api/settings = manager 下发给 agent 的采样配置
```

至少包括：

```json
{
  "refresh_interval": 1.0,
  "process_interval": 3.0,
  "allowed_refresh_intervals": [0.5, 1.0, 2.0, 5.0]
}
```

第一阶段可以让它影响新连接 agent；更完整的版本应广播 config 给已连接 agent。

**6. 客户端迁移**

当前前端主路径已经用：

```text
/api/cluster/snapshot
/ws/cluster
```

所以主要确认：

- 不再引用 `/api/snapshot`
- 不再引用 `/ws/gpu`
- 节点详情、总览、历史、状态都以 `ClusterSnapshot` 为唯一数据模型

**7. 脚本迁移**

需要同步更新：

```text
scripts/service/start.sh
scripts/service/stop.sh
scripts/service/status.sh
scripts/README.md
README.md
README_zh.md
docs/OPERATIONS.md
docs/DESIGN.md
```

脚本目标：

- `start.sh` 启动 manager 和 local agent。
- `stop.sh` 同时停止 local agent 和 manager。
- `status.sh` 显示 manager 状态、local agent 状态、`/api/cluster/snapshot` 摘要。
- 文档不再推荐 `/api/snapshot` 或 `/ws/gpu`。

**8. 测试矩阵**

需要覆盖：

- `/api/snapshot` 返回废弃状态。
- `/ws/gpu` 不再提供实时数据。
- local agent 通过 `/api/agents/ws` 上报后，`/api/cluster/snapshot` 能看到本机节点。
- 启用 DB sink 后，本机 agent 数据写入 SQLite。
- 远端 agent WebSocket 行为不回退。
- `/api/settings` 不依赖 manager collector。
- service 脚本包含 local agent 启停逻辑。

这个计划的关键点是：**旧接口不是兼容层，而是明确废弃；本机不是特殊 collector，而是标准 agent。**

**9. 本次落地状态**

已实现：

- `constella serve` 不再创建或启动 `SnapshotCollector`。
- `/api/cluster/snapshot` 和 `/ws/cluster` 只读取 `ClusterState` 中的 agent 节点。
- `/api/snapshot` 返回 `410 Gone`，`/ws/gpu` 连接后立即关闭。
- `/api/settings` 保存 manager 侧 agent 配置，并向已连接 agent 广播 `config`。
- 本机 service 脚本默认启动 manager 和 local agent，并自动生成 `run/agent-token`。
- local agent 和远端 agent 共用 `ClusterState.ingest_sample(...)` 与 DB sink 写入路径。
- README、设计文档、运维文档和脚本文档已同步为 cluster API 优先。
