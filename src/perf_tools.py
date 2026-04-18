from __future__ import annotations

import json
import locale
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from config import settings
from src.project_skills import ProjectSkill, ProjectSkillCatalog
from src.models import SearchDocument

APP_PROJECT_ROOT = Path(__file__).resolve().parents[1]
IGNORED_K6_SEARCH_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "results",
}


@dataclass(frozen=True)
class K6RunResult:
    service: str
    script_path: Path
    run_dir: Path
    summary_path: Path
    dashboard_path: Path
    stdout: str
    stderr: str
    exit_code: int


class K6Workspace:
    """Resolve test scripts, execute k6 locally, and generate local reports."""

    def __init__(self, project_root: str | None = None) -> None:
        self.project_root = self._resolve_project_root(project_root or settings.k6_project_root)
        self.results_root = self.project_root / "results"

    @property
    def configured(self) -> bool:
        return bool(self.k6_command_path) and bool(self._script_paths())

    @property
    def k6_command_path(self) -> str | None:
        return shutil.which(settings.k6_command) or None

    @property
    def configuration_message(self) -> str:
        scripts = self._script_paths()
        if not self.k6_command_path:
            return (
                f"K6 is not configured. Could not find '{settings.k6_command}' on PATH. "
                "Install k6 or set K6_COMMAND to the executable path."
            )
        if not scripts:
            return (
                "K6 is not configured. "
                f"No '*.test.js' scripts were found under '{self.project_root}'."
            )
        return "K6 is configured."

    def discover_services(self) -> list[str]:
        services: set[str] = set()
        for script_path in self._script_paths():
            services.add(self._service_name_for_script(script_path))
        return sorted(services)

    def find_test_script(self, service: str) -> Path | None:
        normalized = (service or "").strip().lower()
        if not normalized or not self.configured:
            return None

        for script_path in self._script_paths():
            name = self._service_name_for_script(script_path)
            parent_name = script_path.parent.name.lower()
            if (
                name == normalized
                or normalized in name
                or parent_name == normalized
                or normalized in parent_name
            ):
                return script_path
        return None

    def run_test(self, service: str, fields: dict[str, str] | None = None) -> K6RunResult:
        fields = fields or {}
        script_path = self.find_test_script(service)
        if script_path is None:
            raise ValueError(f"Could not find a k6 script for service '{service}'.")

        return self.run_script(script_path, service, fields)

    def run_script(
        self,
        script_path: Path,
        service: str,
        fields: dict[str, str] | None = None,
    ) -> K6RunResult:
        fields = fields or {}
        script_path = script_path.resolve()
        if not script_path.exists():
            raise ValueError(f"Could not find a k6 script at '{script_path}'.")

        k6_command = self.k6_command_path or settings.k6_command
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        run_dir = self.results_root / f"{timestamp}_bot_{service.lower()}"
        run_dir.mkdir(parents=True, exist_ok=True)

        summary_path = run_dir / f"{service.lower()}-summary.json"
        dashboard_path = run_dir / f"{service.lower()}-dashboard.html"

        command = [
            k6_command,
            "run",
            "--summary-export",
            str(summary_path),
        ]
        if fields.get("vus"):
            command.extend(["--vus", fields["vus"]])
        if fields.get("duration"):
            command.extend(["--duration", fields["duration"]])
        command.append(str(script_path.relative_to(self.project_root)))

        env = dict(**settings.raw_environment)
        env.update(
            {
                "K6_WEB_DASHBOARD": "true",
                "K6_WEB_DASHBOARD_EXPORT": str(dashboard_path),
            }
        )
        for key in ("base_url", "auth_url", "products_url", "cart_url", "orders_url", "payments_url"):
            if fields.get(key):
                env[key.upper()] = fields[key]

        completed = subprocess.run(
            command,
            cwd=self.project_root,
            capture_output=True,
            text=False,
            env=env,
            check=False,
        )
        return K6RunResult(
            service=service.lower(),
            script_path=script_path,
            run_dir=run_dir,
            summary_path=summary_path,
            dashboard_path=dashboard_path,
            stdout=_decode_subprocess_output(completed.stdout),
            stderr=_decode_subprocess_output(completed.stderr),
            exit_code=completed.returncode,
        )

    def latest_summary_for_service(self, service: str) -> Path | None:
        normalized = (service or "").strip().lower()
        if not normalized or not self.results_root.exists():
            return None

        candidates = sorted(
            self.results_root.glob(f"**/{normalized}-summary.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None

    def previous_summary_for_service(
        self,
        service: str,
        current_summary_path: Path | None = None,
    ) -> Path | None:
        normalized = (service or "").strip().lower()
        if not normalized or not self.results_root.exists():
            return None

        current_resolved = current_summary_path.resolve() if current_summary_path else None
        candidates = sorted(
            self.results_root.glob(f"**/{normalized}-summary.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for candidate in candidates:
            resolved = candidate.resolve()
            if current_resolved is not None and resolved == current_resolved:
                continue
            return candidate
        return None

    def latest_report_for_service(self, service: str) -> Path | None:
        normalized = (service or "").strip().lower()
        if not normalized or not self.results_root.exists():
            return None

        candidates = sorted(
            self.results_root.glob(f"**/*{normalized}*report*.md"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None

    def generate_report(self, service: str, summary_path: Path | None = None) -> SearchDocument:
        return self.generate_report_with_context(service, summary_path=summary_path)

    def generate_report_with_context(
        self,
        service: str,
        summary_path: Path | None = None,
        dashboard_url: str = "",
        playbooks: list[ProjectSkill] | None = None,
        playbook_notes: list[str] | None = None,
        workflow_context: dict[str, str] | None = None,
    ) -> SearchDocument:
        normalized = (service or "").strip().lower()
        summary_file = summary_path or self.latest_summary_for_service(normalized)
        if summary_file is None or not summary_file.exists():
            raise ValueError(
                f"Could not find a k6 summary for service '{normalized}'. Run the test first."
            )

        payload = json.loads(summary_file.read_text(encoding="utf-8"))
        metrics = payload.get("metrics", {})
        report_path = summary_file.with_name(f"{normalized}-report.md")
        report_content = self._render_markdown_report(
            normalized,
            summary_file,
            metrics,
            dashboard_url=dashboard_url,
            playbooks=playbooks or [],
            playbook_notes=playbook_notes or [],
            workflow_context=workflow_context or {},
        )
        report_path.write_text(report_content, encoding="utf-8")

        return SearchDocument(
            source_type="k6",
            title=f"k6 report for {normalized}",
            url=str(report_path),
            content=report_content,
            metadata={
                "service": normalized,
                "summary_path": str(summary_file),
                "report_path": str(report_path),
            },
        )

    def search_documents(self, query: str, limit: int) -> list[SearchDocument]:
        terms = set(part.lower() for part in query.split())
        documents: list[SearchDocument] = []

        for service in self.discover_services():
            if terms and service.lower() not in terms and "k6" not in terms and "test" not in terms:
                continue
            script_path = self.find_test_script(service)
            if script_path is None:
                continue
            documents.append(
                SearchDocument(
                    source_type="k6",
                    title=f"k6 test script for {service}",
                    url=str(script_path),
                    content=f"Service '{service}' uses script {script_path.name}.",
                    metadata={"service": service, "kind": "script"},
                )
            )

        for service in self.discover_services():
            report_path = self.latest_report_for_service(service)
            if report_path is None:
                continue
            if terms and service.lower() not in terms and "report" not in terms:
                continue
            documents.append(
                SearchDocument(
                    source_type="k6",
                    title=f"Latest k6 report for {service}",
                    url=str(report_path),
                    content=report_path.read_text(encoding="utf-8", errors="ignore")[:1500],
                    metadata={"service": service, "kind": "report"},
                )
            )
        return documents[:limit]

    @staticmethod
    def _service_name_for_script(script_path: Path) -> str:
        name = script_path.name
        if name.endswith(".test.js"):
            return name[:-8].lower()
        return script_path.stem.lower()

    def _script_paths(self) -> list[Path]:
        if not self.project_root.exists():
            return []
        return sorted(
            path
            for path in self.project_root.rglob("*.test.js")
            if not any(part in IGNORED_K6_SEARCH_DIRS for part in path.parts)
        )

    @classmethod
    def _resolve_project_root(cls, preferred_root: str) -> Path:
        preferred = Path(preferred_root).resolve()
        for candidate in cls._candidate_roots(preferred):
            if cls._has_k6_scripts(candidate):
                return candidate
        return preferred

    @classmethod
    def _candidate_roots(cls, preferred: Path) -> list[Path]:
        candidates: list[Path] = []
        seen: set[Path] = set()

        def add(path: Path) -> None:
            resolved = path.resolve()
            if resolved in seen:
                return
            seen.add(resolved)
            candidates.append(resolved)

        add(preferred)
        add(preferred / "performance")
        add(APP_PROJECT_ROOT / "performance")
        add(APP_PROJECT_ROOT)
        return candidates

    @classmethod
    def _has_k6_scripts(cls, candidate: Path) -> bool:
        if not candidate.exists() or not candidate.is_dir():
            return False
        tests_dir = candidate / "tests"
        if not tests_dir.exists() or not tests_dir.is_dir():
            return False
        return any(
            not any(part in IGNORED_K6_SEARCH_DIRS for part in path.parts)
            for path in tests_dir.rglob("*.test.js")
        )

    def _render_markdown_report(
        self,
        service: str,
        summary_path: Path,
        metrics: dict[str, Any],
        dashboard_url: str = "",
        playbooks: list[ProjectSkill] | None = None,
        playbook_notes: list[str] | None = None,
        workflow_context: dict[str, str] | None = None,
    ) -> str:
        http_duration = self._metric_dict(metrics, "http_req_duration")
        checks = self._metric_dict(metrics, "checks")
        iterations = self._metric_dict(metrics, "iterations")
        failures = self._metric_dict(metrics, "http_req_failed")
        requests = self._metric_dict(metrics, "http_reqs")
        grafana_link = dashboard_url or self._grafana_link(service)
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        playbooks = playbooks or []
        playbook_notes = playbook_notes or []
        workflow_context = workflow_context or {}
        baseline_summary = self.previous_summary_for_service(service, current_summary_path=summary_path)
        baseline_metrics = self._load_metrics_file(baseline_summary) if baseline_summary else {}
        delta_lines = self._baseline_delta_lines(metrics, baseline_metrics)
        run_dir = summary_path.parent
        run_dir_relative = self._relative_path(run_dir)
        summary_relative = self._relative_path(summary_path)
        baseline_relative = self._relative_path(baseline_summary) if baseline_summary else ""
        jira_issue = workflow_context.get("jira_issue", "").strip()
        dataset = workflow_context.get("dataset", "").strip()
        test_type = workflow_context.get("test_type", "").strip() or "load"
        script_path = workflow_context.get("script_path", "").strip()
        git_add_command = f"git add {run_dir_relative}"
        executive_line = self._executive_summary_line(metrics, baseline_metrics)

        lines = [
            f"# k6 Test Report: {service}",
            "",
            f"- Generated at: {generated_at}",
            f"- Test type: {test_type}",
            f"- Summary file: `{summary_relative}`",
            f"- Run artifacts: `{run_dir_relative}`",
            f"- Project root: `{self.project_root}`",
            "",
            "## Executive Summary",
            "",
            f"- {executive_line}",
        ]
        if baseline_summary:
            lines.append(f"- Baseline used for comparison: `{baseline_relative}`")
        else:
            lines.append("- Baseline used for comparison: none found in `results/`")
        if jira_issue:
            lines.append(f"- Jira ticket: `{jira_issue}`")
        if dataset:
            lines.append(f"- Dataset: `{dataset}`")
        lines.extend(
            [
                "",
                "## Technical Metrics",
                "",
                f"- HTTP request p(95): {self._format_latency_metric(http_duration.get('p(95)'))}",
                f"- HTTP request avg: {self._format_latency_metric(http_duration.get('avg'))}",
                f"- Checks pass rate: {checks.get('rate', 'n/a')}",
                f"- HTTP failure rate: {failures.get('rate', 'n/a')}",
                f"- Iterations: {iterations.get('count', 'n/a')}",
                f"- HTTP requests: {requests.get('count', 'n/a')}",
                "",
                "## Baseline Comparison",
                "",
                *delta_lines,
                "",
                "## Interpretation",
                "",
                self._summary_interpretation(http_duration, checks, failures),
                "",
            ]
        )
        if workflow_context.get("include_workflow_trace", "true").lower() != "false":
            lines.extend(
                [
                    "## Workflow Trace",
                    "",
                    f"- 1. Jira input: {'linked to ' + jira_issue if jira_issue else 'no Jira issue provided in this run.'}",
                    "- 2. Strategy: apply `docs/skills/performance-testing-strategy` to derive SLAs, VUs, duration, and datasets.",
                    "- 3. Script design: follow the 5-block k6 pattern with options, data, setup, default, and summary.",
                    "- 4. Validation: review the script with `docs/skills/k6-best-practices` before execution.",
                    f"- 5. Run: `k6 run {script_path or 'tests/<service>/<service>.test.js'}`",
                    "- 6. Report: compare the latest run with the most recent baseline in `results/`.",
                    "- 7. Analysis: apply `docs/skills/performance-report-analysis` for executive and technical conclusions.",
                    f"- 8. Jira comment: {'ready to post back to ' + jira_issue if jira_issue else 'pending a Jira issue key.'}",
                    f"- 9. Git versioning: `{git_add_command}`",
                    "",
                ]
            )
        if grafana_link:
            lines.extend(
                [
                    "## Grafana",
                    "",
                    f"- Dashboard search: {grafana_link}",
                    "- Panel image extraction can be attached here when the Grafana MCP image flow is available.",
                    "",
                ]
            )
        if playbooks:
            lines.extend(
                [
                    "## Playbooks",
                    "",
                    *[f"- {playbook.relative_path}" for playbook in playbooks],
                    "",
                ]
            )
        if playbook_notes:
            lines.extend(
                [
                    "## Applied Guidance",
                    "",
                    *[f"- {note}" for note in playbook_notes],
                    "",
                ]
            )
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _load_metrics_file(summary_path: Path | None) -> dict[str, Any]:
        if summary_path is None or not summary_path.exists():
            return {}
        try:
            return json.loads(summary_path.read_text(encoding="utf-8")).get("metrics", {})
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return {}

    @staticmethod
    def _metric_dict(metrics: dict[str, Any], metric_name: str) -> dict[str, Any]:
        metric = metrics.get(metric_name, {})
        if not isinstance(metric, dict):
            return {}
        values = metric.get("values")
        if isinstance(values, dict):
            return values
        passes = metric.get("passes")
        fails = metric.get("fails")
        if isinstance(passes, (int, float)) and isinstance(fails, (int, float)):
            total = passes + fails
            rate = passes / total if total else None
            if metric_name == "http_req_failed":
                rate = fails / total if total else None
            normalized = dict(metric)
            if rate is not None:
                normalized["rate"] = rate
            return normalized
        return metric

    def _relative_path(self, path: Path | None) -> str:
        if path is None:
            return ""
        try:
            return str(path.resolve().relative_to(self.project_root.resolve())).replace("\\", "/")
        except ValueError:
            return str(path)

    def _baseline_delta_lines(
        self,
        current_metrics: dict[str, Any],
        baseline_metrics: dict[str, Any],
    ) -> list[str]:
        if not baseline_metrics:
            return ["- No earlier baseline summary was found for this service."]

        metric_specs = (
            ("http_req_duration", "p(95)", "Latency p95"),
            ("http_req_duration", "avg", "Latency avg"),
            ("http_req_failed", "rate", "Failure rate"),
            ("http_reqs", "count", "HTTP requests"),
        )
        lines: list[str] = []
        for metric_name, value_key, label in metric_specs:
            current_value = self._metric_value(current_metrics, metric_name, value_key)
            baseline_value = self._metric_value(baseline_metrics, metric_name, value_key)
            delta = self._format_delta(current_value, baseline_value)
            lines.append(
                f"- {label}: current={self._format_metric(current_value)} baseline={self._format_metric(baseline_value)} delta={delta}"
            )
        return lines

    @staticmethod
    def _metric_value(metrics: dict[str, Any], metric_name: str, value_key: str) -> float | int | str | None:
        metric = metrics.get(metric_name, {})
        if not isinstance(metric, dict):
            return None
        if "values" in metric and isinstance(metric.get("values"), dict):
            return metric["values"].get(value_key)
        if value_key == "rate":
            passes = metric.get("passes")
            fails = metric.get("fails")
            if isinstance(passes, (int, float)) and isinstance(fails, (int, float)):
                total = passes + fails
                if not total:
                    return None
                if metric_name == "http_req_failed":
                    return fails / total
                return passes / total
        return metric.get(value_key)

    @staticmethod
    def _format_metric(value: float | int | str | None) -> str:
        if value in (None, ""):
            return "n/a"
        if isinstance(value, float):
            return f"{value:.4f}".rstrip("0").rstrip(".")
        return str(value)

    @classmethod
    def _format_delta(cls, current: float | int | str | None, baseline: float | int | str | None) -> str:
        current_number = cls._to_number(current)
        baseline_number = cls._to_number(baseline)
        if current_number is None or baseline_number in (None, 0):
            return "n/a"
        delta = ((current_number - baseline_number) / baseline_number) * 100
        return f"{delta:+.2f}%"

    @staticmethod
    def _to_number(value: float | int | str | None) -> float | None:
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value))
        except ValueError:
            return None

    def _executive_summary_line(
        self,
        current_metrics: dict[str, Any],
        baseline_metrics: dict[str, Any],
    ) -> str:
        current_p95 = self._metric_value(current_metrics, "http_req_duration", "p(95)")
        failure_rate = self._metric_value(current_metrics, "http_req_failed", "rate")
        baseline_p95 = self._metric_value(baseline_metrics, "http_req_duration", "p(95)")
        p95_delta = self._format_delta(current_p95, baseline_p95)
        if baseline_metrics and p95_delta != "n/a":
            return (
                f"The run finished with p95={self._format_latency_metric(current_p95)} and failure rate={self._format_metric(failure_rate)}; "
                f"versus baseline, p95 changed by {p95_delta}."
            )
        return (
            f"The run finished with p95={self._format_latency_metric(current_p95)} and failure rate={self._format_metric(failure_rate)}. "
            "Use this run as the baseline if no prior comparison exists."
        )

    @staticmethod
    def _summary_interpretation(
        http_duration: dict[str, Any],
        checks: dict[str, Any],
        failures: dict[str, Any],
    ) -> str:
        p95 = http_duration.get("p(95)")
        failure_rate = failures.get("rate")
        check_rate = checks.get("rate")
        return (
            f"The latest run reported p(95)={K6Workspace._format_latency_metric(p95)}, "
            f"check pass rate={check_rate}, and failure rate={failure_rate}. "
            "Use the linked Grafana dashboard to correlate latency spikes with backend metrics."
        )

    @staticmethod
    def _format_latency_metric(value: float | int | str | None) -> str:
        formatted = K6Workspace._format_metric(value)
        if formatted == "n/a":
            return formatted
        return f"{formatted} ms"

    @staticmethod
    def _grafana_link(service: str) -> str:
        base = settings.grafana_url.rstrip("/")
        if not base:
            return ""
        return f"{base}/dashboards?query={service}"


def _decode_subprocess_output(value: bytes | str | None) -> str:
    """Decode Windows subprocess output without relying on the active console code page."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value

    for encoding in ("utf-8", locale.getpreferredencoding(False), "cp1252", "latin-1"):
        try:
            return value.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return value.decode("utf-8", errors="replace")
