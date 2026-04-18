from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = PROJECT_ROOT / "docs" / "skills"


@dataclass(frozen=True)
class ProjectSkill:
    name: str
    path: Path

    @property
    def relative_path(self) -> str:
        return str(self.path.relative_to(PROJECT_ROOT)).replace("\\", "/")

    @property
    def skill_file(self) -> Path:
        return self.path / "SKILL.md"


class ProjectSkillCatalog:
    """Discover and format the project-owned reusable AI playbooks."""

    DEFAULT_K6_ACTION_MAP: dict[str, tuple[str, ...]] = {
        "test": ("k6-best-practices",),
        "report": ("performance-report-analysis",),
        "workflow": (
            "performance-testing-strategy",
            "k6-best-practices",
            "performance-report-analysis",
        ),
        "strategy": ("performance-testing-strategy",),
    }

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or SKILLS_ROOT).resolve()

    def get(self, name: str) -> ProjectSkill | None:
        skill_dir = self.root / name
        if not (skill_dir / "SKILL.md").exists():
            return None
        return ProjectSkill(name=name, path=skill_dir)

    def for_k6_action(self, action: str) -> list[ProjectSkill]:
        return self.for_names(self.DEFAULT_K6_ACTION_MAP.get(action, ()))

    def for_names(self, names: tuple[str, ...] | list[str]) -> list[ProjectSkill]:
        skills: list[ProjectSkill] = []
        for name in names:
            skill = self.get(name)
            if skill is not None:
                skills.append(skill)
        return skills

    def guidance_for_k6_action(
        self,
        action: str,
        metrics: dict[str, float | int | str] | None = None,
    ) -> list[str]:
        skills = self.for_k6_action(action)
        return self.guidance_for_skills(skills, metrics=metrics)

    def guidance_for_names(
        self,
        names: tuple[str, ...] | list[str],
        metrics: dict[str, float | int | str] | None = None,
    ) -> list[str]:
        skills = self.for_names(names)
        return self.guidance_for_skills(skills, metrics=metrics)

    def guidance_for_skills(
        self,
        skills: list[ProjectSkill],
        metrics: dict[str, float | int | str] | None = None,
    ) -> list[str]:
        guidance: list[str] = []
        for skill in skills:
            guidance.extend(self._default_guidance(skill.name, metrics or {}))
        return guidance

    @staticmethod
    def format_for_message(skills: list[ProjectSkill]) -> str:
        if not skills:
            return ""
        rendered = ", ".join(skill.relative_path for skill in skills)
        return f" Playbooks: {rendered}."

    def summarize_for_message(
        self,
        action: str,
        metrics: dict[str, float | int | str] | None = None,
        limit: int = 2,
    ) -> str:
        guidance = self.guidance_for_k6_action(action, metrics=metrics)[:limit]
        if not guidance:
            return ""
        return " Guidance: " + " ".join(guidance)

    def render_for_report(
        self,
        action: str,
        metrics: dict[str, float | int | str] | None = None,
    ) -> list[str]:
        skills = self.for_k6_action(action)
        guidance = self.guidance_for_k6_action(action, metrics=metrics)
        lines: list[str] = []
        if skills:
            lines.extend([f"- {skill.relative_path}" for skill in skills])
        if guidance:
            lines.extend([f"- {item}" for item in guidance])
        return lines

    def _default_guidance(
        self,
        skill_name: str,
        metrics: dict[str, float | int | str],
    ) -> list[str]:
        if skill_name == "k6-best-practices":
            return [
                "Keep thresholds as the real test gate; `check()` is only diagnostic.",
                "Use realistic think time and avoid zero-sleep request floods.",
            ]
        if skill_name == "performance-report-analysis":
            failure_rate = metrics.get("failure_rate")
            p95 = metrics.get("p95")
            guidance = [
                "Review p95, p99, error rate, and throughput before drawing conclusions from averages.",
            ]
            if failure_rate not in ("n/a", None, ""):
                guidance.append(f"Treat failure rate={failure_rate} as the first triage signal before latency tuning.")
            if p95 not in ("n/a", None, ""):
                guidance.append(f"Compare p95={p95} against the service SLA and check whether the run stayed stable over time.")
            return guidance
        if skill_name == "performance-testing-strategy":
            return [
                "Start from a smoke or baseline run before adding stress, spike, or endurance coverage.",
                "Size VUs, duration, and datasets from the ticket criteria instead of guessing defaults.",
            ]
        return self._headline_fallback(skill_name)

    def _headline_fallback(self, skill_name: str) -> list[str]:
        skill = self.get(skill_name)
        if skill is None or not skill.skill_file.exists():
            return []
        text = skill.skill_file.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        if not match:
            return []
        return [match.group(1).strip()]
