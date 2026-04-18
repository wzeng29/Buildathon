from __future__ import annotations

import tempfile
import unittest
import shutil
from unittest.mock import MagicMock, patch

import numpy as np
import requests
from pathlib import Path

from config import _is_real_value
from src.agent import BuildAgents, format_slack_response
from src.command_parser import parse_action_request, parse_contextual_action_request
from src.connectors import AS400ManualConnector, BaseConnector, build_connectors, ConfluenceConnector, GrafanaConnector, JiraConnector, JiraPerformanceWorkflowConnector, K6TestConnector, K6WorkflowConnector, TicketPerformancePlan, WorkflowDecision
from src.llm import OpenAIResponder
from src.mcp_adapter import MCPAdapter
from src.memory import RedisConversationMemory
from src.multi_agent import RequirementUnderstandingAgent
from src.models import ActionRequest, ActionResult, AgentAnswer, SearchDocument
from src.main import _run_repl, main
from src.perf_tools import K6Workspace, _decode_subprocess_output
from src.project_skills import ProjectSkillCatalog
from src.skills import parse_skill_request
from src.slack_app import (
    _conversation_id_for_event,
    _is_allowed_channel,
    _is_supported_event,
    _normalize_question,
    _upload_html_report_if_available,
    handle_slack_event,
    process_socket_mode_request,
)


class StubConnector(BaseConnector):
    def __init__(
        self,
        source_type: str,
        target_type: str,
        configured: bool = True,
        documents: list[SearchDocument] | None = None,
    ) -> None:
        super().__init__()
        self.source_type = source_type
        self.target_type = target_type
        self._configured = configured
        self._documents = documents or []
        self.executed_requests: list[ActionRequest] = []

    @property
    def configured(self) -> bool:
        return self._configured

    def search(self, query: str, limit: int) -> list[SearchDocument]:
        return self._documents[:limit]

    def create(self, request: ActionRequest) -> ActionResult:
        return self._record_action("Created", request)

    def read(self, request: ActionRequest) -> ActionResult:
        return self._record_action("Loaded", request)

    def update(self, request: ActionRequest) -> ActionResult:
        return self._record_action("Updated", request)

    def delete(self, request: ActionRequest) -> ActionResult:
        return self._record_action("Deleted", request)

    def _record_action(self, verb: str, request: ActionRequest) -> ActionResult:
        self.executed_requests.append(request)
        document = SearchDocument(
            source_type=self.source_type,
            title=f"{self.source_type.upper()}-1",
            url=f"https://example.com/{self.source_type}/1",
            content="stub content",
            metadata=request.fields,
        )
        return ActionResult(
            success=True,
            message=f"{verb} {request.target_system} {request.target_type}.",
            document=document,
        )


class RunStubConnector(StubConnector):
    def execute(self, request: ActionRequest) -> ActionResult:
        self.executed_requests.append(request)
        document = SearchDocument(
            source_type=self.source_type,
            title=f"{self.source_type.upper()}-{request.identifier or '1'}",
            url=f"https://example.com/{self.source_type}/1",
            content="stub workflow result",
            metadata=request.fields,
        )
        return ActionResult(
            success=True,
            message=f"Executed {request.target_system} {request.target_type}.",
            document=document,
        )


class StubResponder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list[dict[str, str]]]] = []
        self.completions: list[tuple[str, str, float]] = []
        self.function_calls: list[tuple[str, str, str, str, dict, float]] = []

    def generate(
        self,
        question: str,
        evidence_text: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        self.calls.append((question, evidence_text, conversation_history or []))
        return f"ANSWER::{question}::{bool(evidence_text)}::{len(conversation_history or [])}"

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> str:
        self.completions.append((system_prompt, user_prompt, temperature))
        return ""

    def call_function(
        self,
        system_prompt: str,
        user_prompt: str,
        function_name: str,
        function_description: str,
        parameters: dict,
        temperature: float = 0.1,
    ) -> dict:
        self.function_calls.append(
            (system_prompt, user_prompt, function_name, function_description, parameters, temperature)
        )
        return {}


class FakeJiraWorkflowDependency:
    def __init__(self, document: SearchDocument) -> None:
        self.document = document
        self.comments: list[tuple[str, str]] = []

    @property
    def configured(self) -> bool:
        return True

    @property
    def configuration_message(self) -> str:
        return "Jira is configured."

    def search(self, query: str, limit: int) -> list[SearchDocument]:
        return [self.document][:limit]

    def read(self, request: ActionRequest) -> ActionResult:
        return ActionResult(True, "Loaded Jira ticket.", document=self.document, details={"key": self.document.metadata.get("key")})

    def add_comment(self, issue_key: str, comment: str) -> None:
        self.comments.append((issue_key, comment))


class StubMCPHandler:
    def __init__(self, source_type: str) -> None:
        self.source_type = source_type
        self.search_calls: list[tuple[str, int]] = []
        self.execute_calls: list[ActionRequest] = []

    def search(self, query: str, limit: int) -> list[SearchDocument]:
        self.search_calls.append((query, limit))
        return [
            SearchDocument(
                source_type=self.source_type,
                title=f"MCP {self.source_type} result",
                url=f"https://mcp.example/{self.source_type}",
                content=f"MCP search for {query}",
                metadata={"via": "mcp"},
            )
        ]

    def execute(self, request: ActionRequest) -> ActionResult:
        self.execute_calls.append(request)
        return ActionResult(
            success=True,
            message=f"MCP executed {request.operation} on {self.source_type}.",
            document=SearchDocument(
                source_type=self.source_type,
                title=f"MCP {self.source_type} action",
                url=f"https://mcp.example/{self.source_type}/action",
                content="MCP action result",
                metadata={"via": "mcp", "operation": request.operation},
            ),
        )


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, list[str]] = {}
        self.expirations: dict[str, int] = {}

    def ping(self) -> bool:
        return True

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        values = self.store.get(key, [])
        if end == -1:
            end = len(values) - 1
        return values[start : end + 1]

    def rpush(self, key: str, *values: str) -> None:
        self.store.setdefault(key, []).extend(values)

    def ltrim(self, key: str, start: int, end: int) -> None:
        values = self.store.get(key, [])
        length = len(values)
        normalized_start = start if start >= 0 else max(length + start, 0)
        normalized_end = end if end >= 0 else length + end
        self.store[key] = values[normalized_start : normalized_end + 1]

    def expire(self, key: str, ttl_seconds: int) -> None:
        self.expirations[key] = ttl_seconds


class FakeEmbedder:
    model_name = "fake-transformer"

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors: list[list[float]] = []
        for text in texts:
            lowered = text.lower()
            vectors.append(
                [
                    1.0 if any(token in lowered for token in ("obj", "object", "wrkobj")) else 0.0,
                    1.0 if any(token in lowered for token in ("desc", "description", "dspobjd")) else 0.0,
                    1.0 if "lock" in lowered else 0.0,
                    1.0 if any(token in lowered for token in ("distribution", "wrkdstl", "dspdstl")) else 0.0,
                ]
            )
        return np.asarray(vectors, dtype=np.float32)


