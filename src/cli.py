from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from src.agent.auth_gate import require_api_key
from src.agent.orchestrator import Orchestrator
from src.config_loader import load_config
from src.task_spec import TaskSpec
from src.tools.data.setup_check import SetupCheckTool

console = Console()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@click.group()
def main() -> None:
    """大众点评数据分析 AI Agent CLI（LLM 驱动，需 API 密钥）。"""


@main.command("setup-check")
@click.option("--ping", is_flag=True, help="探测 API 是否可达")
def setup_check(ping: bool) -> None:
    root = _project_root()
    config = load_config(project_root=root)
    from src.agent.state import AgentState
    from src.infra.artifact_store import ArtifactStore
    from src.infra.metric_store import MetricStore
    from src.run_context import RunContext

    task = TaskSpec(task_id="setup")
    ctx = RunContext(
        run_id="setup",
        project_root=root,
        task=task,
        data_inputs=[],
        config=config,
        state=AgentState(run_id="setup", task_id="setup"),
        logger=__import__("logging").getLogger("setup"),
        artifact_store=ArtifactStore(config["paths"]["artifacts"], "setup", "setup"),
        metric_store=MetricStore(),
    )
    result = SetupCheckTool().run(ctx)
    auth = require_api_key(project_root=root, config=config, ping=ping)
    if result.success and auth.ok:
        console.print(f"[green]PASS[/green] {result.message}")
        console.print(auth.message)
    else:
        console.print(f"[red]FAIL[/red] {result.error or auth.message}")
        raise SystemExit(1)


@main.command("plan")
@click.option("--data", required=True, help="数据文件或目录")
@click.option("--task", required=True, help="任务文件路径，或自然语言任务")
def plan_cmd(data: str, task: str) -> None:
    root = _project_root()
    auth = require_api_key(project_root=root, config=load_config(project_root=root))
    if not auth.ok:
        console.print(f"[red]{auth.message}[/red]")
        raise SystemExit(1)
    orch = Orchestrator.start(data=data, task=task, project_root=root)
    # 先 LLM 解析再规划
    from src.data_resolver import build_schema_summary

    schema = build_schema_summary(orch.data_inputs, orch.config.get("schema_hints"))
    orch.ctx.schema = schema
    parsed = orch.parse_task_with_llm(orch.task.goal, schema)
    orch.task = parsed
    orch.ctx.task = parsed
    plan, _, source = orch.plan_with_llm(schema)
    console.print_json(json.dumps(plan.to_dict(), ensure_ascii=False))
    console.print(f"\n规划来源: [bold]{source}[/bold]  可行性: [bold]{plan.feasibility}[/bold]")


@main.command("run")
@click.option("--data", required=True, help="数据文件或目录")
@click.option("--task", required=True, help="任务文件路径，或自然语言任务字符串")
@click.option("--step", default=None, help="只跑某个步骤 id/tool")
@click.option("--run-id", default=None, help="指定 run_id")
def run_cmd(data: str, task: str, step: str | None, run_id: str | None) -> None:
    root = _project_root()
    auth = require_api_key(project_root=root, config=load_config(project_root=root))
    if not auth.ok:
        console.print(f"[red]{auth.message}[/red]")
        raise SystemExit(1)

    orch = Orchestrator.start(data=data, task=task, project_root=root, run_id=run_id)
    raw = orch.task.goal
    state = orch.run_until_complete(only_step=step, raw_task_text=raw)
    table = Table(title=f"Run {state.run_id}")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("task_id", state.task_id)
    table.add_row("status", state.status)
    table.add_row("feasibility", state.feasibility)
    table.add_row("plan_source", state.plan_source)
    table.add_row("completed", ", ".join(state.completed_steps))
    table.add_row("artifacts", str(len(state.artifacts)))
    console.print(table)
    if state.status not in {"DONE"}:
        raise SystemExit(1)


@main.command("validate")
@click.option("--run-id", required=True)
def validate_cmd(run_id: str) -> None:
    root = _project_root()
    config = load_config(project_root=root)
    state_path = Path(config["paths"]["logs"]) / run_id / "validation.json"
    if not state_path.exists():
        alt = Path(config["paths"]["logs"]) / run_id / "state.json"
        if not alt.exists():
            raise click.ClickException(f"找不到 run: {run_id}")
        console.print_json(alt.read_text(encoding="utf-8"))
        return
    console.print_json(state_path.read_text(encoding="utf-8"))


@main.command("ui")
@click.option("--port", default=8501, show_default=True, help="Web 端口")
@click.option("--host", default="localhost", show_default=True, help="绑定地址")
def ui_cmd(port: int, host: str) -> None:
    """启动交互 Web 界面。"""
    import subprocess
    import sys

    root = _project_root()
    app_path = root / "src" / "ui" / "app.py"
    console.print(f"[bold green]启动 Web UI[/bold green]: http://{host}:{port}")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(app_path),
            "--server.port",
            str(port),
            "--server.address",
            host,
        ],
        cwd=str(root),
        check=False,
    )


if __name__ == "__main__":
    main()
