from __future__ import annotations

import hashlib
import importlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class RegistryError(RuntimeError):
    """Raised when the declared agent/skill plane is unsafe or inconsistent."""


@dataclass(frozen=True, slots=True)
class AgentSpec:
    agent_id: str
    name: str
    module: str
    class_name: str
    responsibility: str
    model: str
    allowed_skills: tuple[str, ...]
    callers: tuple[str, ...]
    timeout_seconds: int
    retry_policy: str
    fallback_policy: str
    state: str


@dataclass(frozen=True, slots=True)
class SkillSpec:
    name: str
    path: str
    state: str
    execution_mode: str
    consumers: tuple[str, ...]


class AgentSkillPlane:
    """Fail-closed runtime registry for deterministic agents and instruction skills.

    Skill invocation means securely loading the versioned SKILL.md resource for an
    authorized agent. Executable helper scripts remain behind the project activation
    policy and are never launched implicitly by this plane.
    """

    ALLOWED_EXECUTION_MODES = frozenset({"INSTRUCTION_RESOURCE", "GATED_SCRIPT_TOOL"})

    def __init__(self, project_root: str | Path | None = None) -> None:
        self.project_root = self._resolve_project_root(project_root)
        self.agents_root = (self.project_root / ".agents").resolve()
        self.activation_policy = self._load_json(self.agents_root / "activation-policy.json")
        self.agent_registry = self._load_json(self.agents_root / "agent-registry.json")
        self.skill_registry = self._load_json(self.agents_root / "skill-registry.json")
        self.agents = self._load_agents()
        self.skills = self._load_skills()
        self._validate_cross_references()

    @staticmethod
    def _resolve_project_root(project_root: str | Path | None) -> Path:
        candidates: list[Path] = []
        if project_root is not None:
            candidates.append(Path(project_root))
        env_root = os.getenv("MEMORY_PROJECT_ROOT", "").strip()
        if env_root:
            candidates.append(Path(env_root))
        candidates.append(Path(__file__).resolve().parents[2])
        for candidate in candidates:
            root = candidate.resolve()
            if (root / ".agents").is_dir():
                return root
        raise RegistryError("MEMORIA-PERMANENTE project root with .agents was not found")

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise RegistryError(f"missing registry file: {path.name}")
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RegistryError(f"invalid registry file: {path.name}") from exc
        if not isinstance(value, dict):
            raise RegistryError(f"registry root must be an object: {path.name}")
        return value

    def _safe_agent_path(self, relative: str) -> Path:
        value = str(relative or "").strip().replace("\\", "/")
        if not value or value.startswith("/") or ":" in value:
            raise RegistryError(f"invalid skill path: {relative!r}")
        candidate = (self.project_root / value).resolve()
        try:
            candidate.relative_to(self.agents_root)
        except ValueError as exc:
            raise RegistryError(f"skill path escapes .agents: {relative!r}") from exc
        return candidate

    def _load_agents(self) -> dict[str, AgentSpec]:
        raw_agents = self.agent_registry.get("agents")
        if not isinstance(raw_agents, list) or not raw_agents:
            raise RegistryError("agent registry contains no agents")
        result: dict[str, AgentSpec] = {}
        for raw in raw_agents:
            if not isinstance(raw, dict):
                raise RegistryError("agent entry must be an object")
            agent_id = str(raw.get("id") or "").strip()
            module = str(raw.get("module") or "").strip()
            class_name = str(raw.get("class") or "").strip()
            if not agent_id or agent_id in result:
                raise RegistryError(f"invalid or duplicate agent id: {agent_id!r}")
            if not module.startswith("memory_permanent."):
                raise RegistryError(f"agent module outside allowlisted package: {module!r}")
            if not class_name or not class_name.replace("_", "").isalnum():
                raise RegistryError(f"invalid agent class: {class_name!r}")
            timeout = int(raw.get("timeout_seconds") or 0)
            if timeout < 1 or timeout > 3600:
                raise RegistryError(f"invalid timeout for agent {agent_id}")
            result[agent_id] = AgentSpec(
                agent_id=agent_id,
                name=str(raw.get("name") or agent_id).strip(),
                module=module,
                class_name=class_name,
                responsibility=str(raw.get("responsibility") or "").strip(),
                model=str(raw.get("model") or "DETERMINISTIC_NO_LLM").strip(),
                allowed_skills=tuple(str(x).strip() for x in (raw.get("allowed_skills") or []) if str(x).strip()),
                callers=tuple(str(x).strip() for x in (raw.get("callers") or []) if str(x).strip()),
                timeout_seconds=timeout,
                retry_policy=str(raw.get("retry_policy") or "CALLER_CONTROLLED").strip(),
                fallback_policy=str(raw.get("fallback_policy") or "FAIL_CLOSED").strip(),
                state=str(raw.get("state") or "CONFIGURED").strip().upper(),
            )
        return result

    def _load_skills(self) -> dict[str, SkillSpec]:
        raw_skills = self.skill_registry.get("skills")
        if not isinstance(raw_skills, list) or not raw_skills:
            raise RegistryError("skill registry contains no skills")
        result: dict[str, SkillSpec] = {}
        for raw in raw_skills:
            if not isinstance(raw, dict):
                raise RegistryError("skill entry must be an object")
            name = str(raw.get("name") or "").strip()
            path = str(raw.get("path") or "").strip()
            mode = str(raw.get("execution_mode") or "INSTRUCTION_RESOURCE").strip().upper()
            if not name or name in result:
                raise RegistryError(f"invalid or duplicate skill name: {name!r}")
            if mode not in self.ALLOWED_EXECUTION_MODES:
                raise RegistryError(f"unsupported skill execution mode for {name}: {mode}")
            root = self._safe_agent_path(path)
            if not root.is_dir() or not (root / "SKILL.md").is_file():
                raise RegistryError(f"skill {name} is missing SKILL.md at {path}")
            result[name] = SkillSpec(
                name=name,
                path=path.replace("\\", "/"),
                state=str(raw.get("state") or "UNKNOWN").strip().upper(),
                execution_mode=mode,
                consumers=tuple(str(x).strip() for x in (raw.get("consumers") or []) if str(x).strip()),
            )
        return result

    def _validate_cross_references(self) -> None:
        for skill in self.skills.values():
            if not skill.consumers:
                raise RegistryError(f"skill has no consumer: {skill.name}")
            unknown = sorted(set(skill.consumers) - set(self.agents))
            if unknown:
                raise RegistryError(f"skill {skill.name} references unknown consumers: {unknown}")
        for agent in self.agents.values():
            unknown = sorted(set(agent.allowed_skills) - set(self.skills))
            if unknown:
                raise RegistryError(f"agent {agent.agent_id} references unknown skills: {unknown}")
            for skill_name in agent.allowed_skills:
                if agent.agent_id not in self.skills[skill_name].consumers:
                    raise RegistryError(f"agent/skill mapping is not reciprocal: {agent.agent_id}->{skill_name}")

    def load_agent_class(self, agent_id: str) -> type[Any]:
        spec = self.agents.get(str(agent_id))
        if spec is None:
            raise RegistryError(f"unknown agent: {agent_id}")
        module = importlib.import_module(spec.module)
        target = getattr(module, spec.class_name, None)
        if not isinstance(target, type):
            raise RegistryError(f"agent class unavailable: {spec.module}:{spec.class_name}")
        return target

    def invoke_skill(self, agent_id: str, skill_name: str) -> dict[str, Any]:
        agent = self.agents.get(str(agent_id))
        skill = self.skills.get(str(skill_name))
        if agent is None:
            raise RegistryError(f"unknown agent: {agent_id}")
        if skill is None:
            raise RegistryError(f"unknown skill: {skill_name}")
        if skill.name not in agent.allowed_skills or agent.agent_id not in skill.consumers:
            raise PermissionError(f"agent {agent.agent_id} is not authorized for skill {skill.name}")
        skill_md = self._safe_agent_path(skill.path) / "SKILL.md"
        raw = skill_md.read_bytes()
        text = raw.decode("utf-8-sig")
        if not text.lstrip().startswith("---") or "name:" not in text[:2048] or "description:" not in text[:4096]:
            raise RegistryError(f"skill frontmatter is invalid: {skill.name}")
        return {
            "agent_id": agent.agent_id,
            "skill": skill.name,
            "execution_mode": skill.execution_mode,
            "state": skill.state,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "content": text,
        }

    def inventory(self) -> dict[str, Any]:
        return {
            "agents": [
                {
                    "id": spec.agent_id,
                    "name": spec.name,
                    "module": spec.module,
                    "class": spec.class_name,
                    "responsibility": spec.responsibility,
                    "model": spec.model,
                    "allowed_skills": list(spec.allowed_skills),
                    "callers": list(spec.callers),
                    "timeout_seconds": spec.timeout_seconds,
                    "retry_policy": spec.retry_policy,
                    "fallback_policy": spec.fallback_policy,
                    "declared_state": spec.state,
                }
                for spec in self.agents.values()
            ],
            "skills": [
                {
                    "name": spec.name,
                    "path": spec.path,
                    "state": spec.state,
                    "execution_mode": spec.execution_mode,
                    "consumers": list(spec.consumers),
                }
                for spec in self.skills.values()
            ],
        }

    def health(self) -> dict[str, Any]:
        errors: list[str] = []
        loaded_agents: list[str] = []
        callable_skills: list[str] = []
        for agent_id in self.agents:
            try:
                self.load_agent_class(agent_id)
                loaded_agents.append(agent_id)
            except (RegistryError, ImportError, OSError, UnicodeError, PermissionError) as exc:
                errors.append(f"agent:{agent_id}:{type(exc).__name__}:{exc}")
        for skill in self.skills.values():
            try:
                self.invoke_skill(skill.consumers[0], skill.name)
                callable_skills.append(skill.name)
            except (RegistryError, ImportError, OSError, UnicodeError, PermissionError) as exc:
                errors.append(f"skill:{skill.name}:{type(exc).__name__}:{exc}")
        return {
            "status": "HEALTHY" if not errors else "UNHEALTHY",
            "agents_total": len(self.agents),
            "agents_loaded": len(loaded_agents),
            "skills_total": len(self.skills),
            "skills_callable": len(callable_skills),
            "errors": errors,
        }