class AgentTests(unittest.TestCase):
    def test_placeholder_values_are_not_treated_as_real_config(self) -> None:
        self.assertFalse(_is_real_value(""))
        self.assertFalse(_is_real_value("https://your-company.atlassian.net"))
        self.assertTrue(_is_real_value("https://acme.atlassian.net"))

    def test_build_connectors_include_perf_and_grafana_connectors(self) -> None:
        connectors = build_connectors()
        self.assertEqual(
            [connector.source_type for connector in connectors],
            ["as400", "confluence", "jira", "jira", "k6", "k6", "k6", "grafana"],
        )

    def test_keyword_routing_prefers_jira(self) -> None:
        jira = StubConnector("jira", "ticket")
        confluence = StubConnector("confluence", "page")
        agent = BuildAgents(
            connectors=[jira, confluence],
            responder=StubResponder(),
        )

        understood = agent.understanding_agent.analyze("What is the status of ticket ABC-123?")
        selected = agent.retrieval_agent.select_connectors(
            agent.connectors,
            understood,
            {"jira": ("jira", "ticket", "story", "bug", "status")},
        )
        self.assertEqual([connector.source_type for connector in selected], ["jira"])

    def test_keyword_routing_prefers_confluence(self) -> None:
        jira = StubConnector("jira", "ticket")
        confluence = StubConnector("confluence", "page")
        agent = BuildAgents(
            connectors=[jira, confluence],
            responder=StubResponder(),
        )

        understood = agent.understanding_agent.analyze("Find the confluence page for onboarding docs")
        selected = agent.retrieval_agent.select_connectors(
            agent.connectors,
            understood,
            {"confluence": ("confluence", "doc", "page", "knowledge", "kb")},
        )
        self.assertEqual([connector.source_type for connector in selected], ["confluence"])

    def test_generic_query_uses_all_configured_connectors(self) -> None:
        jira = StubConnector("jira", "ticket")
        confluence = StubConnector("confluence", "page")
        agent = BuildAgents(
            connectors=[jira, confluence],
            responder=StubResponder(),
        )

        understood = agent.understanding_agent.analyze("payment gateway outage")
        selected = agent.retrieval_agent.select_connectors(agent.connectors, understood, {})
        self.assertEqual(
            [connector.source_type for connector in selected],
            ["jira", "confluence"],
        )

    def test_understanding_agent_prefers_as400_for_command_questions(self) -> None:
        interpreted = RequirementUnderstandingAgent().analyze("what command to use to see obj info")
        self.assertIn("as400", interpreted.preferred_sources)
        self.assertTrue(interpreted.wants_command_answer)

    def test_as400_manual_connector_searches_local_manual_text(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
            handle.write(
                "Use WRKOBJ OBJ(MYOBJ) OBJTYPE(*FILE) to work with object information.\n"
                "Use DSPOBJD OBJ(MYOBJ) OBJTYPE(*FILE) to display object description.\n"
            )
            manual_path = handle.name

        connector = AS400ManualConnector(
            manual_path=manual_path,
            embedder=FakeEmbedder(),
            index_path=manual_path + ".npz",
        )
        results = connector.search("what command to use to see obj info", 3)

        self.assertTrue(results)
        self.assertEqual(results[0].source_type, "as400")
        self.assertIn("WRKOBJ", " ".join(results[0].metadata.get("command_candidates", [])))

    def test_parse_k6_action_request(self) -> None:
        request = parse_action_request("run k6 test auth vus=2 duration=30s")
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.operation, "run")
        self.assertEqual(request.target_system, "k6")
        self.assertEqual(request.target_type, "test")
        self.assertEqual(request.identifier, "auth")
        self.assertEqual(request.fields["vus"], "2")
        self.assertEqual(request.fields["duration"], "30s")

    def test_parse_skill_request_for_k6_workflow(self) -> None:
        request = parse_skill_request("/k6-workflow auth duration: 30s")
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.operation, "create")
        self.assertEqual(request.target_system, "k6")
        self.assertEqual(request.target_type, "workflow")
        self.assertEqual(request.identifier, "auth")
        self.assertEqual(request.fields["duration"], "30s")

    def test_k6_workspace_generates_markdown_report(self) -> None:
        project_root = Path("tests") / ".tmp_k6_workspace"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            summary_dir = project_root / "results" / "2026-04-14_bot_auth"
            summary_dir.mkdir(parents=True)
            summary_path = summary_dir / "auth-summary.json"
            summary_path.write_text(
                """
                {
                  "metrics": {
                    "http_req_duration": { "values": { "avg": 54.63, "p(95)": 71.45 } },
                    "checks": { "values": { "rate": 0.99 } },
                    "http_req_failed": { "values": { "rate": 0.01 } },
                    "iterations": { "values": { "count": 42 } },
                    "http_reqs": { "values": { "count": 84 } }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            (project_root / "tests" / "auth").mkdir(parents=True)
            (project_root / "tests" / "auth" / "auth.test.js").write_text(
                "export default function () {}",
                encoding="utf-8",
            )

            workspace = K6Workspace(str(project_root))
            document = workspace.generate_report("auth", summary_path)

            self.assertIn("k6 Test Report: auth", document.content)
            self.assertTrue(Path(document.url).exists())
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)

    def test_k6_workspace_report_can_include_playbooks_and_grafana(self) -> None:
        project_root = Path("tests") / ".tmp_k6_report_context"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            summary_dir = project_root / "results" / "2026-04-14_bot_auth"
            summary_dir.mkdir(parents=True)
            summary_path = summary_dir / "auth-summary.json"
            summary_path.write_text(
                """
                {
                  "metrics": {
                    "http_req_duration": { "values": { "avg": 54.63, "p(95)": 71.45 } },
                    "checks": { "values": { "rate": 0.99 } },
                    "http_req_failed": { "values": { "rate": 0.01 } },
                    "iterations": { "values": { "count": 42 } },
                    "http_reqs": { "values": { "count": 84 } }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            (project_root / "tests" / "auth").mkdir(parents=True)
            (project_root / "tests" / "auth" / "auth.test.js").write_text(
                "export default function () {}",
                encoding="utf-8",
            )

            workspace = K6Workspace(str(project_root))
            skills = ProjectSkillCatalog().for_k6_action("workflow")
            document = workspace.generate_report_with_context(
                "auth",
                summary_path=summary_path,
                dashboard_url="https://grafana.example/d/auth",
                playbooks=skills,
                playbook_notes=ProjectSkillCatalog().guidance_for_k6_action("workflow"),
            )

            self.assertIn("https://grafana.example/d/auth", document.content)
            self.assertIn("## Executive Summary", document.content)
            self.assertIn("## Baseline Comparison", document.content)
            self.assertIn("docs/skills/k6-best-practices", document.content)
            self.assertIn("docs/skills/performance-report-analysis", document.content)
            self.assertIn("## Applied Guidance", document.content)
            self.assertIn("Review p95, p99, error rate, and throughput", document.content)
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)

    def test_k6_workspace_report_compares_against_previous_baseline(self) -> None:
        project_root = Path("tests") / ".tmp_k6_baseline_report"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            old_summary_dir = project_root / "results" / "2026-04-13_bot_auth"
            new_summary_dir = project_root / "results" / "2026-04-14_bot_auth"
            old_summary_dir.mkdir(parents=True)
            new_summary_dir.mkdir(parents=True)
            old_summary_path = old_summary_dir / "auth-summary.json"
            new_summary_path = new_summary_dir / "auth-summary.json"
            old_summary_path.write_text(
                """
                {
                  "metrics": {
                    "http_req_duration": { "values": { "avg": 50, "p(95)": 60 } },
                    "http_req_failed": { "values": { "rate": 0.01 } },
                    "http_reqs": { "values": { "count": 80 } }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            new_summary_path.write_text(
                """
                {
                  "metrics": {
                    "http_req_duration": { "values": { "avg": 75, "p(95)": 90 } },
                    "checks": { "values": { "rate": 0.99 } },
                    "http_req_failed": { "values": { "rate": 0.02 } },
                    "iterations": { "values": { "count": 42 } },
                    "http_reqs": { "values": { "count": 100 } }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            (project_root / "tests" / "auth").mkdir(parents=True)
            (project_root / "tests" / "auth" / "auth.test.js").write_text(
                "export default function () {}",
                encoding="utf-8",
            )

            workspace = K6Workspace(str(project_root))
            document = workspace.generate_report_with_context(
                "auth",
                summary_path=new_summary_path,
                workflow_context={
                    "jira_issue": "DEV-42",
                    "dataset": "users.json",
                    "test_type": "load",
                    "script_path": "tests/auth/auth.test.js",
                },
            )

            self.assertIn("DEV-42", document.content)
            self.assertIn("users.json", document.content)
            self.assertIn("2026-04-13_bot_auth/auth-summary.json", document.content)
            self.assertIn("Latency p95: current=90 baseline=60 delta=+50.00%", document.content)
            self.assertIn("git add results/2026-04-14_bot_auth", document.content)
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)

    def test_k6_workspace_report_derives_rate_from_pass_fail_metrics(self) -> None:
        project_root = Path("tests") / ".tmp_k6_metric_normalization"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            summary_dir = project_root / "results" / "2026-04-18_bot_payments"
            summary_dir.mkdir(parents=True)
            summary_path = summary_dir / "payments-summary.json"
            summary_path.write_text(
                """
                {
                  "metrics": {
                    "http_req_duration": { "avg": 2.498, "p(95)": 3.8026 },
                    "checks": { "passes": 42, "fails": 42, "value": 0.5 },
                    "http_req_failed": { "passes": 42, "fails": 0, "value": 1 },
                    "iterations": { "count": 42 },
                    "http_reqs": { "count": 42 }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            (project_root / "tests" / "payments").mkdir(parents=True)
            (project_root / "tests" / "payments" / "payments.test.js").write_text(
                "export default function () {}",
                encoding="utf-8",
            )

            workspace = K6Workspace(str(project_root))
            document = workspace.generate_report_with_context(
                "payments",
                summary_path=summary_path,
                workflow_context={"jira_issue": "KAN-5", "dataset": "users.json"},
            )

            self.assertIn("Checks pass rate: 0.5", document.content)
            self.assertIn("HTTP failure rate: 0", document.content)
            self.assertIn("failure rate=0", document.content)
            self.assertIn("check pass rate=0.5", document.content)
            self.assertIn("HTTP request p(95): 3.8026 ms", document.content)
            self.assertIn("The run finished with p95=3.8026 ms", document.content)
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)

    def test_k6_run_message_includes_applied_skill_guidance(self) -> None:
        project_root = Path("tests") / ".tmp_k6_run_guidance"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            summary_dir = project_root / "results" / "2026-04-14_bot_auth"
            summary_dir.mkdir(parents=True)
            summary_path = summary_dir / "auth-summary.json"
            summary_path.write_text(
                """
                {
                  "metrics": {
                    "http_req_duration": { "values": { "avg": 54.63, "p(95)": 71.45 } },
                    "http_req_failed": { "values": { "rate": 0.01 } },
                    "http_reqs": { "values": { "count": 84 } }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            script_path = project_root / "tests" / "auth" / "auth.test.js"
            script_path.parent.mkdir(parents=True)
            script_path.write_text("export default function () {}", encoding="utf-8")
            workspace = K6Workspace(str(project_root))
            grafana = MagicMock()
            grafana.configured = True
            grafana.lookup_dashboard.return_value = (
                SearchDocument(
                    source_type="grafana",
                    title="Auth dashboard",
                    url="https://grafana.example/d/auth",
                    content="Auth dashboard",
                    metadata={"via": "mcp"},
                ),
                None,
            )
            connector = K6TestConnector(workspace=workspace, grafana_connector=grafana)
            run_result = MagicMock(
                exit_code=0,
                summary_path=summary_path,
                dashboard_path=summary_dir / "auth-dashboard.html",
                stdout="ok",
                stderr="",
                run_dir=summary_dir,
            )
            with patch.object(workspace, "run_test", return_value=run_result):
                result = connector.run(
                    ActionRequest(
                        operation="run",
                        target_system="k6",
                        target_type="test",
                        identifier="auth",
                    )
                )

            self.assertIn("Playbooks: docs/skills/k6-best-practices.", result.message)
            self.assertIn("Guidance:", result.message)
            self.assertIn("thresholds as the real test gate", result.message)
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)

    def test_k6_workflow_message_mentions_strategy_and_git_follow_up(self) -> None:
        project_root = Path("tests") / ".tmp_k6_workflow_guidance"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            summary_dir = project_root / "results" / "2026-04-14_bot_auth"
            summary_dir.mkdir(parents=True)
            summary_path = summary_dir / "auth-summary.json"
            summary_path.write_text(
                """
                {
                  "metrics": {
                    "http_req_duration": { "values": { "avg": 54.63, "p(95)": 71.45 } },
                    "http_req_failed": { "values": { "rate": 0.01 } },
                    "http_reqs": { "values": { "count": 84 } }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            script_path = project_root / "tests" / "auth" / "auth.test.js"
            script_path.parent.mkdir(parents=True)
            script_path.write_text("export default function () {}", encoding="utf-8")
            workspace = K6Workspace(str(project_root))
            connector = K6WorkflowConnector(workspace=workspace)
            run_result = MagicMock(
                exit_code=0,
                summary_path=summary_path,
                dashboard_path=summary_dir / "auth-dashboard.html",
                stdout="ok",
                stderr="",
                run_dir=summary_dir,
                script_path=script_path,
            )
            with patch.object(workspace, "run_test", return_value=run_result):
                result = connector.create(
                    ActionRequest(
                        operation="create",
                        target_system="k6",
                        target_type="workflow",
                        identifier="auth",
                        fields={"ticket": "DEV-42"},
                    )
                )

            self.assertIn("docs/skills/performance-testing-strategy", result.message)
            self.assertIn("Jira: DEV-42.", result.message)
            self.assertIn("Git: git add results/2026-04-14_bot_auth.", result.message)
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)

    def test_k6_workspace_auto_discovers_nested_local_suite(self) -> None:
        project_root = Path("tests") / ".tmp_local_k6_root"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            nested_suite = project_root / "performance"
            script_path = nested_suite / "tests" / "auth" / "auth.test.js"
            script_path.parent.mkdir(parents=True)
            script_path.write_text("export default function () {}", encoding="utf-8")

            workspace = K6Workspace(str(project_root))

            self.assertTrue(workspace.configured)
            self.assertEqual(workspace.project_root.resolve(), nested_suite.resolve())
            self.assertEqual(workspace.find_test_script("auth"), script_path.resolve())
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)

    def test_decode_subprocess_output_handles_non_utf8_bytes(self) -> None:
        self.assertEqual(_decode_subprocess_output(b"price=\x80"), "price=\u20ac")

    def test_jira_connector_prefers_mcp_adapter_for_search_and_read(self) -> None:
        handler = StubMCPHandler("jira")
        adapter = MCPAdapter(
            handlers={"jira": handler},
            config_path=Path("tests") / ".." / ".mcp.example.json",
        )
        connector = JiraConnector(mcp_adapter=adapter)

        results = connector.search("find ticket KAN-1", 3)
        action = connector.read(
            ActionRequest(
                operation="read",
                target_system="jira",
                target_type="ticket",
                identifier="KAN-1",
            )
        )

        self.assertEqual(results[0].metadata["via"], "mcp")
        self.assertEqual(action.document.metadata["via"], "mcp")
        self.assertEqual(handler.search_calls, [("find ticket KAN-1", 3)])
        self.assertEqual(handler.execute_calls[0].identifier, "KAN-1")

    def test_confluence_connector_prefers_mcp_adapter_for_search_and_create(self) -> None:
        handler = StubMCPHandler("confluence")
        adapter = MCPAdapter(
            handlers={"confluence": handler},
            config_path=Path("tests") / ".." / ".mcp.example.json",
        )
        connector = ConfluenceConnector(mcp_adapter=adapter)

        results = connector.search("onboarding doc", 2)
        action = connector.create(
            ActionRequest(
                operation="create",
                target_system="confluence",
                target_type="page",
                fields={"title": "Runbook", "body": "Hello"},
            )
        )

        self.assertEqual(results[0].metadata["via"], "mcp")
        self.assertEqual(action.document.metadata["via"], "mcp")
        self.assertEqual(handler.search_calls, [("onboarding doc", 2)])
        self.assertEqual(handler.execute_calls[0].fields["title"], "Runbook")

    def test_grafana_connector_prefers_mcp_adapter_for_search_and_read(self) -> None:
        handler = StubMCPHandler("grafana")
        adapter = MCPAdapter(
            handlers={"grafana": handler},
            config_path=Path("tests") / ".." / ".mcp.example.json",
        )
        connector = GrafanaConnector(mcp_adapter=adapter)

        results = connector.search("auth", 1)
        action = connector.read(
            ActionRequest(
                operation="read",
                target_system="grafana",
                target_type="dashboard",
                identifier="auth",
            )
        )

        self.assertEqual(results[0].metadata["via"], "mcp")
        self.assertEqual(action.document.metadata["via"], "mcp")
        self.assertEqual(handler.search_calls, [("auth", 1)])
        self.assertEqual(handler.execute_calls[0].identifier, "auth")

    def test_grafana_connector_can_use_mcp_server_env_for_direct_api_search(self) -> None:
        mcp_config_path = Path("tests") / ".tmp_grafana_mcp.json"
        mcp_config_path.write_text(
            """
            {
              "mcpServers": {
                "grafana": {
                  "command": "npx",
                  "args": ["-y", "mcp-grafana-npx"],
                  "env": {
                    "GRAFANA_URL": "http://grafana.local",
                    "GRAFANA_SERVICE_ACCOUNT_TOKEN": "real-token"
                  }
                }
              }
            }
            """.strip(),
            encoding="utf-8",
        )
        try:
            adapter = MCPAdapter(config_path=mcp_config_path)
            connector = GrafanaConnector(mcp_adapter=adapter)
            response = MagicMock()
            response.json.return_value = [
                {"uid": "auth1", "url": "/d/auth1/auth", "title": "Auth Dashboard", "type": "dash-db"}
            ]
            with patch.object(connector.session, "get", return_value=response) as get_mock:
                results = connector.search("auth", 1)

            self.assertTrue(connector.configured)
            self.assertEqual(results[0].url, "http://grafana.local/d/auth1/auth")
            self.assertEqual(results[0].metadata["via"], "mcp-config")
            get_mock.assert_called_once()
        finally:
            if mcp_config_path.exists():
                mcp_config_path.unlink()

    def test_grafana_connector_returns_friendly_message_when_url_is_not_grafana(self) -> None:
        mcp_config_path = Path("tests") / ".tmp_grafana_bad_target.json"
        mcp_config_path.write_text(
            """
            {
              "mcpServers": {
                "grafana": {
                  "command": "npx",
                  "args": ["-y", "mcp-grafana-npx"],
                  "env": {
                    "GRAFANA_URL": "http://localhost:3001",
                    "GRAFANA_SERVICE_ACCOUNT_TOKEN": "real-token"
                  }
                }
              }
            }
            """.strip(),
            encoding="utf-8",
        )
        try:
            adapter = MCPAdapter(config_path=mcp_config_path)
            connector = GrafanaConnector(mcp_adapter=adapter)
            response = MagicMock()
            response.status_code = 404
            error = requests.HTTPError("404 Client Error: Not Found for url", response=response)
            with patch.object(connector.session, "get", side_effect=error):
                action = connector.read(
                    ActionRequest(
                        operation="read",
                        target_system="grafana",
                        target_type="dashboard",
                        identifier="auth",
                    )
                )

            self.assertFalse(action.success)
            self.assertIn("did not expose the Grafana search API", action.message)
            self.assertIn("http://localhost:3001", action.message)
        finally:
            if mcp_config_path.exists():
                mcp_config_path.unlink()

    def test_as400_manual_connector_can_search_across_multiple_manuals(self) -> None:
        temp_path = Path("tests") / ".tmp_multi_manual"
        if temp_path.exists():
            shutil.rmtree(temp_path)
        temp_path.mkdir(parents=True, exist_ok=True)
        try:
            ibm_manual = temp_path / "IBM i Programming CL overview and concepts.txt"
            synon_manual = temp_path / "SYNON_CA2E_Tutorial.txt"
            ibm_manual.write_text(
                "WRKOBJ OBJ(MYOBJ) OBJTYPE(*FILE) lets you work with object information.\n",
                encoding="utf-8",
            )
            synon_manual.write_text(
                "YCRTMDL creates a Synon 2E model object for design work.\n",
                encoding="utf-8",
            )

            connector = AS400ManualConnector(
                manual_path=str(temp_path),
                embedder=FakeEmbedder(),
                index_path=str(temp_path / "multi-manual-index.npz"),
            )
            results = connector.search("what synon 2e command creates a model object", 3)
        finally:
            if temp_path.exists():
                shutil.rmtree(temp_path)

        self.assertTrue(results)
        self.assertEqual(results[0].source_type, "as400")
        self.assertEqual(results[0].metadata["manual_name"], "SYNON_CA2E_Tutorial")
        self.assertIn("Synon 2E tutorial", results[0].title)

    def test_as400_manual_connector_can_search_table_catalog_csv(self) -> None:
        temp_path = Path("tests") / ".tmp_table_catalog"
        if temp_path.exists():
            shutil.rmtree(temp_path)
        temp_path.mkdir(parents=True, exist_ok=True)
        try:
            catalog = temp_path / "FMS_TABLES.csv"
            catalog.write_text(
                "TABLE_NAME,TABLE_TEXT\n"
                "OSANCPP,Vendor WS Trans Physical file\n"
                "UAATCPP,WS API Log Physical file\n",
                encoding="utf-8",
            )

            connector = AS400ManualConnector(
                manual_path=str(catalog),
                embedder=FakeEmbedder(),
                index_path=str(temp_path / "table-catalog-index.npz"),
            )
            results = connector.search("what is table OSANCPP", 3)
        finally:
            if temp_path.exists():
                shutil.rmtree(temp_path)

        self.assertTrue(results)
        self.assertEqual(results[0].metadata["table_name"], "OSANCPP")
        self.assertEqual(results[0].metadata["source_kind"], "table_catalog")
        self.assertIn("FMS table catalog", results[0].title)

    def test_agent_can_answer_from_as400_manual_connector(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
            handle.write(
                "WRKOBJ OBJ(MYOBJ) OBJTYPE(*FILE) lets you work with object information.\n"
                "DSPOBJD OBJ(MYOBJ) OBJTYPE(*FILE) displays object descriptions.\n"
            )
            manual_path = handle.name

        responder = StubResponder()
        agent = BuildAgents(
            connectors=[
                AS400ManualConnector(
                    manual_path=manual_path,
                    embedder=FakeEmbedder(),
                    index_path=manual_path + ".npz",
                )
            ],
            responder=responder,
        )

        result = agent.answer("what command to use to see obj info")
        self.assertEqual(len(result.citations), 1)
        self.assertEqual(result.citations[0].source_type, "as400")
        self.assertIn("Understanding agent preferred sources: as400", result.reasoning_trace)

    def test_agent_can_answer_from_table_catalog_csv(self) -> None:
        temp_path = Path("tests") / ".tmp_table_answer"
        if temp_path.exists():
            shutil.rmtree(temp_path)
        temp_path.mkdir(parents=True, exist_ok=True)
        try:
            catalog = temp_path / "FMS_TABLES.csv"
            catalog.write_text(
                "TABLE_NAME,TABLE_TEXT\n"
                "OSANCPP,Vendor WS Trans Physical file\n",
                encoding="utf-8",
            )

            agent = BuildAgents(
                connectors=[
                    AS400ManualConnector(
                        manual_path=str(catalog),
                        embedder=FakeEmbedder(),
                        index_path=str(temp_path / "table-answer-index.npz"),
                    )
                ]
            )
            result = agent.answer("what is table OSANCPP")
        finally:
            if temp_path.exists():
                shutil.rmtree(temp_path)

        self.assertTrue(result.citations)
        self.assertEqual(result.citations[0].metadata["table_name"], "OSANCPP")
        self.assertIn("Vendor WS Trans Physical file", result.answer)

    def test_agent_can_list_vendor_related_physical_files(self) -> None:
        temp_path = Path("tests") / ".tmp_vendor_tables"
        if temp_path.exists():
            shutil.rmtree(temp_path)
        temp_path.mkdir(parents=True, exist_ok=True)
        try:
            catalog = temp_path / "FMS_TABLES.csv"
            catalog.write_text(
                "TABLE_NAME,TABLE_TEXT\n"
                "OSANCPP,Vendor WS Trans Physical file\n"
                "UCAGCPP,Vendor WS Patch Physical file\n"
                "UAAYREP,Vendor Migration Physical file\n"
                "UUAAREP,Vendor Physical file\n"
                "UAATCPP,WS API Log Physical file\n",
                encoding="utf-8",
            )

            agent = BuildAgents(
                connectors=[
                    AS400ManualConnector(
                        manual_path=str(catalog),
                        embedder=FakeEmbedder(),
                        index_path=str(temp_path / "vendor-index.npz"),
                    )
                ]
            )
            result = agent.answer("find all vendor related physical files")
        finally:
            if temp_path.exists():
                shutil.rmtree(temp_path)

        self.assertIn("OSANCPP", result.answer)
        self.assertIn("UCAGCPP", result.answer)
        self.assertIn("UAAYREP", result.answer)
        self.assertIn("UUAAREP", result.answer)

    def test_agent_can_list_direct_deposit_tables(self) -> None:
        temp_path = Path("tests") / ".tmp_direct_deposit_tables"
        if temp_path.exists():
            shutil.rmtree(temp_path)
        temp_path.mkdir(parents=True, exist_ok=True)
        try:
            catalog = temp_path / "FMS_TABLES.csv"
            catalog.write_text(
                "TABLE_NAME,TABLE_TEXT\n"
                "UAAQCPP,Direct Deposit WS Trans Physical file\n"
                "ABCDCPP,Direct Deposit Control Physical file\n"
                "OSANCPP,Vendor WS Trans Physical file\n",
                encoding="utf-8",
            )

            agent = BuildAgents(
                connectors=[
                    AS400ManualConnector(
                        manual_path=str(catalog),
                        embedder=FakeEmbedder(),
                        index_path=str(temp_path / "deposit-index.npz"),
                    )
                ]
            )
            result = agent.answer("which tables are about direct deposit")
        finally:
            if temp_path.exists():
                shutil.rmtree(temp_path)

        self.assertIn("UAAQCPP", result.answer)
        self.assertIn("ABCDCPP", result.answer)

    def test_agent_can_show_similar_files_to_a_table(self) -> None:
        temp_path = Path("tests") / ".tmp_similar_tables"
        if temp_path.exists():
            shutil.rmtree(temp_path)
        temp_path.mkdir(parents=True, exist_ok=True)
        try:
            catalog = temp_path / "FMS_TABLES.csv"
            catalog.write_text(
                "TABLE_NAME,TABLE_TEXT\n"
                "OSANCPP,Vendor WS Trans Physical file\n"
                "UCAGCPP,Vendor WS Patch Physical file\n"
                "UAAYREP,Vendor Migration Physical file\n"
                "UAATCPP,WS API Log Physical file\n",
                encoding="utf-8",
            )

            agent = BuildAgents(
                connectors=[
                    AS400ManualConnector(
                        manual_path=str(catalog),
                        embedder=FakeEmbedder(),
                        index_path=str(temp_path / "similar-index.npz"),
                    )
                ]
            )
            result = agent.answer("show similar files to OSANCPP")
        finally:
            if temp_path.exists():
                shutil.rmtree(temp_path)

        self.assertIn("UCAGCPP", result.answer)
        self.assertIn("UAAYREP", result.answer)
        self.assertNotIn("`OSANCPP` (", result.answer)

    def test_agent_can_answer_command_for_vendor_physical_file(self) -> None:
        temp_path = Path("tests") / ".tmp_vendor_command"
        if temp_path.exists():
            shutil.rmtree(temp_path)
        temp_path.mkdir(parents=True, exist_ok=True)
        try:
            catalog = temp_path / "FMS_TABLES.csv"
            catalog.write_text(
                "TABLE_NAME,TABLE_TEXT\n"
                "UUAAREP,Vendor Physical file\n"
                "USB5REP,Architect to Vendor Physical file\n",
                encoding="utf-8",
            )

            agent = BuildAgents(
                connectors=[
                    AS400ManualConnector(
                        manual_path=str(catalog),
                        embedder=FakeEmbedder(),
                        index_path=str(temp_path / "vendor-command-index.npz"),
                    )
                ]
            )
            result = agent.answer("what command to use in as400 to open the vendor physical file")
        finally:
            if temp_path.exists():
                shutil.rmtree(temp_path)

        self.assertIn("DSPPFM FILE(UUAAREP)", result.answer)
        self.assertEqual(result.citations[0].metadata["table_name"], "UUAAREP")

    def test_as400_command_query_prefers_manual_pages_over_table_catalog_hits(self) -> None:
        temp_path = Path("tests") / ".tmp_manual_over_catalog"
        if temp_path.exists():
            shutil.rmtree(temp_path)
        temp_path.mkdir(parents=True, exist_ok=True)
        try:
            manual = temp_path / "IBM i Programming CL overview and concepts.txt"
            manual.write_text(
                "Use DLTF FILE(EMPLOYEE) to delete a physical file.\n"
                "Use DSPPFM FILE(EMPLOYEE) to display file members and records.\n",
                encoding="utf-8",
            )
            catalog = temp_path / "FMS_TABLES.csv"
            catalog.write_text(
                "TABLE_NAME,TABLE_TEXT\n"
                "UUAAREP,Vendor Physical file\n"
                "UAATCPP,WS API Log Physical file\n",
                encoding="utf-8",
            )

            connector = AS400ManualConnector(
                manual_path=f"{manual};{catalog}",
                embedder=FakeEmbedder(),
                index_path=str(temp_path / "manual-over-catalog-index.npz"),
            )
            results = connector.search("what command to delete employee table in as400", 3)
        finally:
            if temp_path.exists():
                shutil.rmtree(temp_path)

        self.assertTrue(results)
        self.assertTrue(all(result.metadata["source_kind"] == "manual_page" for result in results))
        self.assertIn("DLTF", " ".join(results[0].metadata.get("command_candidates", [])))

    def test_as400_command_query_returns_no_catalog_guess_when_nothing_relevant_is_found(self) -> None:
        temp_path = Path("tests") / ".tmp_no_catalog_guess"
        if temp_path.exists():
            shutil.rmtree(temp_path)
        temp_path.mkdir(parents=True, exist_ok=True)
        try:
            catalog = temp_path / "FMS_TABLES.csv"
            catalog.write_text(
                "TABLE_NAME,TABLE_TEXT\n"
                "UUAAREP,Vendor Physical file\n"
                "UAATCPP,WS API Log Physical file\n",
                encoding="utf-8",
            )

            agent = BuildAgents(
                connectors=[
                    AS400ManualConnector(
                        manual_path=str(catalog),
                        embedder=FakeEmbedder(),
                        index_path=str(temp_path / "no-catalog-guess-index.npz"),
                    )
                ]
            )
            result = agent.answer("what command to delete employee table in as400")
        finally:
            if temp_path.exists():
                shutil.rmtree(temp_path)

        self.assertEqual(result.citations, [])
        self.assertIn("I could not find enough evidence", result.answer)

    def test_follow_up_table_records_question_stays_on_last_table(self) -> None:
        temp_path = Path("tests") / ".tmp_followup_table"
        if temp_path.exists():
            shutil.rmtree(temp_path)
        temp_path.mkdir(parents=True, exist_ok=True)
        try:
            catalog = temp_path / "FMS_TABLES.csv"
            catalog.write_text(
                "TABLE_NAME,TABLE_TEXT\n"
                "UUAAREP,Vendor Physical file\n"
                "USB5REP,Architect to Vendor Physical file\n",
                encoding="utf-8",
            )

            memory = RedisConversationMemory(
                redis_client=FakeRedis(),
                key_prefix="testbot",
                max_turns=3,
                ttl_seconds=120,
            )
            agent = BuildAgents(
                connectors=[
                    AS400ManualConnector(
                        manual_path=str(catalog),
                        embedder=FakeEmbedder(),
                        index_path=str(temp_path / "followup-table-index.npz"),
                    )
                ],
                memory=memory,
            )
            first = agent.answer(
                "what command to use in as400 to open the vendor physical file",
                conversation_id="table-followup",
            )
            second = agent.answer(
                "how do I see the records in that table",
                conversation_id="table-followup",
            )
        finally:
            if temp_path.exists():
                shutil.rmtree(temp_path)

        self.assertEqual(first.citations[0].metadata["table_name"], "UUAAREP")
        self.assertEqual(second.citations[0].metadata["table_name"], "UUAAREP")
        self.assertIn("DSPPFM FILE(UUAAREP)", second.answer)
        self.assertIn(
            "Expanded the follow-up question using the last referenced document",
            second.reasoning_trace,
        )

    def test_as400_distribution_list_query_prefers_wrkdstl(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
            handle.write(
                "WRKDSTL shows distribution list details and summaries.\n"
                "DSPDSTL displays distribution list details.\n"
            )
            manual_path = handle.name

        connector = AS400ManualConnector(
            manual_path=manual_path,
            embedder=FakeEmbedder(),
            index_path=manual_path + ".npz",
        )
        results = connector.search("what as400 command to use if I want to create an distribution list", 3)

        self.assertTrue(results)
        joined = " ".join(results[0].metadata.get("command_candidates", []))
        self.assertIn("WRKDSTL", joined)

    def test_as400_distribution_list_follow_up_returns_wrkdstl(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
            handle.write(
                "WRKDSTL shows distribution list details and summaries.\n"
                "DSPDSTL displays distribution list details.\n"
            )
            manual_path = handle.name

        agent = BuildAgents(
            connectors=[
                AS400ManualConnector(
                    manual_path=manual_path,
                    embedder=FakeEmbedder(),
                    index_path=manual_path + ".npz",
                )
            ]
        )

        first = agent.answer(
            "what as400 command to use if I want to create an distribution list",
            conversation_id="dist-list-1",
        )
        second = agent.answer("how to work on one then", conversation_id="dist-list-1")

        self.assertTrue(first.citations)
        self.assertTrue(second.citations)
        self.assertEqual(first.citations[0].source_type, "as400")
        self.assertEqual(second.citations[0].source_type, "as400")

    def test_as400_explicit_command_query_prefers_matching_command_page(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
            handle.write(
                "PRTJOBRPT prints job interval collection data reports.\n"
                "PRTQ is a print queue abbreviation and not the requested command.\n"
            )
            manual_path = handle.name

        agent = BuildAgents(
            connectors=[
                AS400ManualConnector(
                    manual_path=manual_path,
                    embedder=FakeEmbedder(),
                    index_path=manual_path + ".npz",
                )
            ]
        )

        result = agent.answer("what is this command for PRTJOBRPT")

        self.assertTrue(result.citations)
        self.assertEqual(result.citations[0].source_type, "as400")
        self.assertIn("PRTJOBRPT", result.answer)

    def test_as400_command_definition_changes_question_returns_list_not_command(self) -> None:
        evidence_text = (
            "[1] Source: as400\n"
            "Title: IBM i CL manual page 362\n"
            "URL: manual#page=362\n"
            "Metadata: {}\n"
            "Content: The following changes can be made to the command definition statements, "
            "but may cause the procedure or program that uses the command to function differently: "
            "Change the meaning of a value. Change the default value. "
            "Change a SNGVAL parameter to a SPCVAL parameter. "
            "Change a value to a SNGVAL parameter. "
            "Change a list to a list within a list. "
            "Change case value from *MIXED to *MONO. "
        )

        from src.llm import OpenAIResponder

        result = OpenAIResponder._fallback(
            "whatf changes can be made to the command definition statements, but may cause the procedure or program that uses the command to function differently",
            evidence_text,
            [],
        )
        self.assertIn("Change the meaning of a value.", result)
        self.assertNotIn("Use `CHGCMD`.", result)

    def test_semantic_index_cache_is_reused_for_same_manual(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
            handle.write("WRKOBJ OBJ(MYOBJ) OBJTYPE(*FILE) lets you work with object information.\n")
            manual_path = handle.name

        connector = AS400ManualConnector(
            manual_path=manual_path,
            embedder=FakeEmbedder(),
            index_path=manual_path + ".npz",
        )
        first = connector.search("object info command", 2)
        second = connector.search("object info command", 2)

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertTrue(Path(manual_path + ".npz").exists())

    def test_answer_returns_ranked_citations(self) -> None:
        jira_doc = SearchDocument(
            source_type="jira",
            title="ABC-123: Payment gateway outage",
            url="https://jira.local/browse/ABC-123",
            content="Outage status and investigation steps.",
            metadata={"status": "In Progress"},
        )
        confluence_doc = SearchDocument(
            source_type="confluence",
            title="Payment Gateway Runbook",
            url="https://conf.local/pages/1",
            content="Runbook for payment gateway outage recovery.",
            metadata={"space": "OPS"},
        )
        responder = StubResponder()
        agent = BuildAgents(
            connectors=[
                StubConnector("jira", "ticket", documents=[jira_doc]),
                StubConnector("confluence", "page", documents=[confluence_doc]),
            ],
            responder=responder,
        )

        result = agent.answer("payment gateway outage")
        self.assertEqual(len(result.citations), 2)
        self.assertIn("Selected tools:", result.reasoning_trace[0])
        self.assertTrue(result.answer.startswith("ANSWER::payment gateway outage"))
        self.assertEqual(responder.calls[0][2], [])

    def test_answer_uses_redis_memory_for_follow_up_context(self) -> None:
        responder = StubResponder()
        memory = RedisConversationMemory(
            redis_client=FakeRedis(),
            key_prefix="testbot",
            max_turns=2,
            ttl_seconds=120,
        )
        memory.append_turn("conv-1", "What broke?", "The payment gateway is down.")
        jira_doc = SearchDocument(
            source_type="jira",
            title="ABC-123: Payment gateway outage",
            url="https://jira.local/browse/ABC-123",
            content="Outage status and investigation steps.",
            metadata={"status": "In Progress"},
        )
        agent = BuildAgents(
            connectors=[StubConnector("jira", "ticket", documents=[jira_doc])],
            responder=responder,
            memory=memory,
        )

        result = agent.answer("What is the latest update?", conversation_id="conv-1")
        self.assertTrue(result.answer.endswith("::2"))
        self.assertIn("Loaded 2 prior messages from conversation memory", result.reasoning_trace[0])
        self.assertEqual(responder.calls[0][2][0]["content"], "What broke?")
        stored = memory.get_history("conv-1")
        self.assertEqual(len(stored), 4)
        self.assertEqual(stored[-1]["content"], result.answer)

    def test_redis_memory_trims_to_max_turns(self) -> None:
        fake_redis = FakeRedis()
        memory = RedisConversationMemory(
            redis_client=fake_redis,
            key_prefix="testbot",
            max_turns=1,
            ttl_seconds=90,
        )

        memory.append_turn("conv-2", "first q", "first a")
        memory.append_turn("conv-2", "second q", "second a")

        history = memory.get_history("conv-2")
        self.assertEqual(
            history,
            [
                {"role": "user", "content": "second q"},
                {"role": "assistant", "content": "second a"},
            ],
        )
        self.assertEqual(fake_redis.expirations["testbot:memory:conv-2"], 90)

    def test_memory_returns_last_citation_for_follow_up_actions(self) -> None:
        memory = RedisConversationMemory(
            redis_client=FakeRedis(),
            key_prefix="testbot",
            max_turns=2,
            ttl_seconds=90,
        )
        citation = SearchDocument(
            source_type="jira",
            title="KAN-1: Invoice Data Fix",
            url="https://jira.local/browse/KAN-1",
            content="Fix the invoice import.",
            metadata={"key": "KAN-1"},
        )

        memory.append_turn("conv-3", "Which ticket is the invoice fix?", "It is KAN-1.", [citation])

        last_citation = memory.get_last_citation("conv-3")
        self.assertIsNotNone(last_citation)
        assert last_citation is not None
        self.assertEqual(last_citation.metadata["key"], "KAN-1")

    def test_memory_without_redis_still_keeps_local_history(self) -> None:
        memory = RedisConversationMemory(
            redis_client=None,
            key_prefix="testbot",
            max_turns=2,
            ttl_seconds=90,
        )
        citation = SearchDocument(
            source_type="jira",
            title="KAN-1: Invoice Data Fix",
            url="https://jira.local/browse/KAN-1",
            content="Fix the invoice import.",
            metadata={"key": "KAN-1"},
        )

        memory.append_turn("conv-local", "what ticket is about delete inv", "It is KAN-1.", [citation])

        history = memory.get_history("conv-local")
        last_citation = memory.get_last_citation("conv-local")
        self.assertEqual(len(history), 2)
        self.assertEqual(memory.backend_label, "local-only")
        self.assertIsNotNone(last_citation)
        assert last_citation is not None
        self.assertEqual(last_citation.metadata["key"], "KAN-1")

    def test_action_request_is_parsed_from_explicit_command(self) -> None:
        request = parse_action_request(
            'create jira ticket summary="Build RAG" description="Create the bot" issue_type="Task"'
        )
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.operation, "create")
        self.assertEqual(request.target_system, "jira")
        self.assertEqual(request.target_type, "ticket")
        self.assertEqual(request.fields["summary"], "Build RAG")
        self.assertEqual(request.fields["issue_type"], "Task")

    def test_action_request_is_parsed_from_natural_slack_command(self) -> None:
        request = parse_action_request(
            "create a ticket in jira: title:as400 fix description: reset user ZENGW's account"
        )
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.operation, "create")
        self.assertEqual(request.target_system, "jira")
        self.assertEqual(request.target_type, "ticket")
        self.assertEqual(request.fields["summary"], "as400 fix")
        self.assertEqual(request.fields["description"], "reset user ZENGW's account")

    def test_action_request_is_parsed_from_jira_performance_workflow_command(self) -> None:
        request = parse_action_request("test jira DEV-42 duration=30s vus=2")
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.operation, "run")
        self.assertEqual(request.target_system, "jira")
        self.assertEqual(request.target_type, "workflow")
        self.assertEqual(request.identifier, "DEV-42")
        self.assertEqual(request.fields["duration"], "30s")
        self.assertEqual(request.fields["vus"], "2")

    def test_action_request_normalizes_lowercase_jira_workflow_key(self) -> None:
        request = parse_action_request("test kan-7")
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.identifier, "KAN-7")
    def test_action_request_is_parsed_from_short_jira_performance_workflow_command(self) -> None:
        request = parse_action_request("test KAN-5")
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.operation, "run")
        self.assertEqual(request.target_system, "jira")
        self.assertEqual(request.target_type, "workflow")
        self.assertEqual(request.identifier, "KAN-5")

    def test_llm_intent_routes_natural_jira_workflow_request(self) -> None:
        responder = StubResponder()

        def staged_call_function(
            system_prompt: str,
            user_prompt: str,
            function_name: str,
            function_description: str,
            parameters: dict,
            temperature: float = 0.1,
        ) -> dict:
            responder.function_calls.append(
                (system_prompt, user_prompt, function_name, function_description, parameters, temperature)
            )
            if function_name == "classify_action_request":
                return {
                    "is_action": True,
                    "operation": "run",
                    "target_system": "jira",
                    "target_type": "workflow",
                    "identifier": "KAN-4",
                    "fields": {},
                }
            return {}

        responder.call_function = staged_call_function
        connector = RunStubConnector("jira", "workflow")
        agent = BuildAgents(
            connectors=[connector],
            responder=responder,
        )

        result = agent.answer("generate test plan, script for KAN-4 and get me the test results")

        self.assertEqual(result.answer, "Executed jira workflow.")
        self.assertEqual(connector.executed_requests[-1].identifier, "KAN-4")

    def test_deterministic_fallback_routes_natural_jira_workflow_request_when_llm_returns_no_action(self) -> None:
        responder = StubResponder()
        responder.call_function = lambda *args, **kwargs: {
            "is_action": False,
            "operation": "read",
            "target_system": "jira",
            "target_type": "ticket",
            "identifier": "",
            "fields": {},
        }
        connector = RunStubConnector("jira", "workflow")
        agent = BuildAgents(
            connectors=[connector],
            responder=responder,
        )

        result = agent.answer("generate test plan and k6 script for kan-4, and get the performance result")

        self.assertEqual(result.answer, "Executed jira workflow.")
        self.assertEqual(connector.executed_requests[-1].identifier, "KAN-4")

    def test_contextual_action_request_resolves_close_it_from_last_ticket(self) -> None:
        reference = SearchDocument(
            source_type="jira",
            title="KAN-1: Invoice Data Fix",
            url="https://jira.local/browse/KAN-1",
            content="Fix the invoice import.",
            metadata={"key": "KAN-1", "status": "To Do"},
        )

        request = parse_contextual_action_request("close it", reference)
        self.assertIsNotNone(request)
        assert request is not None
        self.assertEqual(request.operation, "update")
        self.assertEqual(request.target_system, "jira")
        self.assertEqual(request.identifier, "KAN-1")
        self.assertEqual(request.fields["status"], "closed")

    def test_crud_command_executes_against_matching_connector(self) -> None:
        jira = StubConnector("jira", "ticket")
        confluence = StubConnector("confluence", "page")
        agent = BuildAgents(
            connectors=[jira, confluence],
            responder=StubResponder(),
        )

        result = agent.answer('update jira ticket KAN-1 summary="New title" status="In Progress"')
        self.assertEqual(result.answer, "Updated jira ticket.")
        self.assertEqual(len(result.citations), 1)
        self.assertEqual(jira.executed_requests[0].identifier, "KAN-1")
        self.assertEqual(jira.executed_requests[0].fields["status"], "In Progress")
        self.assertEqual(confluence.executed_requests, [])

    def test_openai_responder_call_function_parses_tool_arguments(self) -> None:
        responder = OpenAIResponder()
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "decide_ticket_workflow",
                                    "arguments": '{"ordered_skills":["k6-best-practices"]}',
                                },
                            }
                        ]
                    }
                }
            ]
        }
        with patch("src.llm.requests.post", return_value=response) as post_mock:
            payload = responder.call_function(
                system_prompt="Pick a skill.",
                user_prompt="Ticket content",
                function_name="decide_ticket_workflow",
                function_description="Pick the skills.",
                parameters={
                    "type": "object",
                    "properties": {"ordered_skills": {"type": "array", "items": {"type": "string"}}},
                    "required": ["ordered_skills"],
                },
            )

        self.assertEqual(payload["ordered_skills"], ["k6-best-practices"])
        self.assertEqual(post_mock.call_args.kwargs["json"]["tool_choice"]["function"]["name"], "decide_ticket_workflow")

    def test_jira_workflow_still_fails_without_model_decision_or_perf_signal(self) -> None:
        ticket = SearchDocument(
            source_type="jira",
            title="DEV-88: Update auth copy",
            url="https://jira.local/browse/DEV-88",
            content="Update the user-facing login page copy for clarity.",
            metadata={"key": "DEV-88"},
        )
        responder = StubResponder()
        connector = JiraPerformanceWorkflowConnector(
            jira_connector=FakeJiraWorkflowDependency(ticket),  # type: ignore[arg-type]
            workspace=K6Workspace(),
            skill_catalog=ProjectSkillCatalog(),
            responder=responder,  # type: ignore[arg-type]
        )

        result = connector.execute(
            ActionRequest(
                operation="run",
                target_system="jira",
                target_type="workflow",
                identifier="DEV-88",
            )
        )

        self.assertFalse(result.success)
        self.assertIn("Could not determine workflow decision", result.message)
        self.assertEqual(len(responder.function_calls), 1)

    def test_jira_performance_workflow_generates_script_runs_and_comments(self) -> None:
        project_root = Path("tests") / ".tmp_jira_perf_workflow"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            script_seed = project_root / "tests" / "auth" / "auth.test.js"
            script_seed.parent.mkdir(parents=True)
            script_seed.write_text("export default function () {}", encoding="utf-8")
            workspace = K6Workspace(str(project_root))
            ticket = SearchDocument(
                source_type="jira",
                title="DEV-42: Auth login load test",
                url="https://jira.local/browse/DEV-42",
                content=(
                    "Service: auth\n"
                    "Endpoint: POST /api/auth/login\n"
                    "SLA: p95 < 450ms\n"
                    "Error rate < 0.5%\n"
                    "VUs: 2\n"
                    "Duration: 30s\n"
                    "Dataset: users.json\n"
                    "- Validate 200 responses\n"
                    "- Validate token exists\n"
                ),
                metadata={"key": "DEV-42"},
            )
            jira_dependency = FakeJiraWorkflowDependency(ticket)
            responder = StubResponder()
            def staged_call_function(
                system_prompt: str,
                user_prompt: str,
                function_name: str,
                function_description: str,
                parameters: dict,
                temperature: float = 0.1,
            ) -> dict:
                responder.function_calls.append(
                    (system_prompt, user_prompt, function_name, function_description, parameters, temperature)
                )
                if function_name == "decide_ticket_workflow":
                    return {
                        "execution_mode": "plan_then_run",
                        "ordered_skills": ["performance-testing-strategy", "k6-best-practices"],
                        "rationale": [
                            "The ticket defines workload and SLA details first.",
                            "The ticket then needs a runnable k6 script.",
                        ],
                    }
                if function_name == "extract_ticket_performance_plan":
                    return {
                        "service": "auth",
                        "endpoint_method": "POST",
                        "endpoint_path": "/api/auth/login",
                        "sla_p95_ms": 450,
                        "error_rate_percent": 0.5,
                        "vus": 2,
                        "duration": "30s",
                        "dataset": "users.json",
                        "test_type": "load",
                        "criteria": ["Validate 200 responses", "Validate token exists"],
                        "strategy_notes": ["Smoke before load.", "Use realistic user credentials."],
                    }
                return {}

            def staged_complete(system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
                responder.completions.append((system_prompt, user_prompt, temperature))
                if "Return only raw JavaScript" in system_prompt:
                    return """import http from 'k6/http';
import { check, group, sleep } from 'k6';
import { SharedArray } from 'k6/data';
import { htmlReport, textSummary } from '../../lib/summary.js';

export const options = {
  scenarios: {
    approved: {
      executor: 'constant-vus',
      vus: 2,
      duration: '30s',
      exec: 'approvedScenario',
      gracefulStop: '30s',
    },
    rejected: {
      executor: 'constant-vus',
      vus: 1,
      duration: '30s',
      exec: 'rejectedScenario',
      gracefulStop: '30s',
      startTime: '0s',
    },
  },
  thresholds: {
    'http_req_duration{service:payments}': ['p(95)<800'],
    'http_req_failed{service:payments}': ['rate<0.001'],
    checks: ['rate>0.99'],
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:3005';
const testUsers = new SharedArray('ticket-users', () => JSON.parse(open('../../data/users.json')));

function traceHeaders() {
  return { 'Content-Type': 'application/json', traceparent: `00-${__VU}` };
}

export function setup() {
  return { baseUrl: BASE_URL };
}

export function approvedScenario(context) {
  const payload = JSON.stringify({ order_id: `ORD-${__VU}`, payment_method: 'credit_card', card_number: '4111111111111111' });
  group('approved payment', () => {
    const res = http.post(`${context.baseUrl}/api/payments/process`, payload, { headers: traceHeaders(), tags: { service: 'payments', jira: 'KAN-5' } });
    check(res, {
      'status 201 approved': (r) => r.status === 201,
      'approved status': (r) => r.json('status') === 'approved',
      'approved transaction': (r) => !!r.json('transaction_id'),
    });
    sleep(1);
  });
}

export function rejectedScenario(context) {
  const payload = JSON.stringify({ order_id: `ORD-R-${__VU}`, payment_method: 'credit_card', card_number: '4000000000000002' });
  group('rejected payment', () => {
    const res = http.post(`${context.baseUrl}/api/payments/process`, payload, { headers: traceHeaders(), tags: { service: 'payments', jira: 'KAN-5' } });
    check(res, {
      'status 201 rejected': (r) => r.status === 201,
      'rejected status': (r) => r.json('status') === 'rejected',
      'rejected reason': (r) => r.json('reason') === 'Card declined',
    });
    sleep(1);
  });
}

export default function (context) {
  approvedScenario(context);
}

export function handleSummary(data) {
  return {
    stdout: textSummary(data, { indent: ' ' }),
    'results/kan-5-payments-report.html': htmlReport(data),
  };
}
"""
                return "## Skill-Driven Technical Analysis\n\n- Technical analysis generated from eval-backed prompts.\n\n## Skill-Driven Business Analysis\n\n- Business analysis generated from eval-backed prompts."
            responder.call_function = staged_call_function
            responder.complete = staged_complete
            connector = JiraPerformanceWorkflowConnector(
                jira_connector=jira_dependency,  # type: ignore[arg-type]
                workspace=workspace,
                skill_catalog=ProjectSkillCatalog(),
                responder=responder,  # type: ignore[arg-type]
            )
            summary_dir = project_root / "results" / "2026-04-15_bot_auth"
            summary_dir.mkdir(parents=True)
            summary_path = summary_dir / "auth-summary.json"
            summary_path.write_text(
                """
                {
                  "metrics": {
                    "http_req_duration": { "avg": 120, "p(95)": 240 },
                    "checks": { "passes": 80, "fails": 0, "value": 1 },
                    "http_req_failed": { "rate": 0.001 },
                    "http_reqs": { "count": 80 }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            run_result = MagicMock(
                exit_code=0,
                summary_path=summary_path,
                dashboard_path=summary_dir / "auth-dashboard.html",
                stdout="ok",
                stderr="",
                run_dir=summary_dir,
                script_path=project_root / "tests" / "auth" / "auth.dev-42.test.js",
            )
            with patch.object(workspace, "run_script", return_value=run_result):
                result = connector.execute(
                    ActionRequest(
                        operation="run",
                        target_system="jira",
                        target_type="workflow",
                        identifier="DEV-42",
                    )
                )

            self.assertTrue(result.success)
            generated_script = project_root / "tests" / "auth" / "auth.dev-42.test.js"
            self.assertTrue(generated_script.exists())
            generated_text = generated_script.read_text(encoding="utf-8")
            self.assertIn("SharedArray", generated_text)
            self.assertIn("http_req_duration{service:auth}", generated_text)
            self.assertIn("/api/auth/login", generated_text)
            self.assertEqual(len(responder.function_calls), 2)
            self.assertEqual(len(responder.completions), 1)
            self.assertIn("docs/skills/performance-testing-strategy", result.message)
            self.assertIn("docs/skills/k6-best-practices", result.message)
            self.assertNotIn("docs/skills/performance-report-analysis", result.message)
            self.assertIn(
                "Playbooks: docs/skills/performance-testing-strategy, docs/skills/k6-best-practices.",
                result.message,
            )
            self.assertIn("Report:", result.message)
            self.assertIn("Slack Report Preview:", result.message)
            self.assertIn("## Executive Summary", result.message)
            self.assertEqual(jira_dependency.comments[0][0], "DEV-42")
            self.assertIn("k6 best practices skill used to generate the runnable script", jira_dependency.comments[0][1])
            self.assertNotIn("Performance report analysis skill used to produce the final report.", jira_dependency.comments[0][1])
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)

    def test_jira_workflow_fallback_decision_can_run_concrete_ticket(self) -> None:
        project_root = Path("tests") / ".tmp_jira_perf_workflow_fallback"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            script_seed = project_root / "tests" / "auth" / "auth.test.js"
            script_seed.parent.mkdir(parents=True)
            script_seed.write_text("export default function () {}", encoding="utf-8")
            workspace = K6Workspace(str(project_root))
            ticket = SearchDocument(
                source_type="jira",
                title="KAN-7: Auth login load test",
                url="https://jira.local/browse/KAN-7",
                content=(
                    "Service: auth\n"
                    "Endpoint: POST /api/auth/login\n"
                    "SLA: p95 < 450ms\n"
                    "Error rate < 0.5%\n"
                    "VUs: 2\n"
                    "Duration: 30s\n"
                    "Please generate and run the k6 workflow.\n"
                ),
                metadata={"key": "KAN-7"},
            )
            jira_dependency = FakeJiraWorkflowDependency(ticket)
            responder = StubResponder()

            def staged_call_function(
                system_prompt: str,
                user_prompt: str,
                function_name: str,
                function_description: str,
                parameters: dict,
                temperature: float = 0.1,
            ) -> dict:
                responder.function_calls.append(
                    (system_prompt, user_prompt, function_name, function_description, parameters, temperature)
                )
                if function_name == "extract_ticket_performance_plan":
                    return {
                        "service": "auth",
                        "endpoint_method": "POST",
                        "endpoint_path": "/api/auth/login",
                        "sla_p95_ms": 450,
                        "error_rate_percent": 0.5,
                        "vus": 2,
                        "duration": "30s",
                        "dataset": "users.json",
                        "test_type": "load",
                        "criteria": ["Validate 200 responses"],
                        "strategy_notes": ["Run a smoke check before load."],
                    }
                return {}

            def staged_complete(system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
                responder.completions.append((system_prompt, user_prompt, temperature))
                if "Return only raw JavaScript" in system_prompt:
                    return """import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  thresholds: {
    'http_req_duration{service:auth}': ['p(95)<450'],
  },
};

export default function () {
  const res = http.post(`${__ENV.BASE_URL || 'http://127.0.0.1:3001'}/api/auth/login`, JSON.stringify({ username: 'u', password: 'p' }));
  check(res, { 'status 200': (r) => r.status === 200 });
  sleep(1);
}
"""
                return "## Skill-Driven Technical Analysis\n\n- Fallback workflow completed."

            responder.call_function = staged_call_function
            responder.complete = staged_complete
            connector = JiraPerformanceWorkflowConnector(
                jira_connector=jira_dependency,  # type: ignore[arg-type]
                workspace=workspace,
                skill_catalog=ProjectSkillCatalog(),
                responder=responder,  # type: ignore[arg-type]
            )
            summary_dir = project_root / "results" / "2026-04-18_bot_auth"
            summary_dir.mkdir(parents=True)
            summary_path = summary_dir / "auth-summary.json"
            summary_path.write_text(
                """
                {
                  "metrics": {
                    "http_req_duration": { "avg": 120, "p(95)": 240 },
                    "checks": { "passes": 80, "fails": 0, "value": 1 },
                    "http_req_failed": { "rate": 0.001 },
                    "http_reqs": { "count": 80 }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            run_result = MagicMock(
                exit_code=0,
                summary_path=summary_path,
                dashboard_path=summary_dir / "auth-dashboard.html",
                stdout="ok",
                stderr="",
                run_dir=summary_dir,
                script_path=project_root / "tests" / "auth" / "auth.kan-7.test.js",
            )
            with patch.object(workspace, "run_script", return_value=run_result):
                result = connector.execute(
                    ActionRequest(
                        operation="run",
                        target_system="jira",
                        target_type="workflow",
                        identifier="KAN-7",
                    )
                )

            self.assertTrue(result.success)
            self.assertEqual(len(responder.function_calls), 2)
            self.assertIn("Completed Jira performance workflow for KAN-7.", result.message)
            self.assertIn("docs/skills/performance-testing-strategy", result.message)
            self.assertIn("docs/skills/k6-best-practices", result.message)
            self.assertNotIn("docs/skills/performance-report-analysis", result.message)
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)

    def test_jira_workflow_fallback_plan_recovers_payments_ticket_shape(self) -> None:
        project_root = Path("tests") / ".tmp_jira_perf_workflow_plan_fallback"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            script_seed = project_root / "tests" / "payments" / "payments.test.js"
            script_seed.parent.mkdir(parents=True)
            script_seed.write_text("export default function () {}", encoding="utf-8")
            workspace = K6Workspace(str(project_root))
            ticket = SearchDocument(
                source_type="jira",
                title="KAN-5: Develop payment script",
                url="https://jira.local/browse/KAN-5",
                content=(
                    "Interface: POST http://localhost:3005/api/payments/process\n"
                    "Scenarios: approved / rejected\n"
                    "Tag { service: 'payments' }\n"
                    "Thresholds reference KAN-4: P95 < 800ms, error rate < 0.1%\n"
                    "Suggested split: 80% approved / 20% rejected\n"
                    "traceparent propagated - unified trace visible in Tempo\n"
                ),
                metadata={"key": "KAN-5"},
            )
            jira_dependency = FakeJiraWorkflowDependency(ticket)
            responder = StubResponder()

            def staged_call_function(
                system_prompt: str,
                user_prompt: str,
                function_name: str,
                function_description: str,
                parameters: dict,
                temperature: float = 0.1,
            ) -> dict:
                responder.function_calls.append(
                    (system_prompt, user_prompt, function_name, function_description, parameters, temperature)
                )
                if function_name == "decide_ticket_workflow":
                    return {
                        "execution_mode": "plan_then_run",
                        "ordered_skills": ["performance-testing-strategy", "k6-best-practices"],
                        "rationale": ["Concrete payment endpoint and SLA are present in the ticket."],
                    }
                return {}

            def staged_complete(system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
                responder.completions.append((system_prompt, user_prompt, temperature))
                return ""

            responder.call_function = staged_call_function
            responder.complete = staged_complete
            connector = JiraPerformanceWorkflowConnector(
                jira_connector=jira_dependency,  # type: ignore[arg-type]
                workspace=workspace,
                skill_catalog=ProjectSkillCatalog(),
                responder=responder,  # type: ignore[arg-type]
            )
            summary_dir = project_root / "results" / "2026-04-18_bot_payments"
            summary_dir.mkdir(parents=True)
            summary_path = summary_dir / "payments-summary.json"
            summary_path.write_text(
                """
                {
                  "metrics": {
                    "http_req_duration": { "p(95)": 700, "avg": 500 },
                    "checks": { "passes": 80, "fails": 0, "value": 1 },
                    "http_req_failed": { "passes": 80, "fails": 0, "value": 1 },
                    "http_reqs": { "count": 80 }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            run_result = MagicMock(
                exit_code=0,
                summary_path=summary_path,
                dashboard_path=summary_dir / "payments-dashboard.html",
                stdout="ok",
                stderr="",
                run_dir=summary_dir,
                script_path=project_root / "tests" / "payments" / "payments.kan-5.test.js",
            )
            with patch.object(workspace, "run_script", return_value=run_result):
                result = connector.execute(
                    ActionRequest(
                        operation="run",
                        target_system="jira",
                        target_type="workflow",
                        identifier="KAN-5",
                    )
                )

            self.assertTrue(result.success)
            generated_script = project_root / "tests" / "payments" / "payments.kan-5.test.js"
            self.assertTrue(generated_script.exists())
            generated_text = generated_script.read_text(encoding="utf-8")
            self.assertIn("http://127.0.0.1:3005", generated_text)
            self.assertIn("/api/payments/process", generated_text)
            self.assertIn("service: 'payments'", generated_text)
            self.assertIn("p(95)<800", generated_text)
            self.assertIn("rate<0.001000", generated_text)
            self.assertIn("Plan recovered deterministically from Jira text", result.document.content)
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)

    def test_jira_workflow_failed_checks_block_pass_decision(self) -> None:
        project_root = Path("tests") / ".tmp_jira_failed_checks"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            script_seed = project_root / "tests" / "payments" / "payments.test.js"
            script_seed.parent.mkdir(parents=True)
            script_seed.write_text("export default function () {}", encoding="utf-8")
            workspace = K6Workspace(str(project_root))
            ticket = SearchDocument(
                source_type="jira",
                title="KAN-5: Develop payment script",
                url="https://jira.local/browse/KAN-5",
                content=(
                    "Interface: POST http://localhost:3005/api/payments/process\n"
                    "Tag { service: 'payments' }\n"
                    "P95 < 800ms\n"
                    "error rate < 0.1%\n"
                ),
                metadata={"key": "KAN-5"},
            )
            jira_dependency = FakeJiraWorkflowDependency(ticket)
            responder = StubResponder()

            def staged_call_function(
                system_prompt: str,
                user_prompt: str,
                function_name: str,
                function_description: str,
                parameters: dict,
                temperature: float = 0.1,
            ) -> dict:
                responder.function_calls.append(
                    (system_prompt, user_prompt, function_name, function_description, parameters, temperature)
                )
                if function_name == "decide_ticket_workflow":
                    return {
                        "execution_mode": "plan_then_run",
                        "ordered_skills": ["performance-testing-strategy", "k6-best-practices"],
                        "rationale": ["Concrete payment endpoint and SLA are present in the ticket."],
                    }
                return {}

            responder.call_function = staged_call_function
            responder.complete = lambda *args, **kwargs: ""
            connector = JiraPerformanceWorkflowConnector(
                jira_connector=jira_dependency,  # type: ignore[arg-type]
                workspace=workspace,
                skill_catalog=ProjectSkillCatalog(),
                responder=responder,  # type: ignore[arg-type]
            )
            summary_dir = project_root / "results" / "2026-04-18_bot_payments"
            summary_dir.mkdir(parents=True)
            summary_path = summary_dir / "payments-summary.json"
            summary_path.write_text(
                """
                {
                  "metrics": {
                    "http_req_duration": { "p(95)": 3.8026, "avg": 2.4980 },
                    "checks": { "passes": 42, "fails": 42, "value": 0.5 },
                    "http_req_failed": { "passes": 42, "fails": 0, "value": 1 },
                    "http_reqs": { "count": 42 }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            run_result = MagicMock(
                exit_code=0,
                summary_path=summary_path,
                dashboard_path=summary_dir / "payments-dashboard.html",
                stdout="ok",
                stderr="",
                run_dir=summary_dir,
                script_path=project_root / "tests" / "payments" / "payments.kan-5.test.js",
            )
            with patch.object(workspace, "run_script", return_value=run_result):
                result = connector.execute(
                    ActionRequest(
                        operation="run",
                        target_system="jira",
                        target_type="workflow",
                        identifier="KAN-5",
                    )
                )

            self.assertFalse(result.success)
            self.assertIn("Checks pass rate: 0.5", result.document.content)
            self.assertIn("HTTP failure rate: 0", result.document.content)
            self.assertIn("Acceptance checks: pass rate = 0.5.", result.document.content)
            self.assertIn("Outcome: Performance SLOs passed, but the acceptance checks did not fully pass.", result.document.content)
            self.assertIn("Next decision: Keep the ticket open and triage the failing acceptance checks before release.", result.document.content)
            self.assertIn("Severity: Medium.", result.document.content)
            self.assertIn("Release risk: Moderate.", result.document.content)
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)

    def test_jira_workflow_selects_report_skill_when_ticket_requests_analysis(self) -> None:
        project_root = Path("tests") / ".tmp_jira_perf_workflow_analysis"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            script_seed = project_root / "tests" / "auth" / "auth.test.js"
            script_seed.parent.mkdir(parents=True)
            script_seed.write_text("export default function () {}", encoding="utf-8")
            workspace = K6Workspace(str(project_root))
            ticket = SearchDocument(
                source_type="jira",
                title="DEV-77: Auth load test with report",
                url="https://jira.local/browse/DEV-77",
                content=(
                    "Service: auth\n"
                    "Endpoint: POST /api/auth/login\n"
                    "SLA: p95 < 450ms\n"
                    "Error rate < 0.5%\n"
                    "VUs: 2\n"
                    "Duration: 30s\n"
                    "Please compare the result to the baseline and include an executive summary report.\n"
                ),
                metadata={"key": "DEV-77"},
            )
            jira_dependency = FakeJiraWorkflowDependency(ticket)
            responder = StubResponder()

            def staged_call_function(
                system_prompt: str,
                user_prompt: str,
                function_name: str,
                function_description: str,
                parameters: dict,
                temperature: float = 0.1,
            ) -> dict:
                responder.function_calls.append(
                    (system_prompt, user_prompt, function_name, function_description, parameters, temperature)
                )
                if function_name == "decide_ticket_workflow":
                    return {
                        "execution_mode": "plan_then_run",
                        "ordered_skills": [
                            "performance-testing-strategy",
                            "k6-best-practices",
                            "performance-report-analysis",
                        ],
                        "rationale": [
                            "The ticket needs planning.",
                            "It needs a runnable script.",
                            "It explicitly asks for baseline comparison and an executive report.",
                        ],
                    }
                if function_name == "extract_ticket_performance_plan":
                    return {
                        "service": "auth",
                        "endpoint_method": "POST",
                        "endpoint_path": "/api/auth/login",
                        "sla_p95_ms": 450,
                        "error_rate_percent": 0.5,
                        "vus": 2,
                        "duration": "30s",
                        "dataset": "users.json",
                        "test_type": "load",
                        "criteria": ["Validate 200 responses"],
                        "strategy_notes": ["Smoke before load."],
                    }
                return {}

            def staged_complete(system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
                responder.completions.append((system_prompt, user_prompt, temperature))
                if "Return only raw JavaScript" in system_prompt:
                    return """import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  thresholds: {
    'http_req_duration{service:auth}': ['p(95)<450'],
  },
};

export default function () {
  const res = http.post(`${__ENV.BASE_URL || 'http://127.0.0.1:3001'}/api/auth/login`, JSON.stringify({ username: 'u', password: 'p' }));
  check(res, { 'status 200': (r) => r.status === 200 });
  sleep(1);
}
"""
                return "## Skill-Driven Technical Analysis\n\n- Compared against the latest baseline.\n\n## Skill-Driven Business Analysis\n\n- Executive summary included."

            responder.call_function = staged_call_function
            responder.complete = staged_complete
            connector = JiraPerformanceWorkflowConnector(
                jira_connector=jira_dependency,  # type: ignore[arg-type]
                workspace=workspace,
                skill_catalog=ProjectSkillCatalog(),
                responder=responder,  # type: ignore[arg-type]
            )
            summary_dir = project_root / "results" / "2026-04-15_bot_auth"
            summary_dir.mkdir(parents=True)
            summary_path = summary_dir / "auth-summary.json"
            summary_path.write_text(
                """
                {
                  "metrics": {
                    "http_req_duration": { "avg": 120, "p(95)": 240 },
                    "checks": { "passes": 80, "fails": 0, "value": 1 },
                    "http_req_failed": { "rate": 0.001 },
                    "http_reqs": { "count": 80 }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            run_result = MagicMock(
                exit_code=0,
                summary_path=summary_path,
                dashboard_path=summary_dir / "auth-dashboard.html",
                stdout="ok",
                stderr="",
                run_dir=summary_dir,
                script_path=project_root / "tests" / "auth" / "auth.dev-77.test.js",
            )
            with patch.object(workspace, "run_script", return_value=run_result):
                result = connector.execute(
                    ActionRequest(
                        operation="run",
                        target_system="jira",
                        target_type="workflow",
                        identifier="DEV-77",
                    )
                )

            self.assertTrue(result.success)
            self.assertEqual(len(responder.function_calls), 2)
            self.assertEqual(len(responder.completions), 2)
            self.assertIn("docs/skills/performance-report-analysis", result.message)
            self.assertIn(
                "Playbooks: docs/skills/performance-testing-strategy, docs/skills/k6-best-practices, docs/skills/performance-report-analysis.",
                result.message,
            )
            self.assertIn("Performance report analysis skill used to produce the final report.", jira_dependency.comments[0][1])
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)

    def test_jira_report_calls_out_acceptance_gaps_and_weak_baseline(self) -> None:
        project_root = Path("tests") / ".tmp_jira_acceptance_gaps"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            script_seed = project_root / "tests" / "payments" / "payments.test.js"
            script_seed.parent.mkdir(parents=True)
            script_seed.write_text("export default function () {}", encoding="utf-8")
            workspace = K6Workspace(str(project_root))
            old_summary_dir = project_root / "results" / "2026-04-17_bot_payments"
            new_summary_dir = project_root / "results" / "2026-04-18_bot_payments"
            old_summary_dir.mkdir(parents=True)
            new_summary_dir.mkdir(parents=True)
            (old_summary_dir / "payments-summary.json").write_text(
                """
                {
                  "metrics": {
                    "http_req_duration": { "p(95)": 0, "avg": 0 },
                    "http_req_failed": { "passes": 41, "fails": 0, "value": 1 },
                    "http_reqs": { "count": 41 }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            ticket = SearchDocument(
                source_type="jira",
                title="KAN-5: Develop payment script",
                url="https://jira.local/browse/KAN-5",
                content=(
                    "Interface: POST http://localhost:3005/api/payments/process\n"
                    "Scenarios: approved / rejected\n"
                    "Tag { service: 'payments' }\n"
                    "Thresholds reference KAN-4: P95 < 800ms, error rate < 0.1%\n"
                    "Suggested split: 80% approved / 20% rejected\n"
                    "traceparent propagated - unified trace visible in Tempo\n"
                ),
                metadata={"key": "KAN-5"},
            )
            jira_dependency = FakeJiraWorkflowDependency(ticket)
            responder = StubResponder()

            def staged_call_function(
                system_prompt: str,
                user_prompt: str,
                function_name: str,
                function_description: str,
                parameters: dict,
                temperature: float = 0.1,
            ) -> dict:
                responder.function_calls.append(
                    (system_prompt, user_prompt, function_name, function_description, parameters, temperature)
                )
                if function_name == "decide_ticket_workflow":
                    return {
                        "execution_mode": "plan_then_run",
                        "ordered_skills": ["performance-testing-strategy", "k6-best-practices"],
                        "rationale": ["Concrete payment endpoint and SLA are present in the ticket."],
                    }
                return {}

            responder.call_function = staged_call_function
            responder.complete = lambda *args, **kwargs: ""
            connector = JiraPerformanceWorkflowConnector(
                jira_connector=jira_dependency,  # type: ignore[arg-type]
                workspace=workspace,
                skill_catalog=ProjectSkillCatalog(),
                responder=responder,  # type: ignore[arg-type]
            )
            summary_path = new_summary_dir / "payments-summary.json"
            summary_path.write_text(
                """
                {
                  "metrics": {
                    "http_req_duration": { "p(95)": 7.7912, "avg": 3.2641 },
                    "checks": { "passes": 41, "fails": 41, "value": 0.5 },
                    "http_req_failed": { "passes": 41, "fails": 0, "value": 1 },
                    "http_reqs": { "count": 41 }
                  },
                  "root_group": {
                    "name": "",
                    "groups": {
                      "KAN-5 payment group": {
                        "name": "KAN-5 payment group",
                        "checks": {
                          "status is expected": { "passes": 0, "fails": 41 },
                          "response time within hard ceiling": { "passes": 41, "fails": 0 }
                        }
                      }
                    }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            run_result = MagicMock(
                exit_code=0,
                summary_path=summary_path,
                dashboard_path=new_summary_dir / "payments-dashboard.html",
                stdout="ok",
                stderr="",
                run_dir=new_summary_dir,
                script_path=project_root / "tests" / "payments" / "payments.kan-5.test.js",
            )
            with patch.object(workspace, "run_script", return_value=run_result):
                result = connector.execute(
                    ActionRequest(
                        operation="run",
                        target_system="jira",
                        target_type="workflow",
                        identifier="KAN-5",
                    )
                )

            self.assertIn("The run does not prove the requested approved/rejected scenario split such as 80/20.", result.document.content)
            self.assertIn("The run does not include evidence that traceparent propagation and Tempo trace visibility were verified.", result.document.content)
            self.assertIn("The latest baseline file does not contain meaningful latency values, so the comparison is not decision-grade.", result.document.content)
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)

    def test_jira_comment_does_not_imply_ticket_can_close_when_checks_fail(self) -> None:
        project_root = Path("tests") / ".tmp_jira_comment_semantics"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            script_seed = project_root / "tests" / "payments" / "payments.test.js"
            script_seed.parent.mkdir(parents=True)
            script_seed.write_text("export default function () {}", encoding="utf-8")
            workspace = K6Workspace(str(project_root))
            ticket = SearchDocument(
                source_type="jira",
                title="KAN-5: Develop payment script",
                url="https://jira.local/browse/KAN-5",
                content=(
                    "Interface: POST http://localhost:3005/api/payments/process\n"
                    "Scenarios: approved / rejected\n"
                    "Tag { service: 'payments' }\n"
                    "Thresholds reference KAN-4: P95 < 800ms, error rate < 0.1%\n"
                    "Suggested split: 80% approved / 20% rejected\n"
                    "traceparent propagated - unified trace visible in Tempo\n"
                ),
                metadata={"key": "KAN-5"},
            )
            jira_dependency = FakeJiraWorkflowDependency(ticket)
            responder = StubResponder()

            def staged_call_function(
                system_prompt: str,
                user_prompt: str,
                function_name: str,
                function_description: str,
                parameters: dict,
                temperature: float = 0.1,
            ) -> dict:
                responder.function_calls.append(
                    (system_prompt, user_prompt, function_name, function_description, parameters, temperature)
                )
                if function_name == "decide_ticket_workflow":
                    return {
                        "execution_mode": "plan_then_run",
                        "ordered_skills": ["performance-testing-strategy", "k6-best-practices"],
                        "rationale": ["Concrete payment endpoint and SLA are present in the ticket."],
                    }
                return {}

            responder.call_function = staged_call_function
            responder.complete = lambda *args, **kwargs: ""
            connector = JiraPerformanceWorkflowConnector(
                jira_connector=jira_dependency,  # type: ignore[arg-type]
                workspace=workspace,
                skill_catalog=ProjectSkillCatalog(),
                responder=responder,  # type: ignore[arg-type]
            )
            summary_dir = project_root / "results" / "2026-04-18_bot_payments"
            summary_dir.mkdir(parents=True)
            summary_path = summary_dir / "payments-summary.json"
            summary_path.write_text(
                """
                {
                  "metrics": {
                    "http_req_duration": { "p(95)": 4.17896, "avg": 2.7712 },
                    "checks": { "passes": 38, "fails": 38, "value": 0.5 },
                    "http_req_failed": { "passes": 38, "fails": 0, "value": 1 },
                    "http_reqs": { "count": 38 }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            run_result = MagicMock(
                exit_code=0,
                summary_path=summary_path,
                dashboard_path=summary_dir / "payments-dashboard.html",
                stdout="ok",
                stderr="",
                run_dir=summary_dir,
                script_path=project_root / "tests" / "payments" / "payments.kan-5.test.js",
            )
            with patch.object(workspace, "run_script", return_value=run_result):
                connector.execute(
                    ActionRequest(
                        operation="run",
                        target_system="jira",
                        target_type="workflow",
                        identifier="KAN-5",
                    )
                )

            comment = jira_dependency.comments[0][1]
            self.assertIn("Performance workflow completed for KAN-5.", comment)
            self.assertIn("Latency SLO: passed", comment)
            self.assertIn("Acceptance checks: 50.0% pass", comment)
            self.assertIn("Outcome: Performance SLOs passed, but the acceptance checks did not fully pass.", comment)
            self.assertIn("Next decision: Keep the ticket open and triage the failing acceptance checks before release.", comment)
            self.assertNotIn("ready to sign off", comment.lower())
            self.assertNotIn("close ticket", comment.lower())
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)

    def test_jira_workflow_plan_only_skips_k6_execution(self) -> None:
        project_root = Path("tests") / ".tmp_jira_plan_only"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            workspace = K6Workspace(str(project_root))
            ticket = SearchDocument(
                source_type="jira",
                title="DEV-90: Estimate Black Friday auth workload",
                url="https://jira.local/browse/DEV-90",
                content=(
                    "Estimate expected Black Friday auth traffic.\n"
                    "Need hourly distribution, VUs, RPS, and recommended test phases.\n"
                    "This ticket is for planning and estimation only.\n"
                ),
                metadata={"key": "DEV-90"},
            )
            jira_dependency = FakeJiraWorkflowDependency(ticket)
            responder = StubResponder()

            def staged_call_function(
                system_prompt: str,
                user_prompt: str,
                function_name: str,
                function_description: str,
                parameters: dict,
                temperature: float = 0.1,
            ) -> dict:
                responder.function_calls.append(
                    (system_prompt, user_prompt, function_name, function_description, parameters, temperature)
                )
                if function_name == "decide_ticket_workflow":
                    return {
                        "execution_mode": "plan_only",
                        "ordered_skills": ["performance-testing-strategy"],
                        "rationale": [
                            "The ticket asks for estimation and planning rather than an executable performance run.",
                        ],
                    }
                if function_name == "extract_ticket_performance_plan":
                    return {
                        "service": "auth",
                        "endpoint_method": "POST",
                        "endpoint_path": "/api/auth/login",
                        "sla_p95_ms": 450,
                        "error_rate_percent": 0.5,
                        "vus": 250,
                        "duration": "30m",
                        "dataset": "users.json",
                        "test_type": "load",
                        "criteria": ["Estimate the Black Friday workload envelope"],
                        "strategy_notes": ["Model hourly traffic bands before any execution.", "Start with a smoke gate after planning sign-off."],
                    }
                return {}

            responder.call_function = staged_call_function
            connector = JiraPerformanceWorkflowConnector(
                jira_connector=jira_dependency,  # type: ignore[arg-type]
                workspace=workspace,
                skill_catalog=ProjectSkillCatalog(),
                responder=responder,  # type: ignore[arg-type]
            )

            with patch.object(workspace, "run_script") as run_script_mock:
                result = connector.execute(
                    ActionRequest(
                        operation="run",
                        target_system="jira",
                        target_type="workflow",
                        identifier="DEV-90",
                    )
                )

            self.assertTrue(result.success)
            run_script_mock.assert_not_called()
            self.assertEqual(len(responder.function_calls), 2)
            self.assertIn("Completed Jira planning workflow for DEV-90.", result.message)
            self.assertIn("Playbooks: docs/skills/performance-testing-strategy.", result.message)
            self.assertIn("Slack Plan Preview:", result.message)
            self.assertIn("Execution mode: `plan_only`", result.document.content)
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)

    def test_follow_up_close_it_uses_last_cited_ticket_from_memory(self) -> None:
        jira_doc = SearchDocument(
            source_type="jira",
            title="KAN-1: Invoice Data Fix",
            url="https://jira.local/browse/KAN-1",
            content="Invoice fix ticket.",
            metadata={"key": "KAN-1", "status": "To Do"},
        )
        responder = StubResponder()
        memory = RedisConversationMemory(
            redis_client=FakeRedis(),
            key_prefix="testbot",
            max_turns=3,
            ttl_seconds=120,
        )
        jira = StubConnector("jira", "ticket", documents=[jira_doc])
        agent = BuildAgents(
            connectors=[jira],
            responder=responder,
            memory=memory,
        )

        first_result = agent.answer("what ticket is the invoice fix?", conversation_id="conv-4")
        second_result = agent.answer("close it", conversation_id="conv-4")

        self.assertEqual(len(first_result.citations), 1)
        self.assertEqual(second_result.answer, "Updated jira ticket.")
        self.assertEqual(jira.executed_requests[-1].identifier, "KAN-1")
        self.assertEqual(jira.executed_requests[-1].fields["status"], "closed")
        self.assertIn(
            "Resolved follow-up action against the last referenced document in memory",
            second_result.reasoning_trace,
        )

    def test_follow_up_status_question_only_returns_relevant_ticket_citation(self) -> None:
        jira_doc_1 = SearchDocument(
            source_type="jira",
            title="KAN-1: Invoice Data Fix",
            url="https://jira.local/browse/KAN-1",
            content="Invoice fix ticket.",
            metadata={"key": "KAN-1", "status": "Done"},
        )
        jira_doc_2 = SearchDocument(
            source_type="jira",
            title="KAN-2: as400 fix",
            url="https://jira.local/browse/KAN-2",
            content="AS400 ticket.",
            metadata={"key": "KAN-2", "status": "To Do"},
        )
        jira_doc_3 = SearchDocument(
            source_type="jira",
            title="KAN-3: as400 fix",
            url="https://jira.local/browse/KAN-3",
            content="Another AS400 ticket.",
            metadata={"key": "KAN-3", "status": "In Progress"},
        )
        responder = StubResponder()
        memory = RedisConversationMemory(
            redis_client=FakeRedis(),
            key_prefix="testbot",
            max_turns=3,
            ttl_seconds=120,
        )
        jira = StubConnector("jira", "ticket", documents=[jira_doc_1, jira_doc_2, jira_doc_3])
        agent = BuildAgents(
            connectors=[jira],
            responder=responder,
            memory=memory,
        )

        first_result = agent.answer("what ticket is about delete inv", conversation_id="conv-5")
        second_result = agent.answer("what's the ticket status now", conversation_id="conv-5")

        self.assertEqual(len(first_result.citations), 3)
        self.assertEqual(len(second_result.citations), 1)
        self.assertEqual(second_result.citations[0].metadata["key"], "KAN-1")
        self.assertIn(
            "Filtered citations down to 1 documents relevant to the current context",
            second_result.reasoning_trace,
        )

    def test_follow_up_description_question_stays_on_remembered_jira_ticket(self) -> None:
        jira_doc = SearchDocument(
            source_type="jira",
            title="KAN-1: Invoice Data Fix",
            url="https://jira.local/browse/KAN-1",
            content="Delete the invoice ABCD.",
            metadata={"key": "KAN-1", "status": "Done"},
        )
        confluence_doc = SearchDocument(
            source_type="confluence",
            title="Learn how to use this space",
            url="https://conf.local/pages/1",
            content="Welcome to your teams new single source of truth.",
            metadata={"id": "1", "space_key": "SD"},
        )
        responder = StubResponder()
        memory = RedisConversationMemory(
            redis_client=FakeRedis(),
            key_prefix="testbot",
            max_turns=3,
            ttl_seconds=120,
        )
        agent = BuildAgents(
            connectors=[
                StubConnector("jira", "ticket", documents=[jira_doc]),
                StubConnector("confluence", "page", documents=[confluence_doc]),
            ],
            responder=responder,
            memory=memory,
        )

        first_result = agent.answer("what ticket is Done on jira", conversation_id="conv-6")
        second_result = agent.answer("whats the description of it", conversation_id="conv-6")

        self.assertEqual(len(first_result.citations), 1)
        self.assertEqual(len(second_result.citations), 1)
        self.assertEqual(second_result.citations[0].source_type, "jira")
        self.assertEqual(second_result.citations[0].metadata["key"], "KAN-1")
        self.assertIn(
            "Expanded the follow-up question using the last referenced document",
            second_result.reasoning_trace,
        )
        self.assertIn("Selected tools: jira", second_result.reasoning_trace)

    def test_follow_up_close_it_works_without_redis_connection(self) -> None:
        jira_doc = SearchDocument(
            source_type="jira",
            title="KAN-1: Invoice Data Fix",
            url="https://jira.local/browse/KAN-1",
            content="Invoice fix ticket.",
            metadata={"key": "KAN-1", "status": "To Do"},
        )
        responder = StubResponder()
        memory = RedisConversationMemory(
            redis_client=None,
            key_prefix="testbot",
            max_turns=3,
            ttl_seconds=120,
        )
        jira = StubConnector("jira", "ticket", documents=[jira_doc])
        agent = BuildAgents(
            connectors=[jira],
            responder=responder,
            memory=memory,
        )

        agent.answer("what ticket is about delete inv", conversation_id="conv-local-followup")
        second_result = agent.answer("close it", conversation_id="conv-local-followup")

        self.assertEqual(second_result.answer, "Updated jira ticket.")
        self.assertEqual(jira.executed_requests[-1].identifier, "KAN-1")
        self.assertEqual(jira.executed_requests[-1].fields["status"], "closed")

    def test_format_slack_response_includes_sources(self) -> None:
        result = AgentAnswer(
            answer="Short grounded answer",
            citations=[
                SearchDocument(
                    source_type="jira",
                    title="ABC-123",
                    url="https://jira.local/browse/ABC-123",
                    content="body",
                )
            ],
            reasoning_trace=[],
        )

        response = format_slack_response(result)
        self.assertIn("Short grounded answer", response)
        self.assertIn("[jira] ABC-123", response)

    def test_format_slack_response_hides_local_sources_outside_files_directory(self) -> None:
        result = AgentAnswer(
            answer="Ran k6 test for auth.",
            citations=[
                SearchDocument(
                    source_type="k6",
                    title="k6 run passed for auth",
                    url=r"C:\Program Files\code\Buildathon\performance\results\2026-04-14_20-55-31_bot_auth\auth-summary.json",
                    content="body",
                )
            ],
            reasoning_trace=[],
        )

        response = format_slack_response(result)
        self.assertIn("Ran k6 test for auth.", response)
        self.assertNotIn("Sources:", response)
        self.assertNotIn("performance\\results", response)

    def test_format_slack_response_keeps_local_sources_inside_files_directory(self) -> None:
        result = AgentAnswer(
            answer="Found a manual.",
            citations=[
                SearchDocument(
                    source_type="as400",
                    title="IBM i manual",
                    url=str((Path("files") / "IBM i Programming CL overview and concepts.pdf").resolve()),
                    content="body",
                )
            ],
            reasoning_trace=[],
        )

        response = format_slack_response(result)
        self.assertIn("Found a manual.", response)
        self.assertIn("[as400] IBM i manual", response)

    def test_jira_workflow_message_uses_relative_artifact_paths_and_dynamic_metrics(self) -> None:
        project_root = Path("tests") / ".tmp_jira_slack_message"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            script_seed = project_root / "tests" / "payments" / "payments.test.js"
            script_seed.parent.mkdir(parents=True)
            script_seed.write_text("export default function () {}", encoding="utf-8")
            workspace = K6Workspace(str(project_root))
            ticket = SearchDocument(
                source_type="jira",
                title="KAN-5: Develop payment script",
                url="https://jira.local/browse/KAN-5",
                content=(
                    "Interface: POST http://localhost:3005/api/payments/process\n"
                    "Tag { service: 'payments' }\n"
                    "P95 < 800ms\n"
                    "error rate < 0.1%\n"
                ),
                metadata={"key": "KAN-5"},
            )
            jira_dependency = FakeJiraWorkflowDependency(ticket)
            responder = StubResponder()

            def staged_call_function(
                system_prompt: str,
                user_prompt: str,
                function_name: str,
                function_description: str,
                parameters: dict,
                temperature: float = 0.1,
            ) -> dict:
                responder.function_calls.append(
                    (system_prompt, user_prompt, function_name, function_description, parameters, temperature)
                )
                if function_name == "decide_ticket_workflow":
                    return {
                        "execution_mode": "plan_then_run",
                        "ordered_skills": ["performance-testing-strategy", "k6-best-practices"],
                        "rationale": ["Concrete payment endpoint and SLA are present in the ticket."],
                    }
                return {}

            responder.call_function = staged_call_function
            responder.complete = lambda *args, **kwargs: ""
            connector = JiraPerformanceWorkflowConnector(
                jira_connector=jira_dependency,  # type: ignore[arg-type]
                workspace=workspace,
                skill_catalog=ProjectSkillCatalog(),
                responder=responder,  # type: ignore[arg-type]
            )
            summary_dir = project_root / "results" / "2026-04-18_bot_payments"
            summary_dir.mkdir(parents=True)
            summary_path = summary_dir / "payments-summary.json"
            summary_path.write_text(
                """
                {
                  "metrics": {
                    "http_req_duration": { "p(95)": 700, "avg": 500 },
                    "checks": { "passes": 42, "fails": 42, "value": 0.5 },
                    "http_req_failed": { "passes": 42, "fails": 0, "value": 1 },
                    "http_reqs": { "count": 42 }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            run_result = MagicMock(
                exit_code=0,
                summary_path=summary_path,
                dashboard_path=summary_dir / "payments-dashboard.html",
                stdout="ok",
                stderr="",
                run_dir=summary_dir,
                script_path=project_root / "tests" / "payments" / "payments.kan-5.test.js",
            )
            with patch.object(workspace, "run_script", return_value=run_result):
                result = connector.execute(
                    ActionRequest(
                        operation="run",
                        target_system="jira",
                        target_type="workflow",
                        identifier="KAN-5",
                    )
                )

            self.assertIn("Script: tests/payments/payments.kan-5.test.js.", result.message)
            self.assertIn("Report: results/2026-04-18_bot_payments/payments-report.md.", result.message)
            self.assertIn("HTML Report: results/2026-04-18_bot_payments/payments-report.html.", result.message)
            self.assertNotIn("C:\\Program Files\\code\\Buildathon", result.message)
            self.assertIn("Latency SLO: passed", result.message)
            self.assertIn("p95 700.000 ms vs target < 800 ms", result.message)
            self.assertIn("HTTP failures: 0.0% (target < 0.10%).", result.message)
            self.assertIn("Acceptance checks: 50.0% pass.", result.message)
            self.assertIn("Requests: 42.", result.message)
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)

    def test_jira_workflow_builds_plan_from_repo_docs_when_ticket_lacks_endpoint(self) -> None:
        project_root = Path("tests") / ".tmp_jira_repo_docs_fallback"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            performance_tests = project_root / "performance" / "tests" / "seed"
            performance_tests.mkdir(parents=True)
            (performance_tests / "seed.test.js").write_text("export default function () {}", encoding="utf-8")
            website_dir = project_root / "website"
            website_dir.mkdir(parents=True)
            (website_dir / "README.md").write_text(
                (
                    "# Demo\n\n"
                    "## Services and Ports\n\n"
                    "| Service | URL |\n"
                    "|---|---|\n"
                    "| users-api | http://localhost:3001 |\n"
                    "| payments-service | http://localhost:3005 |\n\n"
                    "## Purchase Flow\n\n"
                    "curl -X POST http://localhost:3005/api/payments/process\n\n"
                    "## SLOs\n\n"
                    "| Service | P95 Latency | Error Rate |\n"
                    "|---|---|---|\n"
                    "| payments-service | < 800ms | < 0.1% |\n"
                ),
                encoding="utf-8",
            )
            (website_dir / "docs").mkdir(parents=True)
            (website_dir / "docs" / "README.md").write_text("# Docs\n", encoding="utf-8")
            workspace = K6Workspace(str(project_root / "performance"))
            ticket = SearchDocument(
                source_type="jira",
                title="KAN-4: validate payments-service SLO",
                url="https://jira.local/browse/KAN-4",
                content="Please validate the payments-service SLOs from the project docs.",
                metadata={"key": "KAN-4"},
            )
            jira_dependency = FakeJiraWorkflowDependency(ticket)
            responder = StubResponder()
            connector = JiraPerformanceWorkflowConnector(
                jira_connector=jira_dependency,  # type: ignore[arg-type]
                workspace=workspace,
                skill_catalog=ProjectSkillCatalog(),
                responder=responder,  # type: ignore[arg-type]
            )

            plan = connector._build_plan(ticket, {}, ["performance-testing-strategy"])

            self.assertIsNotNone(plan)
            assert plan is not None
            self.assertEqual(plan.service, "payments")
            self.assertEqual(plan.endpoint_method, "POST")
            self.assertEqual(plan.endpoint_path, "/api/payments/process")
            self.assertEqual(plan.sla_p95_ms, 800)
            self.assertEqual(plan.error_rate_threshold, 0.001)
            self.assertIn("repository docs", " ".join(plan.strategy_notes).lower())
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)

    def test_jira_workflow_builds_plan_from_realistic_repo_docs_layout(self) -> None:
        project_root = Path("tests") / ".tmp_jira_repo_docs_realistic"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            performance_tests = project_root / "performance" / "tests" / "seed"
            performance_tests.mkdir(parents=True)
            (performance_tests / "seed.test.js").write_text("export default function () {}", encoding="utf-8")

            website_dir = project_root / "website"
            (website_dir / "docs" / "architecture").mkdir(parents=True)
            (website_dir / "docs" / "getting-started").mkdir(parents=True)
            (website_dir / "README.md").write_text(
                (
                    "# Demo\n\n"
                    "| Service | URL |\n"
                    "|---|---|\n"
                    "| users-api | http://localhost:3001 |\n"
                    "| payments-service | http://localhost:3005 |\n"
                ),
                encoding="utf-8",
            )
            (website_dir / "docs" / "README.md").write_text("# Docs\n", encoding="utf-8")
            (website_dir / "docs" / "getting-started" / "QUICK_START.md").write_text(
                (
                    "TOKEN=$(curl -s -X POST http://localhost:3001/api/auth/login ...)\n"
                    "ORDER=$(curl -s -X POST http://localhost:3004/api/orders ...)\n"
                    "curl -s -X POST http://localhost:3005/api/payments/process ...\n"
                ),
                encoding="utf-8",
            )
            (website_dir / "docs" / "architecture" / "ARCHITECTURE.md").write_text(
                (
                    "Service\n\n"
                    "P95 Latency\n\n"
                    "Error Rate\n\n"
                    "Availability\n\n"
                    "payments-service\n\n"
                    "< 800ms\n\n"
                    "< 0.1%\n\n"
                    "99.99%\n"
                ),
                encoding="utf-8",
            )

            workspace = K6Workspace(str(project_root / "performance"))
            ticket = SearchDocument(
                source_type="jira",
                title="KAN-4: validate payments-service SLO",
                url="https://jira.local/browse/KAN-4",
                content="Use the project documentation to create a runnable performance plan for payments-service.",
                metadata={"key": "KAN-4"},
            )
            jira_dependency = FakeJiraWorkflowDependency(ticket)
            responder = StubResponder()
            connector = JiraPerformanceWorkflowConnector(
                jira_connector=jira_dependency,  # type: ignore[arg-type]
                workspace=workspace,
                skill_catalog=ProjectSkillCatalog(),
                responder=responder,  # type: ignore[arg-type]
            )

            plan = connector._build_plan(ticket, {}, ["performance-testing-strategy"])

            self.assertIsNotNone(plan)
            assert plan is not None
            self.assertEqual(plan.service, "payments")
            self.assertEqual(plan.endpoint_method, "POST")
            self.assertEqual(plan.endpoint_path, "/api/payments/process")
            self.assertEqual(plan.sla_p95_ms, 800)
            self.assertEqual(plan.error_rate_threshold, 0.001)
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)

    def test_jira_workflow_builds_plan_from_ticket_service_matrix_and_repo_endpoint(self) -> None:
        project_root = Path("tests") / ".tmp_jira_ticket_matrix"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            performance_tests = project_root / "performance" / "tests" / "seed"
            performance_tests.mkdir(parents=True)
            (performance_tests / "seed.test.js").write_text("export default function () {}", encoding="utf-8")

            website_dir = project_root / "website"
            website_dir.mkdir(parents=True)
            (website_dir / "README.md").write_text(
                (
                    "# Demo\n\n"
                    "curl -X POST http://localhost:3005/api/payments/process\n"
                ),
                encoding="utf-8",
            )
            (website_dir / "docs").mkdir(parents=True)
            (website_dir / "docs" / "README.md").write_text("# Docs\n", encoding="utf-8")

            workspace = K6Workspace(str(project_root / "performance"))
            ticket = SearchDocument(
                source_type="jira",
                title="KAN-4: Service SLO matrix",
                url="https://jira.local/browse/KAN-4",
                content=(
                    "Service\n\n"
                    "P95 Latency\n\n"
                    "Error Rate\n\n"
                    "Availability\n\n"
                    "users-api\n\n"
                    "< 450ms\n\n"
                    "< 0.5%\n\n"
                    "99.9%\n\n"
                    "payments-service\n\n"
                    "< 800ms\n\n"
                    "< 0.1%\n\n"
                    "99.99%\n"
                ),
                metadata={"key": "KAN-4"},
            )
            jira_dependency = FakeJiraWorkflowDependency(ticket)
            responder = StubResponder()
            connector = JiraPerformanceWorkflowConnector(
                jira_connector=jira_dependency,  # type: ignore[arg-type]
                workspace=workspace,
                skill_catalog=ProjectSkillCatalog(),
                responder=responder,  # type: ignore[arg-type]
            )

            plan = connector._build_plan(ticket, {"service": "payments"}, ["performance-testing-strategy"])

            self.assertIsNotNone(plan)
            assert plan is not None
            self.assertEqual(plan.service, "payments")
            self.assertEqual(plan.endpoint_method, "POST")
            self.assertEqual(plan.endpoint_path, "/api/payments/process")
            self.assertEqual(plan.sla_p95_ms, 800)
            self.assertEqual(plan.error_rate_threshold, 0.001)
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)

    def test_jira_workflow_plan_only_comment_body_accepts_missing_metrics(self) -> None:
        project_root = Path("tests") / ".tmp_jira_plan_only_comment"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            performance_tests = project_root / "performance" / "tests" / "seed"
            performance_tests.mkdir(parents=True)
            (performance_tests / "seed.test.js").write_text("export default function () {}", encoding="utf-8")
            workspace = K6Workspace(str(project_root / "performance"))
            ticket = SearchDocument(
                source_type="jira",
                title="KAN-4: Service SLO matrix",
                url="https://jira.local/browse/KAN-4",
                content="payments-service\n< 800ms\n< 0.1%",
                metadata={"key": "KAN-4"},
            )
            jira_dependency = FakeJiraWorkflowDependency(ticket)
            responder = StubResponder()
            connector = JiraPerformanceWorkflowConnector(
                jira_connector=jira_dependency,  # type: ignore[arg-type]
                workspace=workspace,
                skill_catalog=ProjectSkillCatalog(),
                responder=responder,  # type: ignore[arg-type]
            )
            plan = TicketPerformancePlan(
                issue_key="KAN-4",
                summary="Service SLO matrix",
                description=ticket.content,
                service="payments",
                endpoint_method="POST",
                endpoint_path="/api/payments/process",
                sla_p95_ms=800,
                error_rate_threshold=0.001,
                vus=2,
                duration="30s",
                dataset="users.json",
                test_type="load",
                criteria=[],
                strategy_notes=[],
            )
            decision = WorkflowDecision(
                ordered_skills=["performance-testing-strategy"],
                execution_mode="plan_only",
                rationale=["Planning only."],
            )
            plan_document = SearchDocument(
                source_type="k6",
                title="performance plan for KAN-4",
                url=str(project_root / "performance" / "results" / "kan-4-payments-plan.md"),
                content="# plan",
                metadata={},
            )

            comment = connector._jira_comment_body(
                plan,
                plan_document,
                None,
                [],
                decision,
            )

            self.assertIn("Performance workflow completed for KAN-4.", comment)
            self.assertIn("Workflow mode: plan_only", comment)
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)

    def test_jira_workflow_decision_fallback_runs_when_repo_docs_recover_endpoint(self) -> None:
        project_root = Path("tests") / ".tmp_jira_decision_repo_endpoint"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            performance_tests = project_root / "performance" / "tests" / "seed"
            performance_tests.mkdir(parents=True)
            (performance_tests / "seed.test.js").write_text("export default function () {}", encoding="utf-8")

            website_dir = project_root / "website"
            website_dir.mkdir(parents=True)
            (website_dir / "README.md").write_text(
                "# Demo\n\ncurl -X POST http://localhost:3005/api/payments/process\n",
                encoding="utf-8",
            )
            (website_dir / "docs").mkdir(parents=True)
            (website_dir / "docs" / "README.md").write_text("# Docs\n", encoding="utf-8")

            workspace = K6Workspace(str(project_root / "performance"))
            ticket = SearchDocument(
                source_type="jira",
                title="KAN-4: Service SLO matrix",
                url="https://jira.local/browse/KAN-4",
                content=(
                    "Generate test plan and k6 script.\n"
                    "payments-service\n"
                    "< 800ms\n"
                    "< 0.1%\n"
                ),
                metadata={"key": "KAN-4"},
            )
            jira_dependency = FakeJiraWorkflowDependency(ticket)
            responder = StubResponder()
            responder.call_function = lambda *args, **kwargs: {}
            connector = JiraPerformanceWorkflowConnector(
                jira_connector=jira_dependency,  # type: ignore[arg-type]
                workspace=workspace,
                skill_catalog=ProjectSkillCatalog(),
                responder=responder,  # type: ignore[arg-type]
            )

            decision = connector._decide_ticket_workflow(ticket, {"service": "payments"})

            self.assertIsNotNone(decision)
            assert decision is not None
            self.assertEqual(decision.execution_mode, "plan_then_run")
            self.assertIn("k6-best-practices", decision.ordered_skills)
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)

    def test_jira_workflow_kan4_end_to_end_runs_after_repo_endpoint_recovery(self) -> None:
        project_root = Path("tests") / ".tmp_jira_kan4_e2e"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            performance_root = project_root / "performance"
            script_seed = performance_root / "tests" / "payments" / "payments.test.js"
            script_seed.parent.mkdir(parents=True)
            script_seed.write_text("export default function () {}", encoding="utf-8")

            website_dir = project_root / "website"
            website_dir.mkdir(parents=True)
            (website_dir / "README.md").write_text(
                (
                    "# Demo\n\n"
                    "curl -X POST http://localhost:3005/api/payments/process\n"
                ),
                encoding="utf-8",
            )
            (website_dir / "docs").mkdir(parents=True)
            (website_dir / "docs" / "README.md").write_text("# Docs\n", encoding="utf-8")

            workspace = K6Workspace(str(performance_root))
            ticket = SearchDocument(
                source_type="jira",
                title="KAN-4: Service SLO matrix",
                url="https://jira.local/browse/KAN-4",
                content=(
                    "Generate test plan and k6 script, and get the performance result.\n"
                    "Service\n"
                    "P95 Latency\n"
                    "Error Rate\n"
                    "Availability\n"
                    "payments-service\n"
                    "< 800ms\n"
                    "< 0.1%\n"
                    "99.99%\n"
                ),
                metadata={"key": "KAN-4"},
            )
            jira_dependency = FakeJiraWorkflowDependency(ticket)
            responder = StubResponder()
            responder.call_function = lambda *args, **kwargs: {}
            responder.complete = lambda *args, **kwargs: ""
            connector = JiraPerformanceWorkflowConnector(
                jira_connector=jira_dependency,  # type: ignore[arg-type]
                workspace=workspace,
                skill_catalog=ProjectSkillCatalog(),
                responder=responder,  # type: ignore[arg-type]
            )

            summary_dir = performance_root / "results" / "2026-04-18_bot_payments"
            summary_dir.mkdir(parents=True)
            summary_path = summary_dir / "payments-summary.json"
            summary_path.write_text(
                """
                {
                  "metrics": {
                    "http_req_duration": { "p(95)": 700, "avg": 500 },
                    "checks": { "passes": 42, "fails": 0, "value": 1 },
                    "http_req_failed": { "passes": 42, "fails": 0, "value": 1 },
                    "http_reqs": { "count": 42 }
                  }
                }
                """.strip(),
                encoding="utf-8",
            )
            run_result = MagicMock(
                exit_code=0,
                summary_path=summary_path,
                dashboard_path=summary_dir / "payments-dashboard.html",
                stdout="ok",
                stderr="",
                run_dir=summary_dir,
                script_path=performance_root / "tests" / "payments" / "payments.kan-4.test.js",
            )

            with patch.object(workspace, "run_script", return_value=run_result):
                result = connector.execute(
                    ActionRequest(
                        operation="run",
                        target_system="jira",
                        target_type="workflow",
                        identifier="KAN-4",
                        fields={"service": "payments"},
                    )
                )

            self.assertTrue(result.success)
            self.assertIn("Completed Jira performance workflow for KAN-4.", result.message)
            self.assertIn("Script: tests/payments/payments.kan-4.test.js.", result.message)
            self.assertIn("Report: results/2026-04-18_bot_payments/payments-report.md.", result.message)
            self.assertNotIn("Completed Jira planning workflow", result.message)
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)


class SlackSocketModeTests(unittest.TestCase):
    def test_normalize_question_removes_mentions(self) -> None:
        self.assertEqual(_normalize_question("<@U123> hello"), "hello")

    def test_supported_event_rules(self) -> None:
        self.assertTrue(_is_supported_event({"type": "message"}))
        self.assertFalse(_is_supported_event({"type": "reaction_added"}))
        self.assertFalse(_is_supported_event({"type": "message", "bot_id": "B123"}))

    def test_conversation_id_prefers_thread_then_channel(self) -> None:
        self.assertEqual(
            _conversation_id_for_event({"channel": "C123", "thread_ts": "171234.567"}),
            "C123:thread:171234.567",
        )
        self.assertEqual(
            _conversation_id_for_event({"channel": "D123"}),
            "D123:channel",
        )

    @patch("src.slack_app._process_event_async")
    @patch("src.slack_app._post_placeholder_message", return_value="123.456")
    def test_handle_slack_event_starts_background_work(
        self,
        _placeholder_mock: MagicMock,
        process_mock: MagicMock,
    ) -> None:
        client = MagicMock()
        handle_slack_event(
            {
                "type": "message",
                "channel": "D123",
                "channel_type": "im",
                "user": "U123",
                "text": "hello",
            },
            client,
        )
        process_mock.assert_called_once_with(
            {
                "type": "message",
                "channel": "D123",
                "channel_type": "im",
                "user": "U123",
                "text": "hello",
            },
            "hello",
            client,
            "123.456",
        )

    def test_allowed_channel_with_empty_setting(self) -> None:
        self.assertTrue(_is_allowed_channel({"channel": "C123"}))

    def test_process_socket_mode_request_acknowledges_envelope(self) -> None:
        socket_client = MagicMock()
        socket_client.web_client = MagicMock()
        request = MagicMock()
        request.type = "events_api"
        request.envelope_id = "env-1"
        request.payload = {
            "event": {
                "type": "message",
                "channel": "D123",
                "text": "hello",
            }
        }

        with patch("src.slack_app.handle_slack_event") as handle_mock:
            process_socket_mode_request(socket_client, request)

        socket_client.send_socket_mode_response.assert_called_once()
        handle_mock.assert_called_once()

    def test_upload_html_report_if_available_uploads_matching_html_file(self) -> None:
        project_root = Path("tests") / ".tmp_slack_html_upload"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            run_dir = project_root / "results" / "2026-04-18_bot_payments"
            run_dir.mkdir(parents=True)
            report_path = run_dir / "payments-report.md"
            report_path.write_text("# report", encoding="utf-8")
            html_path = run_dir / "payments-report.html"
            html_path.write_text("<html></html>", encoding="utf-8")
            result = AgentAnswer(
                answer="done",
                citations=[
                    SearchDocument(
                        source_type="k6",
                        title="report",
                        url=str(report_path),
                        content="# report",
                        metadata={"report_path": str(report_path)},
                    )
                ],
                reasoning_trace=[],
            )
            client = MagicMock()

            _upload_html_report_if_available(
                {"channel": "C123"},
                client,
                "171234.567",
                result,
            )

            client.files_upload_v2.assert_called_once()
            kwargs = client.files_upload_v2.call_args.kwargs
            self.assertEqual(kwargs["channel"], "C123")
            self.assertEqual(kwargs["thread_ts"], "171234.567")
            self.assertEqual(Path(kwargs["file"]).resolve(), html_path.resolve())
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)

    def test_upload_html_report_if_available_skips_when_report_path_missing(self) -> None:
        result = AgentAnswer(
            answer="done",
            citations=[
                SearchDocument(
                    source_type="k6",
                    title="report",
                    url="",
                    content="# report",
                    metadata={},
                )
            ],
            reasoning_trace=[],
        )
        client = MagicMock()

        _upload_html_report_if_available(
            {"channel": "C123"},
            client,
            "171234.567",
            result,
        )

        client.files_upload_v2.assert_not_called()


class MainCliTests(unittest.TestCase):
    @patch("src.main.format_slack_response", return_value="formatted")
    @patch("src.main.BuildAgents")
    @patch("builtins.print")
    def test_main_runs_one_shot_question_with_conversation_id(
        self,
        print_mock: MagicMock,
        agent_cls_mock: MagicMock,
        _format_mock: MagicMock,
    ) -> None:
        agent = agent_cls_mock.return_value
        agent.answer.return_value = AgentAnswer(
            answer="ok",
            citations=[],
            reasoning_trace=[],
        )

        exit_code = main(["--conversation-id", "local-test", "hello", "world"])

        self.assertEqual(exit_code, 0)
        agent.answer.assert_called_once_with("hello world", conversation_id="local-test")
        print_mock.assert_called_with("formatted")

    @patch("src.main.format_slack_response", return_value="formatted")
    @patch("src.main.BuildAgents")
    @patch("builtins.input", side_effect=["hello", "quit"])
    @patch("builtins.print")
    def test_run_repl_reuses_same_conversation_id(
        self,
        print_mock: MagicMock,
        _input_mock: MagicMock,
        agent_cls_mock: MagicMock,
        _format_mock: MagicMock,
    ) -> None:
        agent = agent_cls_mock.return_value
        agent.memory.backend_label = "local-only"
        agent.answer.return_value = AgentAnswer(
            answer="ok",
            citations=[],
            reasoning_trace=[],
        )

        exit_code = _run_repl(agent, "session-1")

        self.assertEqual(exit_code, 0)
        agent.answer.assert_called_once_with("hello", conversation_id="session-1")
        self.assertTrue(print_mock.call_args_list[0].args[0].startswith("Starting local chat."))
        self.assertEqual(print_mock.call_args_list[1].args[0], "Memory backend: local-only")


if __name__ == "__main__":
    unittest.main()


