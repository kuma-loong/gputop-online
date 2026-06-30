from __future__ import annotations

import subprocess
from pathlib import Path

from constella.cluster_control import (
    AGENT_RUNTIME_MODULES,
    ClusterConfig,
    ClusterController,
    ClusterNode,
    CommandRunner,
    load_cluster_config,
    load_manager_hostname,
    prepare_agent_runtime,
    render_agent_env,
    render_start_script,
    ssh_command,
)


class FakeRunner(CommandRunner):
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.inputs: list[str | None] = []

    def run(
        self,
        cmd: list[str],
        *,
        input_text: str | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(cmd)
        self.inputs.append(input_text)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    def pipe(
        self,
        left_cmd: list[str],
        right_cmd: list[str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(left_cmd)
        self.commands.append(right_cmd)
        self.inputs.extend([None, None])
        return subprocess.CompletedProcess(right_cmd, 0, stdout="synced\n", stderr="")


def test_load_cluster_config_resolves_relative_token_file(tmp_path) -> None:
    token_file = tmp_path / "run" / "agent-token"
    token_file.parent.mkdir()
    token_file.write_text("secret\n", encoding="utf-8")
    nodes_file = tmp_path / "nodes.yaml"
    nodes_file.write_text(
        """
manager_hostname: H100
manager_url: ws://manager:8765/api/agents/ws
agent_token_file: run/agent-token
refresh_interval: 2.0
process_interval: 5.0
nodes:
  - id: gpu-node-01
    host: gpu-node-01
    user: alice
    port: 2222
""",
        encoding="utf-8",
    )

    config = load_cluster_config(nodes_file)

    assert config.manager_url == "ws://manager:8765/api/agents/ws"
    assert config.agent_token_file == token_file.resolve()
    assert config.manager_hostname == "H100"
    assert config.refresh_interval == 2.0
    assert config.process_interval == 5.0
    assert config.nodes[0] == ClusterNode(id="gpu-node-01", host="gpu-node-01", user="alice", port=2222)
    assert load_manager_hostname(nodes_file) == "H100"


def test_start_node_writes_token_via_stdin_not_ssh_command(tmp_path) -> None:
    config = ClusterConfig(
        manager_url="ws://manager:8765/api/agents/ws",
        agent_token_file=tmp_path / "token",
        nodes=[ClusterNode(id="node-a", host="node-a", user="alice")],
    )
    runner = FakeRunner()
    controller = ClusterController(
        config,
        project_root=tmp_path,
        runner=runner,
        sync_source=False,
    )

    result = controller.start_node(config.nodes[0], "secret-token")

    command_text = "\n".join(" ".join(command) for command in runner.commands)
    input_text = "\n".join(input_value or "" for input_value in runner.inputs)
    assert result.ok
    assert "secret-token" not in command_text
    assert "CONSTELLA_AGENT_TOKEN=secret-token" in input_text
    assert "cat > $HOME/.constella/run/agent.env" in command_text
    assert "chmod 600 $HOME/.constella/run/agent.env" in command_text


def test_render_agent_env_and_start_script_use_home_expansion(tmp_path) -> None:
    config = ClusterConfig(
        manager_url="ws://manager:8765/api/agents/ws",
        agent_token_file=tmp_path / "token",
        nodes=[ClusterNode(id="node-a", host="node-a")],
    )

    env = render_agent_env(config, config.nodes[0], "secret")
    script = render_start_script(config.remote_base)

    assert "CONSTELLA_AGENT_STATE_FILE=$HOME/.constella/run/agent-state.json" in env
    assert "BASE=$HOME/.constella" in script
    assert "python3 not found" in script
    assert "PYTHONPATH=\"$RUNTIME\"" in script
    assert "-m constella.agent_main" in script
    assert "uv run" not in script
    assert "kill -0 \"$old_pid\"" in script


def test_prepare_agent_runtime_contains_only_agent_modules(tmp_path) -> None:
    source = tmp_path / "src" / "constella"
    source.mkdir(parents=True)
    for module in AGENT_RUNTIME_MODULES:
        (source / module).write_text("# test module\n", encoding="utf-8")
    (source / "app.py").write_text("# server-only\n", encoding="utf-8")
    (source / "cli.py").write_text("# server-only\n", encoding="utf-8")

    runtime = prepare_agent_runtime(tmp_path)

    assert (runtime / "constella" / "agent_main.py").exists()
    assert (runtime / "websockets").is_dir()
    assert not (runtime / "constella" / "app.py").exists()
    assert not (runtime / "constella" / "cli.py").exists()
    assert not list(runtime.rglob("*.so"))


def test_ssh_command_includes_user_and_port() -> None:
    node = ClusterNode(id="node-a", host="gpu-a", user="alice", port=2222)

    assert ssh_command(node, "true") == ["ssh", "-p", "2222", "alice@gpu-a", "true"]
