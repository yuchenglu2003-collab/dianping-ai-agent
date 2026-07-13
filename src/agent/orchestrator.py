from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import yaml

from src.agent.auth_gate import AuthResult, require_api_key
from src.agent.critic import Critic
from src.agent.executor import Executor
from src.agent.llm_planner import LLMPlanner
from src.agent.planner import RulePlanner, TaskPlan
from src.agent.run_loop import run_with_progress
from src.agent.state import AgentState
from src.agent.task_parser import LLMTaskParser
from src.config_loader import load_config
from src.data_resolver import SchemaSummary, build_schema_summary, resolve_data_paths
from src.infra.artifact_store import ArtifactStore
from src.infra.llm_gateway import LLMGateway
from src.infra.metric_store import MetricStore
from src.run_context import RunContext
from src.task_loader import load_task
from src.task_spec import TaskSpec
from src.tools.registry import ToolRegistry, build_default_registry

ProgressCallback = Callable[[float, str], None]


def _make_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _setup_logger(run_dir: Path) -> logging.Logger:
    run_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"dianping_agent.{run_dir.name}")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh = logging.FileHandler(run_dir / "run.log", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


class Orchestrator:
    def __init__(
        self,
        project_root: Path,
        config: dict[str, Any],
        task: TaskSpec,
        data_inputs: list[Path],
        registry: ToolRegistry | None = None,
        run_id: str | None = None,
        api_key: str | None = None,
    ):
        self.project_root = project_root
        self.config = config
        self.task = task
        self.data_inputs = data_inputs
        self.registry = registry or build_default_registry()
        self.run_id = run_id or _make_run_id()
        self._ui_api_key = api_key
        self._auth: AuthResult | None = None
        self._gateway: LLMGateway | None = None

        self.rule_planner = RulePlanner()
        self.executor = Executor(self.registry)
        self.critic = Critic()

        logs_root = Path(config["paths"].get("logs", project_root / "logs" / "runs"))
        self.run_dir = logs_root / self.run_id
        self.logger = _setup_logger(self.run_dir)

        self.state = AgentState(
            run_id=self.run_id,
            task_id=task.task_id,
            task_file=task.raw_path,
            data_inputs=[str(p) for p in data_inputs],
        )
        self.ctx = RunContext(
            run_id=self.run_id,
            project_root=project_root,
            task=task,
            data_inputs=data_inputs,
            config=config,
            state=self.state,
            logger=self.logger,
            artifact_store=ArtifactStore(config["paths"]["artifacts"], task.task_id, self.run_id),
            metric_store=MetricStore(),
            run_dir=self.run_dir,
        )

    @classmethod
    def start(
        cls,
        *,
        data: str | Path | list[str | Path],
        task: str | Path | None = None,
        task_spec: TaskSpec | None = None,
        project_root: str | Path | None = None,
        config_path: str | Path | None = None,
        run_id: str | None = None,
        api_key: str | None = None,
    ) -> "Orchestrator":
        root = Path(project_root or Path.cwd()).resolve()
        config = load_config(config_path, project_root=root)
        if task_spec is None:
            if task is None:
                raise ValueError("必须提供 task 文件路径或 task_spec")
            # 自然语言任务：先建占位 TaskSpec，真正解析在 run_loop 里用 LLM
            task_path = Path(str(task))
            if task_path.exists() and task_path.suffix.lower() in {".md", ".yaml", ".yml"}:
                task_spec = load_task(task_path)
            else:
                text = str(task)
                task_spec = TaskSpec(
                    task_id="pending_llm_parse",
                    goal=text,
                    deliverables=["report"],
                    raw_text=text,
                )
        data_paths = resolve_data_paths(data, task_spec.data)
        return cls(root, config, task_spec, data_paths, run_id=run_id, api_key=api_key)

    @classmethod
    def start_with_spec(
        cls,
        *,
        data: str | Path | list[str | Path],
        task_spec: TaskSpec,
        project_root: str | Path | None = None,
        config_path: str | Path | None = None,
        run_id: str | None = None,
        api_key: str | None = None,
    ) -> "Orchestrator":
        return cls.start(
            data=data,
            task_spec=task_spec,
            project_root=project_root,
            config_path=config_path,
            run_id=run_id,
            api_key=api_key,
        )

    def ensure_auth(self, ping: bool = False) -> AuthResult:
        if self._auth and self._auth.ok and self._gateway:
            return self._auth
        auth = require_api_key(
            project_root=self.project_root,
            ui_api_key=self._ui_api_key,
            config=self.config,
            ping=ping,
        )
        self._auth = auth
        if not auth.ok:
            return auth
        self._gateway = LLMGateway(
            config=self.config.get("llm", {}),
            api_key=auth.api_key or "",
            base_url=auth.base_url,
        )
        self.ctx.extras["llm_gateway"] = self._gateway
        self.ctx.extras["auth"] = auth.to_dict()
        if self._ui_api_key:
            self.ctx.extras["ui_api_key"] = self._ui_api_key
        return auth

    def parse_task_with_llm(self, goal_text: str, schema: SchemaSummary) -> TaskSpec:
        self.ensure_auth()
        assert self._gateway is not None
        parser = LLMTaskParser(self._gateway)
        return parser.parse(goal_text, schema)

    def plan_with_llm(self, schema: SchemaSummary) -> tuple[TaskPlan, Any, str]:
        self.ensure_auth()
        assert self._gateway is not None
        allow_fallback = bool(self.config.get("llm", {}).get("allow_rule_fallback", True))
        planner = LLMPlanner(self._gateway, self.registry, allow_fallback=allow_fallback)
        return planner.plan(self.task, schema)

    def _save_snapshots(self, plan: TaskPlan | None = None) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        # 快照配置时剔除可能的 api_key
        cfg_safe = json.loads(json.dumps(self.config, default=str))
        if isinstance(cfg_safe.get("llm"), dict):
            cfg_safe["llm"].pop("api_key", None)
        (self.run_dir / "config_snapshot.yaml").write_text(
            yaml.safe_dump(cfg_safe, allow_unicode=True), encoding="utf-8"
        )
        if self.task.raw_path and Path(self.task.raw_path).exists():
            suffix = Path(self.task.raw_path).suffix or ".md"
            shutil.copy2(self.task.raw_path, self.run_dir / f"task_snapshot{suffix}")
        else:
            (self.run_dir / "task_snapshot.md").write_text(self.task.raw_text or self.task.goal, encoding="utf-8")
        if plan:
            (self.run_dir / "plan.json").write_text(
                json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
        self._persist_state()

    def _persist_state(self) -> None:
        (self.run_dir / "state.json").write_text(
            json.dumps(self.state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _save_llm_usage(self) -> None:
        if not self._gateway:
            return
        usage = self._gateway.usage_summary()
        self.state.llm_usage = {
            "calls": usage["calls"],
            "prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": usage["completion_tokens"],
        }
        (self.run_dir / "llm_calls.json").write_text(
            json.dumps(usage, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def build_plan_only(self) -> TaskPlan:
        """兼容旧 CLI：本地 profile + LLM/规则规划（需密钥）。"""
        auth = self.ensure_auth()
        if not auth.ok:
            raise RuntimeError(auth.message)
        schema = build_schema_summary(self.data_inputs, self.config.get("schema_hints"))
        self.ctx.schema = schema
        plan, feas, source = self.plan_with_llm(schema)
        self.state.feasibility = plan.feasibility
        self.state.plan = plan.steps
        self.state.plan_source = source
        self.state.status = "PLAN"
        self._save_snapshots(plan)
        return plan

    def run_until_complete(
        self,
        only_step: str | None = None,
        on_progress: ProgressCallback | None = None,
        raw_task_text: str | None = None,
    ) -> AgentState:
        return run_with_progress(
            self,
            on_progress=on_progress,
            only_step=only_step,
            raw_task_text=raw_task_text,
        )
