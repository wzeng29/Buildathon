from __future__ import annotations

import csv
import html
import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin

import requests

from config import _is_real_value, settings
from src.llm import OpenAIResponder
from src.mcp_adapter import MCPAdapter, build_mcp_adapter
from src.project_skills import ProjectSkill, ProjectSkillCatalog
from src.models import ActionRequest, ActionResult, SearchDocument
from src.perf_tools import K6Workspace
from src.semantic_retrieval import SemanticDocumentIndex, TextEmbedder

try:  # pragma: no cover - optional dependency in runtime
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional dependency in runtime
    PdfReader = None  # type: ignore[assignment]

REQUEST_TIMEOUT_SECONDS = 30
CONFLUENCE_EXPAND_FIELDS = "body.storage,version,space"
JIRA_FIELDS = "summary,description,status,issuetype,assignee,project"
CONFLUENCE_QUERY_FALLBACK_LIMIT = 3
AS400_COMMAND_PATTERN = re.compile(r"\b[A-Z]{3,10}[A-Z0-9]{0,2}\b")
LOGGER = logging.getLogger(__name__)


def _tokenize(text: str) -> set[str]:
    """Tokenize text for lightweight matching and ranking."""
    return set(re.findall(r"[a-zA-Z0-9_]+", text.lower()))


def _score(query: str, *parts: str) -> float:
    """Calculate a simple overlap score between a query and a candidate document."""
    query_terms = _tokenize(query)
    haystack_terms = _tokenize(" ".join(parts))
    if not query_terms or not haystack_terms:
        return 0.0

    overlap = len(query_terms & haystack_terms)
    return overlap / len(query_terms)


def _fallback_terms(text: str, limit: int = CONFLUENCE_QUERY_FALLBACK_LIMIT) -> list[str]:
    """Extract a few useful keywords when a full question is too broad for search."""
    stopwords = {
        "the",
        "and",
        "for",
        "with",
        "about",
        "what",
        "when",
        "where",
        "which",
        "that",
        "this",
        "from",
        "into",
        "your",
        "have",
        "there",
        "exists",
    }
    terms = [term for term in _tokenize(text) if len(term) > 2 and term not in stopwords]
    ranked = sorted(dict.fromkeys(terms), key=lambda term: (-len(term), term))
    return ranked[:limit]


def _strip_html(value: str) -> str:
    """Convert simple Confluence storage HTML into plain text for summaries."""
    without_tags = re.sub(r"<[^>]+>", " ", value or "")
    return html.unescape(re.sub(r"\s+", " ", without_tags)).strip()


def _normalize_whitespace(value: str) -> str:
    """Collapse PDF-extracted text into a cleaner searchable form."""
    return re.sub(r"\s+", " ", (value or "").replace("\x00", " ")).strip()


def _chunk_text(text: str, chunk_size: int) -> list[str]:
    """Split long text into bounded overlapping chunks."""
    normalized = _normalize_whitespace(text)
    if not normalized:
        return []

    chunks: list[str] = []
    start = 0
    overlap = max(chunk_size // 5, 120)
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _extract_command_candidates(text: str) -> list[str]:
    """Extract plausible IBM i CL command names from a text chunk."""
    command_prefixes = (
        "WRK",
        "DSP",
        "CHG",
        "CRT",
        "DLT",
        "SAV",
        "RST",
        "RTV",
        "STR",
        "END",
        "CPY",
        "SBM",
        "OVR",
        "GRT",
        "RVK",
        "CHK",
        "RNM",
        "MOV",
        "EDT",
        "DMP",
        "PRT",
        "ALC",
        "DLC",
        "MON",
        "SND",
        "RCV",
        "ADD",
        "RMV",
    )
    stopwords = {
        "ADDITION",
        "COMMAND",
        "COMMANDS",
        "CONTROL",
        "LANGUAGE",
        "OBJECT",
        "OBJECTS",
        "PROGRAM",
        "PROGRAMS",
        "MESSAGE",
        "MESSAGES",
        "DISPLAY",
        "DISPLAYING",
        "WORK",
        "SYSTEM",
        "SYSTEMS",
        "INFORMATION",
        "DESCRIPTION",
        "DESCRIPTIONS",
        "PF",
        "LF",
        "PRTF",
        "FILE",
        "FILES",
    }
    seen: set[str] = set()
    commands: list[str] = []
    for match in AS400_COMMAND_PATTERN.findall(text.upper()):
        if not match.startswith(command_prefixes):
            continue
        if match in stopwords:
            continue
        if match in seen:
            continue
        seen.add(match)
        commands.append(match)
    return commands[:12]


def _build_confluence_url(base_url: str, links: dict[str, Any]) -> str:
    """Build a stable browser URL from Confluence response metadata."""
    base = links.get("base") or base_url.rstrip("/")
    webui = links.get("webui") or ""
    if not webui:
        return base_url.rstrip("/")
    if webui.startswith("/wiki/"):
        return urljoin(base.rstrip("/") + "/", webui.lstrip("/"))
    if webui.startswith("/"):
        base_root = base.rstrip("/")
        if base_root.endswith("/wiki"):
            return urljoin(base_root + "/", webui.lstrip("/"))
        return urljoin(base_root + "/", f"wiki{webui}".lstrip("/"))
    return urljoin(base.rstrip("/") + "/", webui)


def _wrap_storage_body(body: str) -> str:
    """Wrap plain text in simple storage markup while preserving HTML bodies."""
    text = (body or "").strip()
    if not text:
        return "<p></p>"
    if text.startswith("<") and text.endswith(">"):
        return text
    escaped = html.escape(text).replace("\n", "<br/>")
    return f"<p>{escaped}</p>"


def _jira_description_to_adf(text: str) -> dict[str, Any]:
    """Convert a plain-text description into the Atlassian document format."""
    lines = [line.strip() for line in (text or "").splitlines()]
    paragraphs = [line for line in lines if line]
    if not paragraphs:
        paragraphs = [""]

    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": paragraph}],
            }
            for paragraph in paragraphs
        ],
    }


def _jira_description_to_text(description: Any) -> str:
    """Extract plain text from Jira's Atlassian document format."""
    if isinstance(description, str):
        return description
    if not isinstance(description, dict):
        return ""

    fragments: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "text" and node.get("text"):
                fragments.append(node["text"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(description)
    return " ".join(fragment for fragment in fragments if fragment).strip()


def _safe_grafana_lookup(
    grafana_connector: "GrafanaConnector | None",
    service: str,
) -> SearchDocument | None:
    """Best-effort Grafana lookup used by k6 flows for non-blocking enrichment."""
    if grafana_connector is None or not grafana_connector.configured:
        return None
    dashboard, _ = grafana_connector.lookup_dashboard(service)
    return dashboard


def _k6_metric_summary(run_result: "K6RunResult") -> dict[str, str]:
    payload: dict[str, str] = {
        "exit_code": str(run_result.exit_code),
    }
    try:
        metrics = json.loads(run_result.summary_path.read_text(encoding="utf-8")).get("metrics", {})
    except Exception:
        return payload

    http_duration = _metric_entry(metrics, "http_req_duration")
    failures = _metric_entry(metrics, "http_req_failed")
    requests = _metric_entry(metrics, "http_reqs")
    payload.update(
        {
            "p95": str(http_duration.get("p(95)", "n/a")),
            "avg": str(http_duration.get("avg", "n/a")),
            "failure_rate": str(failures.get("rate", "n/a")),
            "check_rate": str(_metric_entry(metrics, "checks").get("rate", "n/a")),
            "request_count": str(requests.get("count", "n/a")),
        }
    )
    return payload


def _metric_entry(metrics: dict[str, Any], metric_name: str) -> dict[str, Any]:
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
        normalized = dict(metric)
        if total:
            normalized["rate"] = (fails / total) if metric_name == "http_req_failed" else (passes / total)
        return normalized
    return metric


def _report_preview(content: str, max_lines: int = 8) -> str:
    lines = [line.strip() for line in (content or "").splitlines()]
    selected: list[str] = []
    capture = False
    allowed_headers = {
        "## Executive Summary",
        "## Technical Report",
        "## Business Report",
        "## Skill-Driven Technical Analysis",
        "## Skill-Driven Business Analysis",
    }
    for line in lines:
        if line in allowed_headers:
            capture = True
            if line not in selected:
                selected.append(line)
            continue
        if capture and line.startswith("## "):
            if len(selected) >= max_lines:
                break
            capture = False
        if not capture:
            continue
        if not line:
            continue
        selected.append(line)
        if len(selected) >= max_lines:
            break
    return "\n".join(selected)


@dataclass(frozen=True)
class TicketPerformancePlan:
    issue_key: str
    summary: str
    description: str
    service: str
    endpoint_method: str
    endpoint_path: str
    sla_p95_ms: int
    error_rate_threshold: float
    vus: int
    duration: str
    dataset: str
    test_type: str
    criteria: list[str]
    strategy_notes: list[str]


@dataclass(frozen=True)
class SkillBundle:
    name: str
    skill_text: str
    reference_texts: dict[str, str]
    evals_payload: dict[str, Any]


@dataclass(frozen=True)
class WorkflowDecision:
    ordered_skills: list[str]
    execution_mode: str
    rationale: list[str]


class BaseConnector(ABC):
    """Base class for systems that can search and mutate enterprise records."""

    source_type: str
    target_type: str

    def __init__(self, mcp_adapter: MCPAdapter | None = None) -> None:
        self.session = requests.Session()
        self.session.verify = settings.verify_ssl
        self.mcp_adapter = mcp_adapter

    @property
    @abstractmethod
    def configured(self) -> bool:
        raise NotImplementedError

    @property
    def configuration_message(self) -> str:
        return f"{self.source_type.title()} is not configured."

    @abstractmethod
    def search(self, query: str, limit: int) -> list[SearchDocument]:
        raise NotImplementedError

    @abstractmethod
    def create(self, request: ActionRequest) -> ActionResult:
        raise NotImplementedError

    @abstractmethod
    def read(self, request: ActionRequest) -> ActionResult:
        raise NotImplementedError

    @abstractmethod
    def update(self, request: ActionRequest) -> ActionResult:
        raise NotImplementedError

    @abstractmethod
    def delete(self, request: ActionRequest) -> ActionResult:
        raise NotImplementedError

    def execute(self, request: ActionRequest) -> ActionResult:
        """Dispatch a normalized action request to the concrete CRUD method."""
        handlers = {
            "create": self.create,
            "read": self.read,
            "update": self.update,
            "delete": self.delete,
        }
        handler = handlers.get(request.operation)
        if handler is None:
            return ActionResult(
                success=False,
                message=f"Unsupported operation '{request.operation}' for {self.source_type}.",
            )
        return handler(request)

    def _rank(self, query: str, documents: Iterable[SearchDocument]) -> list[SearchDocument]:
        """Apply the same relevance sort across all connectors."""
        return sorted(
            documents,
            key=lambda doc: _score(query, doc.title, doc.content, str(doc.metadata)),
            reverse=True,
        )


class AS400ManualConnector(BaseConnector):
    """Search local IBM i / AS400 and Synon 2E manuals as one source."""

    source_type = "as400"
    target_type = "manual"

    def __init__(
        self,
        manual_path: str | None = None,
        embedder: TextEmbedder | None = None,
        index_path: str | None = None,
    ) -> None:
        super().__init__()
        configured_path = manual_path or settings.as400_manual_path
        self.manual_spec = configured_path
        self.manual_paths = self._resolve_manual_paths(configured_path)
        self._documents_cache: list[SearchDocument] | None = None
        self.semantic_index = SemanticDocumentIndex(
            index_path=index_path or settings.as400_index_path,
            embedder=embedder,
        )

    @property
    def configured(self) -> bool:
        return bool(self.manual_paths)

    def search(self, query: str, limit: int) -> list[SearchDocument]:
        """Search the uploaded IBM i and Synon manuals as one shared source."""
        if not self.configured:
            return []

        documents = self._load_documents()
        if not documents:
            return []

        expanded_query = self._expand_query(query)
        command_query = self._is_command_query(query)
        explicit_commands = _extract_command_candidates(query)
        explicit_tables = self._extract_table_candidates(query, documents)
        table_catalog_query = self._is_table_catalog_query(query)
        similar_table_query = self._is_similar_table_query(query)
        if explicit_tables and similar_table_query:
            related_documents = self._related_table_documents(documents, explicit_tables, limit)
            if related_documents:
                return related_documents
        if table_catalog_query and not explicit_tables and not command_query:
            keyword_documents = self._keyword_table_documents(query, documents, limit)
            if keyword_documents:
                return keyword_documents
        candidate_documents = documents
        manual_documents = [
            document
            for document in documents
            if document.metadata.get("source_kind") == "manual_page"
        ]
        if command_query and manual_documents:
            candidate_documents = manual_documents
        elif command_query and table_catalog_query:
            if explicit_tables:
                explicit_table_documents = [
                    document
                    for document in documents
                    if str(document.metadata.get("table_name", "")).upper() in explicit_tables
                ]
                if explicit_table_documents:
                    candidate_documents = explicit_table_documents
                else:
                    return []
            else:
                keyword_documents = self._keyword_table_documents(query, documents, max(limit * 3, 6))
                if keyword_documents:
                    candidate_documents = keyword_documents
                else:
                    return []
        elif explicit_tables and similar_table_query:
            anchor_documents = [
                document
                for document in documents
                if str(document.metadata.get("table_name", "")).upper() in explicit_tables
            ]
            if anchor_documents:
                anchor_descriptions = " ".join(
                    str(document.metadata.get("table_text", ""))
                    for document in anchor_documents
                )
                expanded_query = f"{expanded_query} related similar {anchor_descriptions}".strip()
                candidate_documents = [
                    document
                    for document in documents
                    if document.metadata.get("source_kind") == "table_catalog"
                ]
        elif explicit_tables:
            explicit_table_documents = [
                document
                for document in documents
                if str(document.metadata.get("table_name", "")).upper() in explicit_tables
            ]
            if explicit_table_documents:
                candidate_documents = explicit_table_documents
        elif table_catalog_query:
            table_documents = [
                document
                for document in documents
                if document.metadata.get("source_kind") == "table_catalog"
            ]
            if table_documents:
                candidate_documents = table_documents
        if explicit_commands:
            explicit_documents = [
                document
                for document in candidate_documents
                if self._contains_explicit_command(document, explicit_commands)
            ]
            if explicit_documents:
                candidate_documents = explicit_documents
        phrase_documents = self._phrase_matched_documents(query, candidate_documents)
        if phrase_documents:
            candidate_documents = phrase_documents

        semantic_hits = self.semantic_index.search(
            expanded_query,
            candidate_documents,
            max(limit * 4, 8),
        )
        if not semantic_hits:
            return []

        scored = [
            (
                self._combined_search_score(
                    expanded_query,
                    semantic_score,
                    document,
                    explicit_commands,
                ),
                document,
            )
            for document, semantic_score in semantic_hits
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        best_score = scored[0][0] if scored else 0.0
        minimum_score = max(best_score * 0.82, 0.32)
        if similar_table_query:
            minimum_score = max(best_score * 0.45, 0.08)
        elif command_query and candidate_documents and all(
            document.metadata.get("source_kind") == "manual_page" for document in candidate_documents
        ):
            minimum_score = max(best_score * 0.78, 0.38)
        filtered = [document for score, document in scored if score >= minimum_score]
        selected = filtered[:limit]
        if not selected:
            return []
        if "command" in query.lower():
            return selected[: min(limit, 2)]
        return selected[:limit]

    def create(self, request: ActionRequest) -> ActionResult:
        return ActionResult(False, "AS400 manual is read-only.")

    def read(self, request: ActionRequest) -> ActionResult:
        return ActionResult(False, "AS400 manual read actions are not supported through CRUD commands.")

    def update(self, request: ActionRequest) -> ActionResult:
        return ActionResult(False, "AS400 manual is read-only.")

    def delete(self, request: ActionRequest) -> ActionResult:
        return ActionResult(False, "AS400 manual is read-only.")

    def _load_documents(self) -> list[SearchDocument]:
        if self._documents_cache is not None:
            return self._documents_cache

        documents: list[SearchDocument] = []
        for manual_path in self.manual_paths:
            if manual_path.suffix.lower() == ".csv":
                documents.extend(self._load_csv_documents(manual_path))
                continue

            page_texts = self._extract_page_texts_for_file(manual_path)
            for _, page_number, page_text in page_texts:
                for chunk_index, chunk in enumerate(_chunk_text(page_text, settings.as400_chunk_chars)):
                    command_candidates = _extract_command_candidates(chunk)
                    documents.append(
                        SearchDocument(
                            source_type=self.source_type,
                            title=f"{self._manual_label(manual_path)} page {page_number}",
                            url=f"{manual_path.resolve()}#page={page_number}",
                            content=chunk,
                            metadata={
                                "manual_name": manual_path.stem,
                                "page": page_number,
                                "chunk_index": chunk_index,
                                "command_candidates": command_candidates,
                                "manual_path": str(manual_path.resolve()),
                                "source_kind": "manual_page",
                            },
                        )
                    )
        self._documents_cache = documents
        return documents

    def _load_csv_documents(self, manual_path: Path) -> list[SearchDocument]:
        documents: list[SearchDocument] = []
        with manual_path.open("r", encoding="utf-8-sig", errors="ignore", newline="") as handle:
            reader = csv.DictReader(handle)
            for row_index, row in enumerate(reader, start=1):
                table_name = _normalize_whitespace(row.get("TABLE_NAME", ""))
                table_text = _normalize_whitespace(row.get("TABLE_TEXT", ""))
                if not table_name and not table_text:
                    continue

                content = f"Table {table_name}. Description: {table_text}".strip()
                documents.append(
                    SearchDocument(
                        source_type=self.source_type,
                        title=f"{self._manual_label(manual_path)} {table_name}".strip(),
                        url=f"{manual_path.resolve()}#row={row_index}",
                        content=content,
                        metadata={
                            "manual_name": manual_path.stem,
                            "table_name": table_name,
                            "table_text": table_text,
                            "row": row_index,
                            "command_candidates": [],
                            "manual_path": str(manual_path.resolve()),
                            "source_kind": "table_catalog",
                        },
                    )
                )
        return documents

    def _extract_page_texts_for_file(self, manual_path: Path) -> list[tuple[Path, int, str]]:
        if manual_path.suffix.lower() == ".txt":
            text = manual_path.read_text(encoding="utf-8", errors="ignore")
            return [(manual_path, 1, text)]
        if manual_path.suffix.lower() == ".pdf":
            if PdfReader is None:
                return []
            reader = PdfReader(str(manual_path))
            pages: list[tuple[Path, int, str]] = []
            for index, page in enumerate(reader.pages, start=1):
                pages.append((manual_path, index, page.extract_text() or ""))
            return pages
        text = manual_path.read_text(encoding="utf-8", errors="ignore")
        return [(manual_path, 1, text)]

    @staticmethod
    def _resolve_manual_paths(path_spec: str) -> list[Path]:
        candidates: list[Path] = []
        seen: set[str] = set()
        for part in [item.strip() for item in path_spec.split(";") if item.strip()]:
            path = Path(part)
            resolved_paths: list[Path]
            if any(token in part for token in ("*", "?")):
                resolved_paths = sorted(candidate for candidate in path.parent.glob(path.name) if candidate.is_file())
            elif path.is_dir():
                preferred = sorted(
                    candidate
                    for candidate in path.iterdir()
                    if candidate.is_file() and candidate.suffix.lower() in {".pdf", ".txt", ".csv"}
                )
                resolved_paths = preferred or sorted(candidate for candidate in path.iterdir() if candidate.is_file())
            else:
                resolved_paths = [path] if path.exists() else []

            for resolved in resolved_paths:
                resolved_key = str(resolved.resolve())
                if resolved_key in seen:
                    continue
                seen.add(resolved_key)
                candidates.append(resolved)
        return candidates

    @staticmethod
    def _manual_label(manual_path: Path) -> str:
        stem = manual_path.stem.lower()
        if "fms_tables" in stem or "table" in stem:
            return "FMS table catalog"
        if "synon" in stem or "2e" in stem or "ca 2e" in stem or "ca2e" in stem:
            return "Synon 2E tutorial"
        if "ibm i" in stem or "as400" in stem or "cl" in stem:
            return "IBM i / AS400 manual"
        return manual_path.stem

    @staticmethod
    def _expand_query(query: str) -> str:
        lowered = query.lower()
        expansions: list[str] = [query]
        if any(token in lowered for token in ("synon", "2e", "ca 2e", "ca2e")):
            expansions.append("Synon 2E CA 2E tutorial model object design command")
        if ("obj" in lowered or "object" in lowered) and any(
            token in lowered for token in ("info", "information", "detail", "description", "see")
        ):
            expansions.append("WRKOBJ DSPOBJD object information object description work with objects")
        if "lock" in lowered:
            expansions.append("WRKOBJLCK object locks")
        if "history log" in lowered or "job log" in lowered or "log" in lowered:
            expansions.append("DSPLOG WRKOBJ QHST DSPOBJD")
        if "distribution list" in lowered or ("distribution" in lowered and "list" in lowered):
            expansions.append(
                "WRKDSTL DSPDSTL SNADS distribution list details summary work with distribution list display distribution list"
            )
        if "directory" in lowered and "distribution" in lowered:
            expansions.append("DSPDIRE WRKDSTL DSPDSTL distribution list directory")
        if any(token in lowered for token in ("table", "physical file", "pf")):
            expansions.append("table physical file database file record table name description")
        return " ".join(expansions)

    @staticmethod
    def _combined_search_score(
        query: str,
        semantic_score: float,
        document: SearchDocument,
        explicit_commands: list[str] | None = None,
    ) -> float:
        candidates = document.metadata.get("command_candidates", [])
        lowered_query = query.lower()
        lowered_content = document.content.lower()
        lowered_title = document.title.lower()
        lexical_score = _score(query, document.title, document.content, " ".join(candidates))
        base_score = (semantic_score * 0.85) + (lexical_score * 0.15)
        explicit_commands = explicit_commands or []
        if explicit_commands and AS400ManualConnector._contains_explicit_command(document, explicit_commands):
            base_score += 0.6
        if "command" in lowered_query and candidates:
            base_score += 0.2
        if any(command in query.upper() for command in candidates):
            base_score += 0.15
        if "WRKOBJ" in candidates and any(token in lowered_query for token in ("obj", "object", "info")):
            base_score += 0.12
        if "DSPOBJD" in candidates and any(
            token in lowered_query for token in ("desc", "description", "detail", "info")
        ):
            base_score += 0.1
        if "WRKDSTL" in candidates and any(
            token in lowered_query for token in ("distribution", "list", "work", "create")
        ):
            base_score += 0.18
        if "DSPDSTL" in candidates and any(
            token in lowered_query for token in ("distribution", "list", "display", "show")
        ):
            base_score += 0.14
        if document.metadata.get("source_kind") == "manual_page":
            if any(token in lowered_query for token in ("delete", "remove")) and any(
                token in lowered_content for token in ("delete", "remove", "dltf")
            ):
                base_score += 0.28
            if any(token in lowered_query for token in ("display", "show", "open", "view")) and any(
                token in lowered_content for token in ("display", "show", "open", "view", "dsppfm", "dspfd")
            ):
                base_score += 0.24
            if "create" in lowered_query and any(
                token in lowered_content for token in ("create", "crt", "generate")
            ):
                base_score += 0.22
            if "physical file" in lowered_query and "physical file" in lowered_content:
                base_score += 0.12
        table_name = str(document.metadata.get("table_name", "")).upper()
        if table_name and table_name in query.upper():
            base_score += 0.45
        if document.metadata.get("source_kind") == "table_catalog" and any(
            token in lowered_query for token in ("table", "physical file", "pf", "file")
        ):
            base_score += 0.18
        if document.metadata.get("source_kind") == "table_catalog" and any(
            token in lowered_query for token in ("related", "similar", "like")
        ):
            base_score += 0.12
        manual_name = str(document.metadata.get("manual_name", "")).lower()
        if any(token in lowered_query for token in ("synon", "2e", "ca 2e", "ca2e")) and any(
            token in manual_name for token in ("synon", "2e", "ca2e")
        ):
            base_score += 0.35
        if "vendor" in lowered_query and document.metadata.get("source_kind") == "table_catalog":
            table_text = str(document.metadata.get("table_text", "")).lower()
            if table_text == "vendor physical file":
                base_score += 0.8
            elif table_text.startswith("vendor "):
                base_score += 0.35
        if any(token in lowered_query for token in ("delete", "display", "open", "view")) and lowered_title:
            if any(token in lowered_title for token in ("physical file", "table")):
                base_score += 0.05
        return base_score

    @staticmethod
    def _extract_table_candidates(query: str, documents: list[SearchDocument]) -> set[str]:
        query_upper = query.upper()
        return {
            str(document.metadata.get("table_name", "")).upper()
            for document in documents
            if document.metadata.get("table_name")
            and str(document.metadata.get("table_name", "")).upper() in query_upper
        }

    @staticmethod
    def _is_table_catalog_query(query: str) -> bool:
        lowered = query.lower()
        return any(token in lowered for token in ("table", "physical file", "physical files", "pf", "files"))

    @staticmethod
    def _is_similar_table_query(query: str) -> bool:
        lowered = query.lower()
        return any(token in lowered for token in ("similar", "related", "like"))

    @staticmethod
    def _is_command_query(query: str) -> bool:
        lowered = query.lower()
        command_phrases = (
            "what command",
            "which command",
            "command to use",
            "how to use",
            "how do i use",
            "what is this command for",
            "create file",
            "generate file",
            "display file",
            "open file",
            "delete file",
            "delete table",
            "display table",
            "open table",
        )
        return any(phrase in lowered for phrase in command_phrases) or bool(
            _extract_command_candidates(query)
        )

    @staticmethod
    def _related_table_documents(
        documents: list[SearchDocument],
        explicit_tables: set[str],
        limit: int,
    ) -> list[SearchDocument]:
        anchor_documents = [
            document
            for document in documents
            if str(document.metadata.get("table_name", "")).upper() in explicit_tables
        ]
        if not anchor_documents:
            return []

        anchor = anchor_documents[0]
        anchor_tokens = {
            token
            for token in _tokenize(str(anchor.metadata.get("table_text", "")))
            if token not in {"physical", "file", "files", "table", "tables"}
        }
        related_scored: list[tuple[float, SearchDocument]] = []
        for document in documents:
            if document is anchor:
                continue
            if document.metadata.get("source_kind") != "table_catalog":
                continue
            candidate_tokens = set(_tokenize(str(document.metadata.get("table_text", ""))))
            overlap = len(anchor_tokens & candidate_tokens)
            score = float(overlap)
            if score <= 0:
                continue
            related_scored.append((score, document))

        related_scored.sort(
            key=lambda item: (item[0], len(str(item[1].metadata.get("table_text", "")))),
            reverse=True,
        )
        related = [document for _, document in related_scored[: max(limit - 1, 1)]]
        return [anchor, *related]

    @staticmethod
    def _keyword_table_documents(
        query: str,
        documents: list[SearchDocument],
        limit: int,
    ) -> list[SearchDocument]:
        query_terms = {
            term
            for term in _tokenize(query)
            if term
            not in {
                "find",
                "all",
                "which",
                "show",
                "table",
                "tables",
                "physical",
                "file",
                "files",
                "related",
                "about",
                "what",
                "are",
                "the",
                "as400",
                "ibm",
                "command",
                "commands",
                "open",
                "use",
                "using",
                "see",
                "records",
                "record",
                "view",
                "show",
                "how",
                "do",
                "does",
                "in",
                "to",
                "of",
                "that",
            }
        }
        if not query_terms:
            return []

        scored: list[tuple[float, SearchDocument]] = []
        for document in documents:
            if document.metadata.get("source_kind") != "table_catalog":
                continue
            table_name = str(document.metadata.get("table_name", ""))
            table_text = str(document.metadata.get("table_text", ""))
            searchable = f"{table_name} {table_text}".lower()
            searchable_terms = _tokenize(searchable)
            overlap = len(query_terms & searchable_terms)
            if overlap <= 0:
                continue

            score = float(overlap)
            normalized_text = table_text.lower()
            if any(normalized_text.startswith(term) for term in query_terms):
                score += 0.6
            if all(term in normalized_text for term in query_terms):
                score += 0.4
            if "vendor" in query_terms and normalized_text == "vendor physical file":
                score += 0.8
            scored.append((score, document))

        scored.sort(
            key=lambda item: (
                item[0],
                len(str(item[1].metadata.get("table_text", ""))),
                item[1].metadata.get("table_name", ""),
            ),
            reverse=True,
        )
        return [document for _, document in scored[:limit]]

    @staticmethod
    def _contains_explicit_command(document: SearchDocument, explicit_commands: list[str]) -> bool:
        searchable = (
            f"{document.title}\n{document.content}\n"
            f"{' '.join(document.metadata.get('command_candidates', []))}"
        ).upper()
        return any(command.upper() in searchable for command in explicit_commands)

    @staticmethod
    def _phrase_matched_documents(
        query: str,
        documents: list[SearchDocument],
    ) -> list[SearchDocument]:
        lowered = query.lower()
        phrases: list[str] = []
        if "command definition statements" in lowered:
            phrases.append("command definition statements")
        if "function differently" in lowered:
            phrases.append("function differently")
        if "procedure or program" in lowered:
            phrases.append("procedure or program")
        if not phrases:
            return []

        matched = [
            document
            for document in documents
            if all(phrase in document.content.lower() for phrase in phrases[:2])
        ]
        if matched:
            return matched

        return [
            document
            for document in documents
            if any(phrase in document.content.lower() for phrase in phrases)
        ]


class ConfluenceConnector(BaseConnector):
    """Search and manage Confluence pages through the content API."""

    source_type = "confluence"
    target_type = "page"

    def __init__(self, mcp_adapter: MCPAdapter | None = None) -> None:
        super().__init__(mcp_adapter=mcp_adapter)

    @property
    def configured(self) -> bool:
        if self.mcp_adapter and self.mcp_adapter.is_enabled(self.source_type):
            return True
        return all(
            [
                _is_real_value(settings.confluence_base_url),
                _is_real_value(settings.confluence_username),
                _is_real_value(settings.confluence_api_token),
            ]
        )

    def search(self, query: str, limit: int) -> list[SearchDocument]:
        """Search Confluence, then retry with fallback keywords if needed."""
        if not self.configured:
            return []
        if self.mcp_adapter:
            delegated = self.mcp_adapter.search(self.source_type, query, limit)
            if delegated is not None:
                return delegated

        queries = [query, *_fallback_terms(query)]
        documents: list[SearchDocument] = []
        seen_urls: set[str] = set()

        for query_text in queries:
            for document in self._search_once(query_text, limit):
                if document.url in seen_urls:
                    continue
                seen_urls.add(document.url)
                documents.append(document)
            if len(documents) >= limit:
                break

        return self._rank(query, documents)[:limit]

    def create(self, request: ActionRequest) -> ActionResult:
        """Create a Confluence page in the configured or requested space."""
        if not self.configured:
            return ActionResult(False, "Confluence is not configured.")
        if self.mcp_adapter:
            delegated = self.mcp_adapter.execute(self.source_type, request)
            if delegated is not None:
                return delegated

        title = request.fields.get("title")
        body = request.fields.get("body")
        space_key = request.fields.get("space_key") or settings.confluence_space_key
        parent_id = request.fields.get("parent_id")

        if not title or not body:
            return ActionResult(
                False,
                "Confluence page creation requires title and body fields.",
            )
        if not space_key:
            return ActionResult(
                False,
                "Confluence page creation requires CONFLUENCE_SPACE_KEY or space_key=...",
            )

        payload: dict[str, Any] = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {
                "storage": {
                    "value": _wrap_storage_body(body),
                    "representation": "storage",
                }
            },
        }
        if parent_id:
            payload["ancestors"] = [{"id": str(parent_id)}]

        response = self.session.post(
            self._content_api_url(),
            json=payload,
            auth=self._auth(),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        created = response.json()
        document = self._document_from_page(self._get_page_by_id(created["id"]))
        return ActionResult(
            success=True,
            message=f"Created Confluence page '{document.title}'.",
            document=document,
            details={"id": created["id"]},
        )

    def read(self, request: ActionRequest) -> ActionResult:
        """Fetch a Confluence page by id or, when needed, by title search."""
        if not self.configured:
            return ActionResult(False, "Confluence is not configured.")
        if self.mcp_adapter:
            delegated = self.mcp_adapter.execute(self.source_type, request)
            if delegated is not None:
                return delegated

        page = self._resolve_page(request)
        if page is None:
            return ActionResult(False, "Could not find the requested Confluence page.")

        document = self._document_from_page(page)
        return ActionResult(
            success=True,
            message=f"Loaded Confluence page '{document.title}'.",
            document=document,
            details={"id": page.get("id")},
        )

    def update(self, request: ActionRequest) -> ActionResult:
        """Update title and/or body for an existing Confluence page."""
        if not self.configured:
            return ActionResult(False, "Confluence is not configured.")
        if self.mcp_adapter:
            delegated = self.mcp_adapter.execute(self.source_type, request)
            if delegated is not None:
                return delegated

        page = self._resolve_page(request)
        if page is None:
            return ActionResult(False, "Could not find the requested Confluence page.")

        current_version = page.get("version", {}).get("number")
        if current_version is None:
            return ActionResult(False, "Could not determine the current Confluence page version.")

        title = request.fields.get("title") or page.get("title")
        body = request.fields.get("body") or page.get("body", {}).get("storage", {}).get("value", "")
        space_key = request.fields.get("space_key") or page.get("space", {}).get("key")
        parent_id = request.fields.get("parent_id")

        payload: dict[str, Any] = {
            "id": page["id"],
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {
                "storage": {
                    "value": _wrap_storage_body(body),
                    "representation": "storage",
                }
            },
            "version": {"number": current_version + 1},
        }
        if parent_id:
            payload["ancestors"] = [{"id": str(parent_id)}]

        response = self.session.put(
            f"{self._content_api_url()}/{page['id']}",
            json=payload,
            auth=self._auth(),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        document = self._document_from_page(self._get_page_by_id(page["id"]))
        return ActionResult(
            success=True,
            message=f"Updated Confluence page '{document.title}'.",
            document=document,
            details={"id": page["id"]},
        )

    def delete(self, request: ActionRequest) -> ActionResult:
        """Delete a Confluence page by id or title lookup."""
        if not self.configured:
            return ActionResult(False, "Confluence is not configured.")
        if self.mcp_adapter:
            delegated = self.mcp_adapter.execute(self.source_type, request)
            if delegated is not None:
                return delegated

        page = self._resolve_page(request)
        if page is None:
            return ActionResult(False, "Could not find the requested Confluence page.")

        document = self._document_from_page(page)
        response = self.session.delete(
            f"{self._content_api_url()}/{page['id']}",
            auth=self._auth(),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return ActionResult(
            success=True,
            message=f"Deleted Confluence page '{document.title}'.",
            document=document,
            details={"id": page["id"]},
        )

    def _search_once(self, query: str, limit: int) -> list[SearchDocument]:
        """Run a single Confluence CQL search and normalize the result set."""
        cql_parts = [f'text ~ "{query}"']
        if settings.confluence_space_key:
            cql_parts.append(f'space = "{settings.confluence_space_key}"')

        response = self.session.get(
            f"{self._content_api_url()}/search",
            params={
                "cql": " AND ".join(cql_parts),
                "limit": limit,
                "expand": CONFLUENCE_EXPAND_FIELDS,
            },
            auth=self._auth(),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        return [self._document_from_page(item, matched_query=query) for item in payload.get("results", [])]

    def _resolve_page(self, request: ActionRequest) -> dict[str, Any] | None:
        """Resolve a page by explicit id, title field, or search fallback."""
        identifier = request.identifier or request.fields.get("id")
        if identifier and identifier.isdigit():
            return self._get_page_by_id(identifier)

        title = request.fields.get("title")
        if title:
            page = self._get_page_by_title(title)
            if page:
                return page

        if identifier:
            page = self._get_page_by_title(identifier)
            if page:
                return page

        return None

    def _get_page_by_id(self, page_id: str) -> dict[str, Any]:
        """Load a single page record with body and version info."""
        response = self.session.get(
            f"{self._content_api_url()}/{page_id}",
            params={"expand": CONFLUENCE_EXPAND_FIELDS},
            auth=self._auth(),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()

    def _get_page_by_title(self, title: str) -> dict[str, Any] | None:
        """Look up the first page whose title matches the provided title."""
        cql_parts = [f'type = "page"', f'title = "{title}"']
        if settings.confluence_space_key:
            cql_parts.append(f'space = "{settings.confluence_space_key}"')

        response = self.session.get(
            f"{self._content_api_url()}/search",
            params={
                "cql": " AND ".join(cql_parts),
                "limit": 1,
                "expand": CONFLUENCE_EXPAND_FIELDS,
            },
            auth=self._auth(),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        results = response.json().get("results", [])
        return results[0] if results else None

    def _document_from_page(
        self,
        page: dict[str, Any],
        matched_query: str | None = None,
    ) -> SearchDocument:
        """Normalize a Confluence page payload into the shared document model."""
        links = page.get("_links", {})
        body = page.get("body", {}).get("storage", {}).get("value", "")
        return SearchDocument(
            source_type=self.source_type,
            title=page.get("title", "Untitled Confluence page"),
            url=_build_confluence_url(settings.confluence_base_url, links),
            content=body,
            metadata={
                "id": page.get("id"),
                "status": page.get("status"),
                "version": page.get("version", {}).get("number"),
                "space_key": page.get("space", {}).get("key"),
                "matched_query": matched_query,
                "plain_text_preview": _strip_html(body)[:300],
            },
        )

    @staticmethod
    def _auth() -> tuple[str, str]:
        """Return the basic auth tuple used for Confluence Cloud."""
        return (settings.confluence_username, settings.confluence_api_token)

    @staticmethod
    def _content_api_url() -> str:
        """Return the base Confluence content API URL."""
        return f"{settings.confluence_base_url.rstrip('/')}/wiki/rest/api/content"


class JiraConnector(BaseConnector):
    """Search and manage Jira issues through the v3 REST API."""

    source_type = "jira"
    target_type = "ticket"

    def __init__(self, mcp_adapter: MCPAdapter | None = None) -> None:
        super().__init__(mcp_adapter=mcp_adapter)

    @property
    def configured(self) -> bool:
        if self.mcp_adapter and self.mcp_adapter.is_enabled(self.source_type):
            return True
        return all(
            [
                _is_real_value(settings.jira_base_url),
                _is_real_value(settings.jira_username),
                _is_real_value(settings.jira_api_token),
            ]
        )

    def search(self, query: str, limit: int) -> list[SearchDocument]:
        """Search Jira issues and normalize them into the shared document model."""
        if not self.configured:
            return []
        if self.mcp_adapter:
            delegated = self.mcp_adapter.search(self.source_type, query, limit)
            if delegated is not None:
                return delegated

        jql_candidates = self._build_jql_candidates(query)
        documents: list[SearchDocument] = []
        seen_urls: set[str] = set()

        for jql in jql_candidates:
            for document in self._search_once(jql, limit):
                if document.url in seen_urls:
                    continue
                seen_urls.add(document.url)
                documents.append(document)
            if documents:
                break

        return self._rank(query, documents)[:limit]

    def create(self, request: ActionRequest) -> ActionResult:
        """Create a Jira ticket in the configured or discovered project."""
        if not self.configured:
            return ActionResult(False, "Jira is not configured.")
        if self.mcp_adapter:
            delegated = self.mcp_adapter.execute(self.source_type, request)
            if delegated is not None:
                return delegated

        summary = request.fields.get("summary")
        description = request.fields.get("description", "")
        issue_type = request.fields.get("issue_type", "Task")
        project_key = request.fields.get("project_key") or self._default_project_key()

        if not summary:
            return ActionResult(False, "Jira ticket creation requires summary=...")
        if not project_key:
            return ActionResult(False, "Jira ticket creation requires JIRA_PROJECT_KEY or project_key=...")

        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary,
                "issuetype": {"name": issue_type},
                "description": _jira_description_to_adf(description),
            }
        }

        response = self.session.post(
            f"{settings.jira_base_url.rstrip('/')}/rest/api/3/issue",
            json=payload,
            auth=self._auth(),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        created = response.json()

        if request.fields.get("assignee"):
            self._update_assignee(created["key"], request.fields["assignee"])
        if request.fields.get("status"):
            self._transition_issue(created["key"], request.fields["status"])

        document = self._document_from_issue(self._get_issue(created["key"]))
        return ActionResult(
            success=True,
            message=f"Created Jira ticket {document.title}.",
            document=document,
            details={"key": created["key"]},
        )

    def read(self, request: ActionRequest) -> ActionResult:
        """Fetch a Jira issue by key, or by the first issue matching a summary query."""
        if not self.configured:
            return ActionResult(False, "Jira is not configured.")
        if self.mcp_adapter:
            delegated = self.mcp_adapter.execute(self.source_type, request)
            if delegated is not None:
                return delegated

        issue = self._resolve_issue(request)
        if issue is None:
            return ActionResult(False, "Could not find the requested Jira ticket.")

        document = self._document_from_issue(issue)
        return ActionResult(
            success=True,
            message=f"Loaded Jira ticket {document.title}.",
            document=document,
            details={"key": issue.get("key")},
        )

    def update(self, request: ActionRequest) -> ActionResult:
        """Update summary, description, assignee, or status for a Jira issue."""
        if not self.configured:
            return ActionResult(False, "Jira is not configured.")
        if self.mcp_adapter:
            delegated = self.mcp_adapter.execute(self.source_type, request)
            if delegated is not None:
                return delegated

        issue = self._resolve_issue(request)
        if issue is None:
            return ActionResult(False, "Could not find the requested Jira ticket.")

        issue_key = issue["key"]
        fields_payload: dict[str, Any] = {}
        if request.fields.get("summary"):
            fields_payload["summary"] = request.fields["summary"]
        if request.fields.get("description") is not None:
            fields_payload["description"] = _jira_description_to_adf(request.fields["description"])

        if fields_payload:
            response = self.session.put(
                f"{settings.jira_base_url.rstrip('/')}/rest/api/3/issue/{issue_key}",
                json={"fields": fields_payload},
                auth=self._auth(),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()

        if request.fields.get("assignee"):
            self._update_assignee(issue_key, request.fields["assignee"])
        if request.fields.get("status"):
            self._transition_issue(issue_key, request.fields["status"])

        document = self._document_from_issue(self._get_issue(issue_key))
        return ActionResult(
            success=True,
            message=f"Updated Jira ticket {document.title}.",
            document=document,
            details={"key": issue_key},
        )

    def delete(self, request: ActionRequest) -> ActionResult:
        """Delete a Jira issue by key or lookup query."""
        if not self.configured:
            return ActionResult(False, "Jira is not configured.")
        if self.mcp_adapter:
            delegated = self.mcp_adapter.execute(self.source_type, request)
            if delegated is not None:
                return delegated

        issue = self._resolve_issue(request)
        if issue is None:
            return ActionResult(False, "Could not find the requested Jira ticket.")

        document = self._document_from_issue(issue)
        response = self.session.delete(
            f"{settings.jira_base_url.rstrip('/')}/rest/api/3/issue/{issue['key']}",
            auth=self._auth(),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return ActionResult(
            success=True,
            message=f"Deleted Jira ticket {document.title}.",
            document=document,
            details={"key": issue["key"]},
        )

    def add_comment(self, issue_key: str, comment: str) -> None:
        """Post a plain-text comment to a Jira issue."""
        if not self.configured:
            raise ValueError("Jira is not configured.")
        response = self.session.post(
            f"{settings.jira_base_url.rstrip('/')}/rest/api/3/issue/{issue_key}/comment",
            json={"body": _jira_description_to_adf(comment)},
            auth=self._auth(),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

    def _build_jql_candidates(self, query: str) -> list[str]:
        """Build a small set of bounded Jira queries, newest-first."""
        candidates: list[str] = []
        project_keys = self._project_keys()
        scope = self._project_scope(project_keys)

        candidates.append(
            scope + f'(summary ~ "{query}" OR description ~ "{query}" OR text ~ "{query}") ORDER BY updated DESC'
        )

        for term in _fallback_terms(query):
            candidates.append(
                scope + f'(summary ~ "{term}" OR description ~ "{term}" OR text ~ "{term}") ORDER BY updated DESC'
            )

        if project_keys:
            candidates.append(self._recent_issues_jql(project_keys))

        deduplicated: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            deduplicated.append(candidate)
        return deduplicated

    def _project_keys(self) -> list[str]:
        """Resolve the Jira project scope from config or the accessible project list."""
        if settings.jira_project_key:
            return [settings.jira_project_key]
        return self._discover_project_keys()

    def _default_project_key(self) -> str | None:
        """Return the first known project key for create requests."""
        project_keys = self._project_keys()
        return project_keys[0] if project_keys else None

    def _discover_project_keys(self) -> list[str]:
        """Discover accessible Jira projects for bounded search and create defaults."""
        response = self.session.get(
            f"{settings.jira_base_url.rstrip('/')}/rest/api/3/project/search",
            auth=self._auth(),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        return [project["key"] for project in payload.get("values", []) if project.get("key")]

    @staticmethod
    def _project_scope(project_keys: list[str]) -> str:
        """Build a project scope prefix suitable for JQL queries."""
        if not project_keys:
            return ""
        if len(project_keys) == 1:
            return f'project = "{project_keys[0]}" AND '
        quoted_keys = ", ".join(f'"{key}"' for key in project_keys)
        return f"project in ({quoted_keys}) AND "

    @staticmethod
    def _recent_issues_jql(project_keys: list[str]) -> str:
        """Return a valid bounded JQL query for the most recently updated issues."""
        if len(project_keys) == 1:
            return f'project = "{project_keys[0]}" ORDER BY updated DESC'
        quoted_keys = ", ".join(f'"{key}"' for key in project_keys)
        return f"project in ({quoted_keys}) ORDER BY updated DESC"

    def _search_once(self, jql: str, limit: int) -> list[SearchDocument]:
        """Run a single Jira JQL search using the current API path."""
        response = self.session.get(
            f"{settings.jira_base_url.rstrip('/')}/rest/api/3/search/jql",
            params={
                "jql": jql,
                "maxResults": limit,
                "fields": JIRA_FIELDS,
            },
            auth=self._auth(),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        return [self._document_from_issue(issue, matched_jql=jql) for issue in payload.get("issues", [])]

    def _resolve_issue(self, request: ActionRequest) -> dict[str, Any] | None:
        """Resolve an issue by explicit key or by summary search."""
        identifier = request.identifier or request.fields.get("key")
        if identifier and re.match(r"^[A-Z][A-Z0-9_]+-\d+$", identifier):
            return self._get_issue(identifier)

        summary_query = request.fields.get("summary") or identifier
        if not summary_query:
            return None

        matches = self.search(summary_query, 1)
        if not matches:
            return None
        key = matches[0].metadata.get("key")
        if not key:
            return None
        return self._get_issue(str(key))

    def _get_issue(self, issue_key: str) -> dict[str, Any]:
        """Fetch a single Jira issue record by key."""
        response = self.session.get(
            f"{settings.jira_base_url.rstrip('/')}/rest/api/3/issue/{issue_key}",
            params={"fields": JIRA_FIELDS},
            auth=self._auth(),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()

    def _transition_issue(self, issue_key: str, status_name: str) -> None:
        """Move an issue to a named workflow status."""
        response = self.session.get(
            f"{settings.jira_base_url.rstrip('/')}/rest/api/3/issue/{issue_key}/transitions",
            auth=self._auth(),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        transitions = response.json().get("transitions", [])
        requested = status_name.lower().strip()
        for transition in transitions:
            if transition.get("name", "").lower() == requested:
                move = self.session.post(
                    f"{settings.jira_base_url.rstrip('/')}/rest/api/3/issue/{issue_key}/transitions",
                    json={"transition": {"id": transition["id"]}},
                    auth=self._auth(),
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                move.raise_for_status()
                return
        if requested in {"close", "closed", "resolve", "resolved", "done", "complete", "completed"}:
            for transition in transitions:
                transition_name = transition.get("name", "").lower()
                status_category = (
                    transition.get("to", {})
                    .get("statusCategory", {})
                    .get("key", "")
                    .lower()
                )
                if status_category == "done" or transition_name in {
                    "done",
                    "closed",
                    "resolved",
                    "complete",
                    "completed",
                }:
                    move = self.session.post(
                        f"{settings.jira_base_url.rstrip('/')}/rest/api/3/issue/{issue_key}/transitions",
                        json={"transition": {"id": transition["id"]}},
                        auth=self._auth(),
                        timeout=REQUEST_TIMEOUT_SECONDS,
                    )
                    move.raise_for_status()
                    return
        raise ValueError(f"Could not find a Jira transition named '{status_name}'.")

    def _update_assignee(self, issue_key: str, assignee: str) -> None:
        """Assign an issue to the current user or a specific Jira account id."""
        account_id = self._resolve_account_id(assignee)
        if not account_id:
            raise ValueError(f"Could not resolve Jira assignee '{assignee}'.")
        response = self.session.put(
            f"{settings.jira_base_url.rstrip('/')}/rest/api/3/issue/{issue_key}/assignee",
            json={"accountId": account_id},
            auth=self._auth(),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

    def _resolve_account_id(self, assignee: str) -> str | None:
        """Resolve 'me' or a supplied account id into the Jira account id to assign."""
        if assignee.lower() == "me":
            response = self.session.get(
                f"{settings.jira_base_url.rstrip('/')}/rest/api/3/myself",
                auth=self._auth(),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.json().get("accountId")
        return assignee

    def _document_from_issue(
        self,
        issue: dict[str, Any],
        matched_jql: str | None = None,
    ) -> SearchDocument:
        """Normalize a Jira issue payload into the shared document model."""
        fields = issue.get("fields", {})
        key = issue.get("key", "UNKNOWN")
        assignee = fields.get("assignee") or {}
        return SearchDocument(
            source_type=self.source_type,
            title=f"{key}: {fields.get('summary', 'Untitled issue')}",
            url=f"{settings.jira_base_url.rstrip('/')}/browse/{key}",
            content=_jira_description_to_text(fields.get("description")),
            metadata={
                "key": key,
                "status": fields.get("status", {}).get("name"),
                "issue_type": fields.get("issuetype", {}).get("name"),
                "project_key": fields.get("project", {}).get("key"),
                "assignee": assignee.get("displayName"),
                "assignee_account_id": assignee.get("accountId"),
                "matched_jql": matched_jql,
            },
        )

    @staticmethod
    def _auth() -> tuple[str, str]:
        """Return the basic auth tuple used for Jira Cloud."""
        return (settings.jira_username, settings.jira_api_token)


class JiraPerformanceWorkflowConnector(BaseConnector):
    """Drive a ticket-based Jira -> strategy -> script -> run -> analysis workflow."""

    source_type = "jira"
    target_type = "workflow"

    def __init__(
        self,
        jira_connector: JiraConnector | None = None,
        workspace: K6Workspace | None = None,
        grafana_connector: "GrafanaConnector | None" = None,
        skill_catalog: ProjectSkillCatalog | None = None,
        responder: OpenAIResponder | None = None,
    ) -> None:
        super().__init__()
        self.jira_connector = jira_connector or JiraConnector()
        self.workspace = workspace or K6Workspace()
        self.grafana_connector = grafana_connector
        self.skill_catalog = skill_catalog or ProjectSkillCatalog()
        self.responder = responder or OpenAIResponder()

    @property
    def configured(self) -> bool:
        return self.jira_connector.configured and bool(self.workspace.k6_command_path)

    @property
    def configuration_message(self) -> str:
        if not self.jira_connector.configured:
            return self.jira_connector.configuration_message
        if not self.workspace.k6_command_path:
            return self.workspace.configuration_message
        return "Jira performance workflow is configured."

    def search(self, query: str, limit: int) -> list[SearchDocument]:
        return self.jira_connector.search(query, limit)

    def create(self, request: ActionRequest) -> ActionResult:
        return ActionResult(False, "Use `test jira DEV-42` or `run jira DEV-42` for the performance workflow.")

    def read(self, request: ActionRequest) -> ActionResult:
        return ActionResult(False, "Use `test jira DEV-42` or `run jira DEV-42` to execute the workflow.")

    def update(self, request: ActionRequest) -> ActionResult:
        return ActionResult(False, "Updating Jira workflow records is not supported.")

    def delete(self, request: ActionRequest) -> ActionResult:
        return ActionResult(False, "Deleting Jira workflow artifacts is not supported.")

    def execute(self, request: ActionRequest) -> ActionResult:
        if request.operation == "run":
            return self.run(request)
        return super().execute(request)

    def run(self, request: ActionRequest) -> ActionResult:
        if not self.configured:
            return ActionResult(False, self.configuration_message)

        issue_key = request.identifier or request.fields.get("ticket") or request.fields.get("key") or ""
        if not issue_key:
            return ActionResult(False, "Jira performance workflow requires an issue key, for example: test jira DEV-42")

        jira_result = self.jira_connector.read(
            ActionRequest(
                operation="read",
                target_system="jira",
                target_type="ticket",
                identifier=issue_key,
            )
        )
        if not jira_result.success or jira_result.document is None:
            return ActionResult(False, f"Could not load Jira ticket {issue_key}.")

        LOGGER.info("Workflow ticket loaded: issue=%s", issue_key)
        decision = self._decide_ticket_workflow(jira_result.document, request.fields)
        if decision is None:
            return ActionResult(False, f"Could not determine workflow decision for Jira ticket {issue_key}.")
        selected_skills = self.skill_catalog.for_names(decision.ordered_skills)
        selected_skill_names = [skill.name for skill in selected_skills]
        LOGGER.info(
            "Workflow decision: issue=%s mode=%s skills=%s",
            issue_key,
            decision.execution_mode,
            ",".join(selected_skill_names),
        )
        plan = self._build_plan(jira_result.document, request.fields, selected_skill_names)
        if plan is None:
            return ActionResult(False, f"Could not extract a structured performance plan from Jira ticket {issue_key}.")
        LOGGER.info("Workflow plan extracted: issue=%s service=%s endpoint=%s %s", issue_key, plan.service, plan.endpoint_method, plan.endpoint_path)
        if decision.execution_mode == "plan_only":
            LOGGER.info("Workflow execution skipped by model decision: issue=%s", issue_key)
            plan_document = self._create_plan_document(plan, selected_skills, decision)
            comment_body = self._jira_comment_body(plan, plan_document, None, selected_skills, decision)
            comment_status = "comment skipped"
            try:
                self.jira_connector.add_comment(plan.issue_key, comment_body)
                comment_status = "comment posted"
            except Exception as exc:
                comment_status = f"comment failed: {exc}"
            message = (
                f"Completed Jira planning workflow for {plan.issue_key}. "
                f"Service={plan.service}. Plan: {plan_document.url}. Jira {comment_status}."
            )
            preview = self._plan_preview(plan_document.content)
            if preview:
                message += f"\n\nSlack Plan Preview:\n{preview}"
            message += self.skill_catalog.format_for_message(selected_skills)
            return ActionResult(True, message, document=plan_document)

        LOGGER.info("Workflow script generation started: issue=%s", issue_key)
        script_path = self._generate_script(plan, selected_skill_names)
        run_fields = dict(request.fields)
        run_fields.setdefault("vus", str(plan.vus))
        run_fields.setdefault("duration", plan.duration)
        run_fields.setdefault("base_url", request.fields.get("base_url", self._default_base_url(plan.service)))

        LOGGER.info("Workflow k6 run started: issue=%s script=%s", issue_key, script_path)
        run_result = self.workspace.run_script(script_path, plan.service, run_fields)
        LOGGER.info("Workflow k6 run finished: issue=%s exit_code=%s", issue_key, run_result.exit_code)
        grafana_document = _safe_grafana_lookup(self.grafana_connector, plan.service)
        report_document = self.workspace.generate_report_with_context(
            plan.service,
            summary_path=run_result.summary_path,
            dashboard_url=grafana_document.url if grafana_document else "",
            playbooks=selected_skills,
            playbook_notes=self.skill_catalog.guidance_for_skills(
                selected_skills,
                metrics=_k6_metric_summary(run_result),
            ),
            workflow_context={
                "jira_issue": plan.issue_key,
                "dataset": plan.dataset,
                "test_type": plan.test_type,
                "script_path": self._workflow_script_path(script_path),
                "include_workflow_trace": "true",
            },
        )
        LOGGER.info("Workflow report generation finished: issue=%s report=%s", issue_key, report_document.url)
        report_document = self._enhance_report(
            report_document,
            plan,
            run_result,
            grafana_document,
            selected_skill_names,
        )
        report_document.metadata.update(
            {
                "issue_key": plan.issue_key,
                "service": plan.service,
                "script_path": str(script_path),
                "summary_path": str(run_result.summary_path),
                "report_path": report_document.url,
                "run_dir": str(run_result.run_dir),
            }
        )

        metric_summary = _k6_metric_summary(run_result)
        comment_body = self._jira_comment_body(plan, report_document, grafana_document, selected_skills, decision, metric_summary, run_result.summary_path)
        comment_status = "comment skipped"
        try:
            self.jira_connector.add_comment(plan.issue_key, comment_body)
            comment_status = "comment posted"
        except Exception as exc:
            comment_status = f"comment failed: {exc}"
        LOGGER.info("Workflow Jira comment status: issue=%s status=%s", issue_key, comment_status)
        try:
            run_dir_display = str(run_result.run_dir.resolve().relative_to(self.workspace.project_root.resolve())).replace("\\", "/")
        except ValueError:
            run_dir_display = str(run_result.run_dir)
        script_display = self._workflow_script_path(script_path)
        report_display = self._relative_workspace_path(Path(report_document.url))
        html_report_display = self._relative_workspace_path(
            Path(report_document.url).with_name(f"{Path(report_document.url).stem.replace('-report', '')}-report.html")
        )
        message = (
            f"Completed Jira performance workflow for {plan.issue_key}. "
            f"Service={plan.service}. Script: {script_display}. "
            f"Report: {report_display}. HTML Report: {html_report_display}. Jira {comment_status}. "
            f"Git: git add {run_dir_display}."
        )
        message += (
            f"\n"
            f"Latency SLO: {self._latency_status(metric_summary, plan)} "
            f"(p95 {self._format_latency_value(metric_summary.get('p95'))} vs target < {plan.sla_p95_ms} ms). "
            f"HTTP failures: {self._format_percentage(metric_summary.get('failure_rate'))} "
            f"(target < {plan.error_rate_threshold * 100:.2f}%)."
        )
        message += (
            f"\n"
            f"Acceptance checks: {self._format_percentage(metric_summary.get('check_rate'))} pass. "
            f"Requests: {metric_summary.get('request_count', 'n/a')}."
        )
        if grafana_document is not None:
            message += f" Grafana: {grafana_document.url}."
        preview = _report_preview(report_document.content)
        if preview:
            message += f"\n\nSlack Report Preview:\n{preview}"
        message += self.skill_catalog.format_for_message(selected_skills)
        passed = run_result.exit_code == 0 and self._passed(_k6_metric_summary(run_result), plan)
        return ActionResult(passed, message, document=report_document)

    def _build_plan(
        self,
        ticket: SearchDocument,
        fields: dict[str, str],
        selected_skill_names: list[str],
    ) -> TicketPerformancePlan | None:
        strategy_bundle = self._skill_bundle_if_selected("performance-testing-strategy", selected_skill_names)
        modeled_plan = self._build_plan_via_model(ticket, fields, strategy_bundle)
        if self._is_ticket_grounded_plan(modeled_plan):
            return modeled_plan
        ticket_plan = self._build_plan_from_ticket_text(ticket, fields)
        if self._is_ticket_grounded_plan(ticket_plan):
            return ticket_plan
        return self._build_plan_from_ticket_and_repo_docs(ticket, fields)

    def _build_plan_via_model(
        self,
        ticket: SearchDocument,
        fields: dict[str, str],
        bundle: SkillBundle,
    ) -> TicketPerformancePlan | None:
        if not bundle.skill_text:
            return None
        summary = ticket.title.split(": ", 1)[1] if ": " in ticket.title else ticket.title
        payload = self.responder.call_function(
            system_prompt=(
                "You are extracting a structured performance test plan from a Jira ticket. "
                "Use the supplied skill, references, and evals as mandatory guidance."
            ),
            user_prompt=(
                f"Ticket key: {ticket.metadata.get('key', '')}\n"
                f"Summary: {summary}\n"
                f"Description:\n{ticket.content}\n\n"
                f"User overrides: {fields}\n\n"
                f"Skill:\n{bundle.skill_text}\n\n"
                f"References:\n{self._format_skill_references(bundle)}\n\n"
                f"Evals:\n{self._format_skill_evals(bundle)}\n\n"
                "Use only ticket-grounded facts; if missing, infer conservatively and say so in strategy_notes."
            ),
            function_name="extract_ticket_performance_plan",
            function_description="Extract the structured performance test plan from a Jira ticket.",
            parameters=self._ticket_plan_function_schema(),
            temperature=0.1,
        )
        if not isinstance(payload, dict):
            return None
        try:
            plan = TicketPerformancePlan(
                issue_key=str(ticket.metadata.get("key", "")),
                summary=summary,
                description=ticket.content or "",
                service=str(payload.get("service") or fields.get("service") or "").lower(),
                endpoint_method=str(payload.get("endpoint_method") or "").upper(),
                endpoint_path=str(payload.get("endpoint_path") or ""),
                sla_p95_ms=int(payload.get("sla_p95_ms") or 0),
                error_rate_threshold=float(payload.get("error_rate_percent") or 0) / 100,
                vus=int(payload.get("vus") or fields.get("vus") or 2),
                duration=str(payload.get("duration") or fields.get("duration") or "30s"),
                dataset=str(payload.get("dataset") or fields.get("dataset") or "users.json"),
                test_type=str(payload.get("test_type") or fields.get("type") or "load"),
                criteria=[str(item) for item in (payload.get("criteria") or [])][:8],
                strategy_notes=[str(item) for item in (payload.get("strategy_notes") or [])][:8],
            )
            return plan
        except (TypeError, ValueError):
            return None

    def _build_plan_from_ticket_text(
        self,
        ticket: SearchDocument,
        fields: dict[str, str],
    ) -> TicketPerformancePlan | None:
        summary = ticket.title.split(": ", 1)[1] if ": " in ticket.title else ticket.title
        description = ticket.content or ""
        combined = f"{summary}\n{description}"
        endpoint_method, endpoint_path = self._extract_endpoint(combined)
        service = self._normalize_service_name(
            (fields.get("service") or self._infer_service(combined, endpoint_path) or self._infer_service_from_issue(summary, description)).lower()
        )
        sla_p95_ms = self._extract_int(combined, r"\bp95\b[^\d]{0,20}(\d+)\s*ms", 0)
        if sla_p95_ms <= 0 and service:
            sla_p95_ms = self._extract_service_scoped_slo_int(combined, service, "p95")
        error_rate_percent = self._extract_float(
            combined,
            r"\berror\s*rate\b[^\d]{0,20}(\d+(?:\.\d+)?)\s*%",
            0,
        )
        if error_rate_percent <= 0 and service:
            error_rate_percent = self._extract_service_scoped_slo_float(combined, service, "error_rate")
        if not service or sla_p95_ms <= 0 or error_rate_percent <= 0:
            return None
        if not endpoint_path or endpoint_path == "/" or endpoint_method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            repo_context = self._load_repo_docs_context()
            service_context = self._repo_service_context(repo_context, service) if repo_context else ""
            if service_context:
                endpoint_method, endpoint_path = self._extract_endpoint(service_context)
            if (not endpoint_path or endpoint_path == "/") and repo_context:
                endpoint_method, endpoint_path = self._extract_endpoint(repo_context)
        if sla_p95_ms <= 0 or error_rate_percent <= 0:
            return None
        if not endpoint_path or endpoint_path == "/" or endpoint_method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            return None
        vus = self._extract_int(
            fields.get("vus", "") or combined,
            r"(?:\bvus\b|\bvirtual users\b|\bconcurrent users\b)\s*[:=]?\s*(\d+)",
            2,
        )
        duration = fields.get("duration") or self._extract_duration(combined) or "30s"
        criteria = self._extract_acceptance_criteria(description)
        strategy_notes = [
            "Plan recovered deterministically from Jira text because the model plan was unavailable or incomplete.",
            f"Use `{service}` service tags for all thresholds and observability queries.",
            f"Validate `{endpoint_method} {endpoint_path}` against the ticket criteria before sign-off.",
        ]
        return TicketPerformancePlan(
            issue_key=str(ticket.metadata.get("key") or fields.get("ticket") or ""),
            summary=summary,
            description=description,
            service=service,
            endpoint_method=endpoint_method,
            endpoint_path=endpoint_path,
            sla_p95_ms=sla_p95_ms,
            error_rate_threshold=error_rate_percent / 100,
            vus=vus,
            duration=duration,
            dataset=fields.get("dataset") or self._extract_dataset(combined) or "users.json",
            test_type=fields.get("type") or self._extract_test_type(combined),
            criteria=criteria,
            strategy_notes=strategy_notes,
        )

    def _build_plan_from_ticket_and_repo_docs(
        self,
        ticket: SearchDocument,
        fields: dict[str, str],
    ) -> TicketPerformancePlan | None:
        summary = ticket.title.split(": ", 1)[1] if ": " in ticket.title else ticket.title
        description = ticket.content or ""
        combined = f"{summary}\n{description}"
        repo_context = self._load_repo_docs_context()
        if not repo_context:
            return None

        endpoint_method, endpoint_path = self._extract_endpoint(combined)
        service = (fields.get("service") or self._infer_service(combined, endpoint_path)).lower()
        service = self._normalize_service_name(service or self._infer_service_from_issue(summary, description))
        if not service:
            return None

        service_context = self._repo_service_context(repo_context, service)
        if not endpoint_path or endpoint_path == "/" or endpoint_method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            endpoint_method, endpoint_path = self._extract_endpoint(service_context)
        if not endpoint_path or endpoint_path == "/":
            endpoint_method, endpoint_path = self._extract_endpoint(repo_context)
        if not endpoint_path or endpoint_path == "/":
            return None

        sla_p95_ms = self._extract_int(combined, r"\bp95\b[^\d]{0,20}(\d+)\s*ms", 0)
        if sla_p95_ms <= 0:
            sla_p95_ms = self._extract_repo_slo_int(repo_context, service, "p95")
        error_rate_percent = self._extract_float(
            combined,
            r"\berror\s*rate\b[^\d]{0,20}(\d+(?:\.\d+)?)\s*%",
            0,
        )
        if error_rate_percent <= 0:
            error_rate_percent = self._extract_repo_slo_float(repo_context, service, "error_rate")
        if sla_p95_ms <= 0 or error_rate_percent <= 0:
            return None

        vus = self._extract_int(
            fields.get("vus", "") or combined,
            r"(?:\bvus\b|\bvirtual users\b|\bconcurrent users\b)\s*[:=]?\s*(\d+)",
            2,
        )
        duration = fields.get("duration") or self._extract_duration(combined) or "30s"
        criteria = self._extract_acceptance_criteria(description)
        repo_criteria = self._extract_acceptance_criteria(service_context)
        for item in repo_criteria:
            if item not in criteria:
                criteria.append(item)
        strategy_notes = [
            "Plan recovered from Jira text plus repository docs because the ticket alone did not contain enough runnable detail.",
            f"Repository docs mapped the `{service}` service to `{endpoint_method} {endpoint_path}`.",
            f"Use `{service}` service tags for all thresholds and observability queries.",
        ]
        return TicketPerformancePlan(
            issue_key=str(ticket.metadata.get("key") or fields.get("ticket") or ""),
            summary=summary,
            description=description,
            service=service,
            endpoint_method=endpoint_method,
            endpoint_path=endpoint_path,
            sla_p95_ms=sla_p95_ms,
            error_rate_threshold=error_rate_percent / 100,
            vus=vus,
            duration=duration,
            dataset=fields.get("dataset") or self._extract_dataset(combined) or "users.json",
            test_type=fields.get("type") or self._extract_test_type(combined),
            criteria=criteria[:8],
            strategy_notes=strategy_notes,
        )

    @staticmethod
    def _is_ticket_grounded_plan(plan: TicketPerformancePlan | None) -> bool:
        if plan is None:
            return False
        if not plan.service or plan.service == "service":
            return False
        if not plan.endpoint_path or plan.endpoint_path == "/":
            return False
        if plan.endpoint_method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            return False
        if plan.sla_p95_ms <= 0 or plan.error_rate_threshold <= 0:
            return False
        return True

    def _generate_script(self, plan: TicketPerformancePlan, selected_skill_names: list[str]) -> Path:
        service_dir = self.workspace.project_root / "tests" / plan.service
        service_dir.mkdir(parents=True, exist_ok=True)
        script_path = service_dir / f"{plan.service}.{plan.issue_key.lower()}.test.js"
        script = self._generate_script_via_model(plan, selected_skill_names) or self._generate_script_fallback(plan)
        script_path.write_text(script, encoding="utf-8")
        return script_path

    def _generate_script_via_model(self, plan: TicketPerformancePlan, selected_skill_names: list[str]) -> str:
        k6_bundle = self._skill_bundle_if_selected("k6-best-practices", selected_skill_names)
        if not k6_bundle.skill_text:
            return ""
        strategy_bundle = self._skill_bundle_if_selected("performance-testing-strategy", selected_skill_names)

        system_prompt = (
            "You are generating a production-quality k6 JavaScript script from a Jira ticket. "
            "You must follow the provided skill documents exactly. "
            "Return only raw JavaScript, with no markdown fences and no explanation."
        )
        skill_sections = [
            f"k6 best practices skill:\n{k6_bundle.skill_text}\n\n"
            f"k6 best practices references:\n{self._format_skill_references(k6_bundle)}\n\n"
            f"k6 best practices evals:\n{self._format_skill_evals(k6_bundle)}\n\n"
        ]
        if strategy_bundle.skill_text:
            skill_sections.insert(
                0,
                f"Performance strategy skill:\n{strategy_bundle.skill_text}\n\n"
                f"Performance strategy references:\n{self._format_skill_references(strategy_bundle)}\n\n"
                f"Performance strategy evals:\n{self._format_skill_evals(strategy_bundle)}\n\n",
            )
        user_prompt = (
            f"Ticket key: {plan.issue_key}\n"
            f"Summary: {plan.summary}\n"
            f"Description:\n{plan.description}\n\n"
            f"Structured plan:\n"
            f"- service: {plan.service}\n"
            f"- endpoint: {plan.endpoint_method} {plan.endpoint_path}\n"
            f"- sla_p95_ms: {plan.sla_p95_ms}\n"
            f"- error_rate_threshold: {plan.error_rate_threshold}\n"
            f"- vus: {plan.vus}\n"
            f"- duration: {plan.duration}\n"
            f"- dataset: {plan.dataset}\n"
            f"- test_type: {plan.test_type}\n"
            f"- criteria: {plan.criteria}\n\n"
            + "".join(skill_sections)
            + "Requirements:\n"
            "- Produce a complete runnable JavaScript k6 script.\n"
            "- Use the 5-block pattern from the skill.\n"
            "- Match the Jira ticket exactly; do not invent a different payload or different scenarios.\n"
            "- If the ticket asks for multiple scenarios such as approved/rejected, implement them explicitly.\n"
            "- If the ticket asks for a scenario split like 80/20, encode that in the script logic or scenario design.\n"
            "- Use the request body required by the ticket.\n"
            "- Include checks for the exact status codes and response fields from the ticket.\n"
            "- Include traceparent propagation when the ticket asks for it.\n"
            "- Use service-specific tagged thresholds like http_req_duration{service:<service>}.\n"
            "- Load the dataset via SharedArray when applicable.\n"
            "- Use BASE_URL from __ENV.\n"
            "- Save the HTML summary under results/.\n"
            "- Imports must be at the top of the file.\n"
            "- Output only JavaScript."
        )
        response = self.responder.complete(system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.1)
        cleaned = self._clean_generated_script(response)
        if not cleaned or "export const options" not in cleaned:
            return ""
        if self._evaluate_generated_script(cleaned, plan, k6_bundle):
            return ""
        return cleaned

    def _generate_script_fallback(self, plan: TicketPerformancePlan) -> str:
        dataset_path = self._dataset_relative_path(plan.dataset)
        return f"""import http                        from 'k6/http';
import {{ check, group, sleep }}     from 'k6';
import {{ SharedArray }}             from 'k6/data';
import {{ htmlReport, textSummary }} from '../../lib/summary.js';

// Block 1: Options
export const options = {{
  scenarios: {{
    {plan.service}_{plan.test_type}: {{
      executor: 'constant-vus',
      vus: __ENV.VUS ? Number(__ENV.VUS) : {plan.vus},
      duration: __ENV.DURATION || '{plan.duration}',
      gracefulStop: '30s',
    }},
  }},
  thresholds: {{
    'http_req_failed{{service:{plan.service}}}': ['rate<{plan.error_rate_threshold:.6f}'],
    'http_req_duration{{service:{plan.service}}}': ['p(95)<{plan.sla_p95_ms}'],
    checks: ['rate>0.99'],
  }},
}};

// Block 2: Data
const BASE_URL = __ENV.BASE_URL || '{self._default_base_url(plan.service)}';
const testUsers = new SharedArray('ticket-users', () => JSON.parse(open('{dataset_path}')));

// Block 3: Setup
export function setup() {{
  return {{ baseUrl: BASE_URL }};
}}

// Block 4: Default function
export default function (context) {{
  const user = testUsers[(__VU - 1) % testUsers.length] || {{}};
  const payload = {self._request_payload(plan)};

  group('{plan.issue_key} {plan.summary}', () => {{
    const request = {self._request_expression(plan)};
    check(request, {{
      'status is expected': (r) => r.status >= 200 && r.status < 300,
      'response time within hard ceiling': (r) => r.timings.duration < {max(plan.sla_p95_ms * 2, plan.sla_p95_ms + 250)},
    }});
    sleep(Math.random() + 1);
  }});
}}

// Block 5: Summary
export function handleSummary(data) {{
  return {{
    stdout: textSummary(data, {{ indent: ' ' }}),
    'results/{plan.issue_key.lower()}-{plan.service}-report.html': htmlReport(data),
  }};
}}
"""

    def _enhance_report(
        self,
        report_document: SearchDocument,
        plan: TicketPerformancePlan,
        run_result: "K6RunResult",
        grafana_document: SearchDocument | None,
        selected_skill_names: list[str],
    ) -> SearchDocument:
        metrics = _k6_metric_summary(run_result)
        analysis_bundle = self._skill_bundle_if_selected("performance-report-analysis", selected_skill_names)
        modeled_analysis = self._generate_analysis_via_model(plan, run_result, analysis_bundle, grafana_document)
        technical_section: list[str] = []
        if "performance-testing-strategy" in selected_skill_names:
            technical_section.extend(
                [
                    "## Ticket Strategy",
                    "",
                    f"- Jira ticket: `{plan.issue_key}`",
                    f"- Service under test: `{plan.service}`",
                    f"- Endpoint: `{plan.endpoint_method} {plan.endpoint_path}`",
                    f"- Dataset: `{plan.dataset}`",
                    *[f"- {note}" for note in plan.strategy_notes],
                ]
            )
            if plan.criteria:
                technical_section.extend([f"- Acceptance criterion: {criterion}" for criterion in plan.criteria])
            technical_section.extend([""])
        technical_section.extend(
            [
                "## Script Validation",
                "",
                "- `k6-best-practices` applied: 5-block structure, thresholds as the real gate, SharedArray for ticket data, and think time in the VU flow.",
                f"- Generated script: `{self._workflow_script_path(Path(report_document.metadata.get('script_path', '')) or Path()) if report_document.metadata.get('script_path') else self._workflow_script_path(Path(self._generate_script_path_from_report(plan)))}`",
                "",
                "## Technical Report",
                "",
                f"- SLA check: p95 target < {plan.sla_p95_ms} ms; actual p95 = {metrics.get('p95', 'n/a')}.",
                f"- Error-rate check: target < {plan.error_rate_threshold * 100:.2f}%; actual failure rate = {metrics.get('failure_rate', 'n/a')}.",
                f"- Acceptance checks: pass rate = {metrics.get('check_rate', 'n/a')}.",
                f"- Throughput/volume: HTTP requests = {metrics.get('request_count', 'n/a')}.",
                f"- Severity: {self._severity_label(metrics, plan)}.",
                "",
                "## Business Report",
                "",
                f"- Outcome: {self._business_outcome(metrics, plan)}",
                f"- Release risk: {self._business_risk(metrics, plan)}.",
                f"- Next decision: {self._next_decision(metrics, plan)}",
                "",
            ]
        )
        evidence_gaps = self._acceptance_evidence_gaps(plan, metrics, run_result.summary_path)
        if evidence_gaps:
            technical_section.extend(
                [
                    "## Acceptance Gaps",
                    "",
                    *[f"- {item}" for item in evidence_gaps],
                    "",
                ]
            )
        baseline_note = self._baseline_quality_note(report_document.content)
        if baseline_note:
            technical_section.extend(
                [
                    "## Baseline Quality",
                    "",
                    f"- {baseline_note}",
                    "",
                ]
            )
        if grafana_document is not None:
            technical_section.extend(
                [
                    "## Grafana Evidence",
                    "",
                    f"- Dashboard: {grafana_document.url}",
                    "- Panel image capture should be attached here when the Grafana image endpoint is configured.",
                    "",
                ]
            )
        content = report_document.content.rstrip() + "\n\n" + "\n".join(technical_section)
        if modeled_analysis:
            content += "\n\n" + modeled_analysis.strip() + "\n"
        Path(report_document.url).write_text(content + "\n", encoding="utf-8")
        report_document.content = content + "\n"
        return report_document

    def _generate_analysis_via_model(
        self,
        plan: TicketPerformancePlan,
        run_result: "K6RunResult",
        bundle: SkillBundle,
        grafana_document: SearchDocument | None,
    ) -> str:
        if not bundle.skill_text:
            return ""
        try:
            summary_payload = json.loads(run_result.summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            summary_payload = {}
        response = self.responder.complete(
            system_prompt=(
                "You are producing a technical and business performance analysis from a completed k6 run. "
                "Use the supplied skill, references, and evals as mandatory guidance. "
                "Return markdown only."
            ),
            user_prompt=(
                f"Ticket key: {plan.issue_key}\n"
                f"Service: {plan.service}\n"
                f"Endpoint: {plan.endpoint_method} {plan.endpoint_path}\n"
                f"SLA p95: {plan.sla_p95_ms} ms\n"
                f"Error-rate threshold: {plan.error_rate_threshold}\n"
                f"Grafana dashboard: {grafana_document.url if grafana_document else 'n/a'}\n\n"
                f"k6 summary JSON:\n{json.dumps(summary_payload, indent=2)}\n\n"
                f"Skill:\n{bundle.skill_text}\n\n"
                f"References:\n{self._format_skill_references(bundle)}\n\n"
                f"Evals:\n{self._format_skill_evals(bundle)}\n\n"
                "Produce markdown with two sections: "
                "`## Skill-Driven Technical Analysis` and `## Skill-Driven Business Analysis`. "
                "Use concrete numbers from the summary when present."
            ),
            temperature=0.1,
        )
        return response.strip()

    def _create_plan_document(
        self,
        plan: TicketPerformancePlan,
        selected_skills: list[ProjectSkill],
        decision: WorkflowDecision,
    ) -> SearchDocument:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        run_dir = self.workspace.results_root / f"{timestamp}_bot_{plan.service.lower()}"
        run_dir.mkdir(parents=True, exist_ok=True)
        plan_path = run_dir / f"{plan.issue_key.lower()}-{plan.service}-plan.md"
        lines = [
            f"# Jira Performance Plan: {plan.issue_key}",
            "",
            "## Workflow Decision",
            "",
            f"- Execution mode: `{decision.execution_mode}`",
            f"- Skills: {', '.join(skill.relative_path for skill in selected_skills) if selected_skills else 'none'}",
            *([f"- Rationale: {item}" for item in decision.rationale] or []),
            "",
            "## Planned Test Shape",
            "",
            f"- Service: `{plan.service}`",
            f"- Endpoint: `{plan.endpoint_method} {plan.endpoint_path}`",
            f"- SLA p95 target: `{plan.sla_p95_ms} ms`",
            f"- Error-rate threshold: `{plan.error_rate_threshold * 100:.2f}%`",
            f"- VUs: `{plan.vus}`",
            f"- Duration: `{plan.duration}`",
            f"- Dataset: `{plan.dataset}`",
            f"- Test type: `{plan.test_type}`",
            "",
            "## Strategy Notes",
            "",
            *([f"- {item}" for item in plan.strategy_notes] or ["- None"]),
        ]
        if plan.criteria:
            lines.extend(["", "## Acceptance Criteria", "", *[f"- {item}" for item in plan.criteria]])
        content = "\n".join(lines).rstrip() + "\n"
        plan_path.write_text(content, encoding="utf-8")
        return SearchDocument(
            source_type="k6",
            title=f"performance plan for {plan.issue_key}",
            url=str(plan_path),
            content=content,
            metadata={
                "issue_key": plan.issue_key,
                "service": plan.service,
                "workflow_mode": decision.execution_mode,
                "plan_path": str(plan_path),
            },
        )

    @staticmethod
    def _plan_preview(content: str, max_lines: int = 8) -> str:
        lines = [line for line in (content or "").splitlines() if line.strip()]
        return "\n".join(lines[:max_lines])

    def _jira_comment_body(
        self,
        plan: TicketPerformancePlan,
        report_document: SearchDocument,
        grafana_document: SearchDocument | None,
        selected_skills: list[ProjectSkill],
        decision: WorkflowDecision,
        metrics: dict[str, str] | None = None,
        summary_path: Path | None = None,
    ) -> str:
        metrics = metrics or {}
        lines = [
            f"Performance workflow completed for {plan.issue_key}.",
            "",
            "Executive summary:",
            f"- Service: {plan.service}",
            f"- Endpoint: {plan.endpoint_method} {plan.endpoint_path}",
            f"- Test type: {plan.test_type}",
            f"- Workflow mode: {decision.execution_mode}",
            f"- Output: {report_document.url}",
            f"- Latency SLO: {self._latency_status(metrics, plan)} (p95 {self._format_latency_value(metrics.get('p95'))} vs target < {plan.sla_p95_ms} ms)",
            f"- HTTP failures: {self._format_percentage(metrics.get('failure_rate'))} (target < {plan.error_rate_threshold * 100:.2f}%)",
            f"- Acceptance checks: {self._format_percentage(metrics.get('check_rate'))} pass",
            f"- Outcome: {self._business_outcome(metrics, plan)}",
            f"- Next decision: {self._next_decision(metrics, plan)}",
        ]
        if grafana_document is not None:
            lines.append(f"- Grafana: {grafana_document.url}")
        evidence_gaps = self._acceptance_evidence_gaps(plan, metrics, summary_path) if summary_path is not None else []
        if evidence_gaps:
            lines.extend(["", "Acceptance gaps:"])
            lines.extend(f"- {item}" for item in evidence_gaps)
        if decision.rationale:
            lines.extend(["", "Decision rationale:"])
            lines.extend(f"- {item}" for item in decision.rationale)
        lines.extend(
            [
                "",
                "Workflow trace:",
            ]
        )
        skill_trace = {
            "performance-testing-strategy": "Strategy skill applied from the Jira ticket requirements.",
            "k6-best-practices": "k6 best practices skill used to generate the runnable script.",
            "performance-report-analysis": "Performance report analysis skill used to produce the final report.",
        }
        for skill in selected_skills:
            trace = skill_trace.get(skill.name)
            if trace:
                lines.append(f"- {trace}")
        return "\n".join(lines)

    def _decide_ticket_workflow(
        self,
        ticket: SearchDocument,
        fields: dict[str, str],
    ) -> WorkflowDecision | None:
        summary = ticket.title.split(": ", 1)[1] if ": " in ticket.title else ticket.title
        payload = self.responder.call_function(
            system_prompt=(
                "You are deciding how to execute a Jira-driven performance workflow. "
                "Choose the exact ordered project skills and whether this ticket should stop at planning or continue to execution."
            ),
            user_prompt=(
                f"Ticket key: {ticket.metadata.get('key', '')}\n"
                f"Summary: {summary}\n"
                f"Description:\n{ticket.content}\n\n"
                f"User overrides: {fields}\n\n"
                "Available skills:\n"
                "- performance-testing-strategy: use when the ticket needs test planning, workload modeling, SLAs, datasets, traffic mix, baseline sizing, or deciding what kind of performance test to run.\n"
                "- k6-best-practices: use when the ticket needs a runnable k6 script, concrete endpoint calls, thresholds, checks, scenarios, datasets, or execution guidance.\n"
                "- performance-report-analysis: use when the ticket needs report writing, baseline comparison, business or executive summary, result interpretation, stakeholder communication, or post-run analysis.\n\n"
                "Rules:\n"
                "- Return 1 to 3 skills.\n"
                "- Preserve execution order.\n"
                "- execution_mode must be either plan_only or plan_then_run.\n"
                "- Use plan_only when the ticket is primarily strategy, estimation, planning, workload sizing, or requirements definition and does not yet contain enough concrete execution detail.\n"
                "- Use plan_then_run when the ticket is specific enough to generate and execute a k6 script.\n"
                "- Include performance-testing-strategy before k6-best-practices when the ticket first needs planning.\n"
                "- Include performance-report-analysis after k6-best-practices when the ticket explicitly asks for analysis, comparison, or executive/business reporting.\n"
                "- If the ticket is about generating or running a k6 workflow, include k6-best-practices.\n"
                "- Use only these exact skill names.\n"
            ),
            function_name="decide_ticket_workflow",
            function_description="Choose the execution mode and exact ordered project skills required for this Jira performance workflow.",
            parameters=self._ticket_workflow_decision_function_schema(),
            temperature=0.1,
        )
        if not isinstance(payload, dict):
            return self._fallback_ticket_workflow_decision(ticket, fields)
        ordered_skills = self._normalize_selected_skill_names(payload.get("ordered_skills"))
        execution_mode = str(payload.get("execution_mode") or "").strip()
        rationale = [str(item) for item in (payload.get("rationale") or []) if str(item).strip()]
        if execution_mode not in {"plan_only", "plan_then_run"} or not ordered_skills:
            return self._fallback_ticket_workflow_decision(ticket, fields)
        return WorkflowDecision(
            ordered_skills=ordered_skills,
            execution_mode=execution_mode,
            rationale=rationale[:6],
        )

    def _fallback_ticket_workflow_decision(
        self,
        ticket: SearchDocument,
        fields: dict[str, str],
    ) -> WorkflowDecision | None:
        """Choose a safe deterministic workflow when model tool-calling is unavailable."""
        summary = ticket.title.split(": ", 1)[1] if ": " in ticket.title else ticket.title
        combined = " ".join(
            [
                summary,
                ticket.content,
                " ".join(f"{key} {value}" for key, value in fields.items()),
            ]
        ).lower()
        if not combined.strip():
            return None

        planning_terms = (
            "strategy",
            "planning",
            "plan",
            "estimate",
            "estimation",
            "workload",
            "sizing",
            "traffic",
            "sla",
            "baseline",
            "requirements",
        )
        execution_terms = (
            "k6",
            "load test",
            "stress test",
            "soak test",
            "performance test",
            "run",
            "execute",
            "script",
            "endpoint",
            "api/",
            "post ",
            "get ",
            "put ",
            "delete ",
            "vus",
            "duration",
        )
        report_terms = (
            "analysis",
            "analyze",
            "compare",
            "comparison",
            "report",
            "executive",
            "business summary",
            "stakeholder",
        )

        has_planning = any(term in combined for term in planning_terms)
        has_execution = any(term in combined for term in execution_terms)
        has_report = any(term in combined for term in report_terms)
        has_concrete_endpoint = bool(
            re.search(r"\b(?:GET|POST|PUT|PATCH|DELETE)\s+/\S+", ticket.content, re.IGNORECASE)
            or re.search(r"\bendpoint\s*:\s*\S+", ticket.content, re.IGNORECASE)
        )
        has_runtime_shape = bool(
            re.search(r"\bvus?\s*[:=]?\s*\d+", ticket.content, re.IGNORECASE)
            or re.search(r"\bduration\s*[:=]?\s*\d+\s*(?:s|m|h|sec|secs|seconds|minutes?)\b", ticket.content, re.IGNORECASE)
        )
        recovered_plan = self._build_plan_from_ticket_text(ticket, fields) or self._build_plan_from_ticket_and_repo_docs(ticket, fields)
        recovered_endpoint = bool(
            recovered_plan
            and recovered_plan.endpoint_method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
            and recovered_plan.endpoint_path
            and recovered_plan.endpoint_path != "/"
        )

        if not (has_planning or has_execution or has_report or has_concrete_endpoint or has_runtime_shape or recovered_endpoint):
            return None

        ordered_skills: list[str] = []
        if has_planning or has_concrete_endpoint or has_runtime_shape or recovered_endpoint:
            ordered_skills.append("performance-testing-strategy")
        if has_execution or has_concrete_endpoint or recovered_endpoint:
            ordered_skills.append("k6-best-practices")
        if has_report:
            ordered_skills.append("performance-report-analysis")
        if not ordered_skills:
            ordered_skills.append("performance-testing-strategy")

        execution_mode = "plan_then_run" if ("k6-best-practices" in ordered_skills and (has_concrete_endpoint or recovered_endpoint)) else "plan_only"
        LOGGER.info(
            "Workflow decision fallback used: issue=%s mode=%s skills=%s",
            ticket.metadata.get("key", ""),
            execution_mode,
            ",".join(ordered_skills),
        )
        return WorkflowDecision(
            ordered_skills=ordered_skills,
            execution_mode=execution_mode,
            rationale=[
                "OpenAI workflow decision was unavailable or invalid, so deterministic ticket keyword rules selected the workflow.",
            ],
        )

    @staticmethod
    def _normalize_selected_skill_names(selected: Any) -> list[str]:
        allowed = {
            "performance-testing-strategy",
            "k6-best-practices",
            "performance-report-analysis",
        }
        if not isinstance(selected, list):
            return []
        normalized: list[str] = []
        for item in selected:
            name = str(item or "").strip()
            if name in allowed and name not in normalized:
                normalized.append(name)
        return normalized

    def _skill_bundle_if_selected(self, skill_name: str, selected_skill_names: list[str]) -> SkillBundle:
        if skill_name not in selected_skill_names:
            return SkillBundle(name=skill_name, skill_text="", reference_texts={}, evals_payload={})
        return self._load_skill_bundle(skill_name)

    @staticmethod
    def _ticket_workflow_decision_function_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "execution_mode": {
                    "type": "string",
                    "enum": ["plan_only", "plan_then_run"],
                },
                "ordered_skills": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "performance-testing-strategy",
                            "k6-best-practices",
                            "performance-report-analysis",
                        ],
                    },
                    "minItems": 1,
                    "maxItems": 3,
                },
                "rationale": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["execution_mode", "ordered_skills"],
            "additionalProperties": False,
        }

    @staticmethod
    def _ticket_plan_function_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "endpoint_method": {"type": "string"},
                "endpoint_path": {"type": "string"},
                "sla_p95_ms": {"type": "integer"},
                "error_rate_percent": {"type": "number"},
                "vus": {"type": "integer"},
                "duration": {"type": "string"},
                "dataset": {"type": "string"},
                "test_type": {"type": "string"},
                "criteria": {"type": "array", "items": {"type": "string"}},
                "strategy_notes": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "service",
                "endpoint_method",
                "endpoint_path",
                "sla_p95_ms",
                "error_rate_percent",
                "vus",
                "duration",
                "dataset",
                "test_type",
                "criteria",
                "strategy_notes",
            ],
            "additionalProperties": False,
        }

    def _dataset_relative_path(self, dataset: str) -> str:
        candidate = Path(dataset)
        if candidate.parts[:1] == ("data",):
            return "../../" + str(candidate).replace("\\", "/")
        return "../../data/" + candidate.name

    @staticmethod
    def _default_base_url(service: str) -> str:
        defaults = {
            "auth": "http://127.0.0.1:3001",
            "products": "http://127.0.0.1:3002",
            "cart": "http://127.0.0.1:3003",
            "orders": "http://127.0.0.1:3004",
            "payments": "http://127.0.0.1:3005",
        }
        return defaults.get(service, "http://127.0.0.1:3001")

    def _load_repo_docs_context(self) -> str:
        roots = [self.workspace.project_root, self.workspace.project_root.parent]
        candidate_paths: list[Path] = []
        seen: set[Path] = set()
        preferred_suffixes = {
            "website/README.md",
            "website/README.es.md",
            "website/docs/README.md",
            "website/docs/architecture/ARCHITECTURE.md",
            "website/docs/getting-started/QUICK_START.md",
            "website/observability/README.md",
        }

        def add_candidate(path: Path) -> None:
            resolved = path.resolve()
            if resolved in seen or not resolved.exists() or resolved.suffix.lower() != ".md":
                return
            seen.add(resolved)
            candidate_paths.append(resolved)

        for root in roots:
            for suffix in preferred_suffixes:
                add_candidate(root / suffix)
            website_root = (root / "website").resolve()
            if not website_root.exists():
                continue
            for path in website_root.rglob("*.md"):
                try:
                    relative = path.resolve().relative_to(website_root).as_posix().lower()
                except ValueError:
                    relative = path.name.lower()
                if any(
                    token in relative
                    for token in (
                        "readme",
                        "architecture",
                        "quick_start",
                        "quick-start",
                        "installation",
                        "troubleshooting",
                        "observability",
                    )
                ):
                    add_candidate(path)
        parts: list[str] = []
        for path in candidate_paths:
            if not path.exists():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore").strip()
            except OSError:
                continue
            if text:
                try:
                    label = path.relative_to(self.workspace.project_root).as_posix()
                except ValueError:
                    try:
                        label = path.relative_to(self.workspace.project_root.parent).as_posix()
                    except ValueError:
                        label = path.name
                parts.append(f"[{label}]\n{text}")
        return "\n\n".join(parts)

    @staticmethod
    def _normalize_service_name(service: str) -> str:
        normalized = (service or "").strip().lower()
        aliases = {
            "payments-service": "payments",
            "payment-service": "payments",
            "payment": "payments",
            "orders-service": "orders",
            "order-service": "orders",
            "order": "orders",
            "cart-service": "cart",
            "products-service": "products",
            "product-service": "products",
            "users-api": "auth",
            "users-service": "auth",
            "user-service": "auth",
            "users": "auth",
        }
        return aliases.get(normalized, normalized)

    def _infer_service_from_issue(self, summary: str, description: str) -> str:
        lowered = f"{summary}\n{description}".lower()
        service_targets = {
            "users-api": "auth",
            "users-service": "auth",
            "auth": "auth",
            "products-service": "products",
            "products": "products",
            "cart-service": "cart",
            "cart": "cart",
            "orders-service": "orders",
            "orders": "orders",
            "payments-service": "payments",
            "payments": "payments",
        }
        for token, service in service_targets.items():
            if token in lowered:
                return service
        return ""

    def _repo_service_context(self, repo_context: str, service: str) -> str:
        alias_map = {
            "auth": ("users-api", "users-service", "auth"),
            "products": ("products-service", "products"),
            "cart": ("cart-service", "cart"),
            "orders": ("orders-service", "orders"),
            "payments": ("payments-service", "payments"),
        }
        lines = repo_context.splitlines()
        selected: list[str] = []
        for line in lines:
            lowered = line.lower()
            if any(alias in lowered for alias in alias_map.get(service, ())):
                selected.append(line)
        if selected:
            return "\n".join(selected)

        service_patterns = {
            "auth": r"localhost:3001|/api/auth|users-api|users-service",
            "products": r"localhost:3002|/api/products|products-service",
            "cart": r"localhost:3003|/api/cart|cart-service",
            "orders": r"localhost:3004|/api/orders|orders-service",
            "payments": r"localhost:3005|/api/payments|payments-service",
        }
        pattern = service_patterns.get(service, "")
        if pattern:
            for line in lines:
                if re.search(pattern, line, re.IGNORECASE):
                    selected.append(line)
        return "\n".join(selected)

    def _extract_repo_slo_int(self, repo_context: str, service: str, field_name: str) -> int:
        if field_name != "p95":
            return 0
        service_context = self._repo_service_context(repo_context, service)
        match = re.search(r"<\s*(\d+)\s*ms", service_context, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except (TypeError, ValueError):
                return 0
        service_aliases = {
            "auth": ("users-api", "users-service"),
            "products": ("products-service",),
            "cart": ("cart-service",),
            "orders": ("orders-service",),
            "payments": ("payments-service",),
        }
        aliases = service_aliases.get(service, ())
        lines = [line.strip() for line in repo_context.splitlines()]
        for index, line in enumerate(lines):
            lowered = line.lower()
            if not any(alias in lowered for alias in aliases):
                continue
            for candidate in lines[index + 1 : index + 8]:
                match = re.search(r"<\s*(\d+)\s*ms", candidate, re.IGNORECASE)
                if match:
                    try:
                        return int(match.group(1))
                    except (TypeError, ValueError):
                        return 0
        return 0

    def _extract_repo_slo_float(self, repo_context: str, service: str, field_name: str) -> float:
        if field_name != "error_rate":
            return 0
        service_context = self._repo_service_context(repo_context, service)
        match = re.search(r"<\s*(\d+(?:\.\d+)?)\s*%", service_context, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except (TypeError, ValueError):
                return 0
        service_aliases = {
            "auth": ("users-api", "users-service"),
            "products": ("products-service",),
            "cart": ("cart-service",),
            "orders": ("orders-service",),
            "payments": ("payments-service",),
        }
        aliases = service_aliases.get(service, ())
        lines = [line.strip() for line in repo_context.splitlines()]
        for index, line in enumerate(lines):
            lowered = line.lower()
            if not any(alias in lowered for alias in aliases):
                continue
            for candidate in lines[index + 1 : index + 8]:
                match = re.search(r"<\s*(\d+(?:\.\d+)?)\s*%", candidate, re.IGNORECASE)
                if match:
                    try:
                        return float(match.group(1))
                    except (TypeError, ValueError):
                        return 0
        return 0

    def _extract_service_scoped_slo_int(self, text: str, service: str, field_name: str) -> int:
        if field_name != "p95":
            return 0
        aliases = self._service_aliases(service)
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        matched_ranges: list[tuple[int, int]] = []
        for index, line in enumerate(lines):
            lowered = line.lower()
            if not any(alias in lowered for alias in aliases):
                continue
            matched_ranges.append((index, min(index + 8, len(lines))))
            same_line_match = re.search(r"<\s*(\d+)\s*ms", line, re.IGNORECASE)
            if same_line_match:
                try:
                    return int(same_line_match.group(1))
                except (TypeError, ValueError):
                    return 0
            for candidate in lines[index + 1 : index + 8]:
                match = re.search(r"<\s*(\d+)\s*ms", candidate, re.IGNORECASE)
                if match:
                    try:
                        return int(match.group(1))
                    except (TypeError, ValueError):
                        return 0
        for start, end in matched_ranges:
            block = "\n".join(lines[start:end])
            match = re.search(r"<\s*(\d+)\s*ms", block, re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except (TypeError, ValueError):
                    return 0
        return 0

    def _extract_service_scoped_slo_float(self, text: str, service: str, field_name: str) -> float:
        if field_name != "error_rate":
            return 0
        aliases = self._service_aliases(service)
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        matched_ranges: list[tuple[int, int]] = []
        for index, line in enumerate(lines):
            lowered = line.lower()
            if not any(alias in lowered for alias in aliases):
                continue
            matched_ranges.append((index, min(index + 8, len(lines))))
            same_line_match = re.search(r"<\s*(\d+(?:\.\d+)?)\s*%", line, re.IGNORECASE)
            if same_line_match:
                try:
                    return float(same_line_match.group(1))
                except (TypeError, ValueError):
                    return 0
            for candidate in lines[index + 1 : index + 8]:
                match = re.search(r"<\s*(\d+(?:\.\d+)?)\s*%", candidate, re.IGNORECASE)
                if match:
                    try:
                        return float(match.group(1))
                    except (TypeError, ValueError):
                        return 0
        for start, end in matched_ranges:
            block = "\n".join(lines[start:end])
            match = re.search(r"<\s*(\d+(?:\.\d+)?)\s*%", block, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except (TypeError, ValueError):
                    return 0
        return 0

    @staticmethod
    def _service_aliases(service: str) -> tuple[str, ...]:
        alias_map = {
            "auth": ("users-api", "users-service", "auth"),
            "products": ("products-service", "products"),
            "cart": ("cart-service", "cart"),
            "orders": ("orders-service", "orders"),
            "payments": ("payments-service", "payments"),
        }
        return alias_map.get(service, (service,))

    def _load_skill_bundle(self, skill_name: str) -> SkillBundle:
        skill = self.skill_catalog.get(skill_name)
        if skill is None:
            return SkillBundle(name=skill_name, skill_text="", reference_texts={}, evals_payload={})
        reference_texts: dict[str, str] = {}
        references_dir = skill.path / "references"
        if references_dir.exists():
            for ref_file in sorted(references_dir.glob("*.md")):
                reference_texts[ref_file.name] = ref_file.read_text(encoding="utf-8", errors="ignore")
        evals_payload: dict[str, Any] = {}
        evals_file = skill.path / "evals" / "evals.json"
        if evals_file.exists():
            try:
                evals_payload = json.loads(evals_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                evals_payload = {}
        return SkillBundle(
            name=skill_name,
            skill_text=skill.skill_file.read_text(encoding="utf-8", errors="ignore"),
            reference_texts=reference_texts,
            evals_payload=evals_payload,
        )

    @staticmethod
    def _format_skill_references(bundle: SkillBundle, limit_per_file: int = 2200) -> str:
        if not bundle.reference_texts:
            return "None"
        blocks: list[str] = []
        for name, text in bundle.reference_texts.items():
            blocks.append(f"[{name}]\n{text[:limit_per_file]}")
        return "\n\n".join(blocks)

    @staticmethod
    def _format_skill_evals(bundle: SkillBundle, max_cases: int = 4) -> str:
        evals = bundle.evals_payload.get("evals", []) if isinstance(bundle.evals_payload, dict) else []
        if not isinstance(evals, list) or not evals:
            return "None"
        rendered: list[str] = []
        for case in evals[:max_cases]:
            if not isinstance(case, dict):
                continue
            assertions = case.get("assertions", [])
            assertion_lines = []
            if isinstance(assertions, list):
                for item in assertions[:8]:
                    if isinstance(item, dict):
                        assertion_lines.append(f"- {item.get('name')}: {item.get('description')}")
            rendered.append(
                "\n".join(
                    [
                        f"Case: {case.get('name')}",
                        f"Prompt: {case.get('prompt')}",
                        f"Expected: {case.get('expected_output')}",
                        "Assertions:",
                        *assertion_lines,
                    ]
                )
            )
        return "\n\n".join(rendered) if rendered else "None"

    def _evaluate_generated_script(
        self,
        script: str,
        plan: TicketPerformancePlan,
        bundle: SkillBundle,
    ) -> list[str]:
        issues: list[str] = []
        lowered = script.lower()
        evals = bundle.evals_payload.get("evals", []) if isinstance(bundle.evals_payload, dict) else []
        if "SharedArray".lower() not in lowered:
            issues.append("missing SharedArray")
        if "sleep(" not in lowered:
            issues.append("missing sleep")
        if f"http_req_duration{{service:{plan.service}}}".lower() not in lowered:
            issues.append("missing service-tagged latency threshold")
        if not isinstance(evals, list):
            return issues
        for case in evals:
            if not isinstance(case, dict):
                continue
            for assertion in case.get("assertions", []):
                if not isinstance(assertion, dict):
                    continue
                name = str(assertion.get("name") or "")
                if name == "uses_5_block_pattern" and "handleSummary" not in script:
                    issues.append("missing 5-block summary")
                if name == "checks_plus_thresholds" and ("check(" not in script or "thresholds" not in script):
                    issues.append("missing checks_plus_thresholds")
                if name == "includes_run_command":
                    continue
        if "approved" in " ".join(plan.criteria).lower() and "approved" not in lowered:
            issues.append("missing approved scenario semantics")
        if "rejected" in " ".join(plan.criteria).lower() and "rejected" not in lowered:
            issues.append("missing rejected scenario semantics")
        return issues

    @staticmethod
    def _clean_generated_script(text: str) -> str:
        cleaned = (text or "").strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:javascript|js)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        return cleaned.strip()

    def _request_payload(self, plan: TicketPerformancePlan) -> str:
        if plan.endpoint_method == "GET":
            return "null"
        if plan.service == "auth":
            return "JSON.stringify({ email: user.email, password: user.password })"
        return "JSON.stringify({ issueKey: __ENV.TICKET_KEY || '" + plan.issue_key + "', userId: user.id || __VU })"

    def _request_expression(self, plan: TicketPerformancePlan) -> str:
        url = "${context.baseUrl}" + plan.endpoint_path
        if plan.endpoint_method == "GET":
            return f"http.get(`{url}`, {{ headers: {{ 'Content-Type': 'application/json' }}, tags: {{ service: '{plan.service}', jira: '{plan.issue_key}' }} }})"
        return (
            f"http.{plan.endpoint_method.lower()}(`{url}`, payload, "
            f"{{ headers: {{ 'Content-Type': 'application/json' }}, tags: {{ service: '{plan.service}', jira: '{plan.issue_key}' }} }})"
        )

    def _severity_label(self, metrics: dict[str, str], plan: TicketPerformancePlan) -> str:
        if self._performance_slo_passed(metrics, plan) and not self._acceptance_checks_passed(metrics):
            return "Medium"
        return "Low" if self._passed(metrics, plan) else "High"

    def _business_risk(self, metrics: dict[str, str], plan: TicketPerformancePlan) -> str:
        if self._performance_slo_passed(metrics, plan) and not self._acceptance_checks_passed(metrics):
            return "Moderate"
        return "Low" if self._passed(metrics, plan) else "Elevated"

    def _business_outcome(self, metrics: dict[str, str], plan: TicketPerformancePlan) -> str:
        if self._passed(metrics, plan):
            return "The service stayed within the target envelope and the acceptance checks passed."
        if self._performance_slo_passed(metrics, plan) and not self._acceptance_checks_passed(metrics):
            return "Performance SLOs passed, but the acceptance checks did not fully pass."
        return "The service needs follow-up before sign-off."

    def _next_decision(self, metrics: dict[str, str], plan: TicketPerformancePlan) -> str:
        if self._passed(metrics, plan):
            return "Ticket can move forward with monitoring."
        if self._performance_slo_passed(metrics, plan) and not self._acceptance_checks_passed(metrics):
            return "Keep the ticket open and triage the failing acceptance checks before release."
        return "Keep the ticket open and triage latency/errors before release."

    def _performance_slo_passed(self, metrics: dict[str, str], plan: TicketPerformancePlan) -> bool:
        p95 = self._float_or_none(metrics.get("p95"))
        failure_rate = self._float_or_none(metrics.get("failure_rate"))
        if p95 is None or p95 > plan.sla_p95_ms:
            return False
        if failure_rate is not None and failure_rate > plan.error_rate_threshold:
            return False
        return True

    def _acceptance_checks_passed(self, metrics: dict[str, str]) -> bool:
        check_rate = self._float_or_none(metrics.get("check_rate"))
        if check_rate is None:
            return False
        return check_rate >= 0.99

    def _passed(self, metrics: dict[str, str], plan: TicketPerformancePlan) -> bool:
        return self._performance_slo_passed(metrics, plan) and self._acceptance_checks_passed(metrics)

    @staticmethod
    def _float_or_none(value: str | None) -> float | None:
        if value in (None, "", "n/a"):
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def _workflow_script_path(self, script_path: Path) -> str:
        try:
            return str(script_path.resolve().relative_to(self.workspace.project_root.resolve())).replace("\\", "/")
        except ValueError:
            return str(script_path)

    @staticmethod
    def _generate_script_path_from_report(plan: TicketPerformancePlan) -> str:
        return f"tests/{plan.service}/{plan.service}.{plan.issue_key.lower()}.test.js"

    def _relative_workspace_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.workspace.project_root.resolve())).replace("\\", "/")
        except ValueError:
            return path.name

    @staticmethod
    def _format_percentage(value: str | None) -> str:
        if value in (None, "", "n/a"):
            return "n/a"
        try:
            return f"{float(value) * 100:.1f}%"
        except ValueError:
            return str(value)

    @staticmethod
    def _format_latency_value(value: str | None) -> str:
        if value in (None, "", "n/a"):
            return "n/a"
        try:
            return f"{float(value):.3f} ms"
        except ValueError:
            return str(value)

    def _latency_status(self, metrics: dict[str, str], plan: TicketPerformancePlan) -> str:
        p95 = self._float_or_none(metrics.get("p95"))
        if p95 is None:
            return "not proven"
        return "passed" if p95 <= plan.sla_p95_ms else "failed"

    def _acceptance_evidence_gaps(
        self,
        plan: TicketPerformancePlan,
        metrics: dict[str, str],
        summary_path: Path,
    ) -> list[str]:
        gaps: list[str] = []
        criteria_text = " ".join(plan.criteria).lower()
        if "80%" in criteria_text or "20%" in criteria_text or "approved" in criteria_text or "rejected" in criteria_text:
            groups = self._load_root_group_checks(summary_path)
            if not any("approved" in name.lower() or "rejected" in name.lower() for name in groups):
                gaps.append("The run does not prove the requested approved/rejected scenario split such as 80/20.")
        if "traceparent" in criteria_text or "tempo" in criteria_text:
            gaps.append("The run does not include evidence that traceparent propagation and Tempo trace visibility were verified.")
        if self._performance_slo_passed(metrics, plan) and not self._acceptance_checks_passed(metrics):
            gaps.append("Performance metrics passed, but one or more acceptance checks still failed.")
        return gaps

    @staticmethod
    def _load_root_group_checks(summary_path: Path) -> list[str]:
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        root_group = payload.get("root_group", {})
        if not isinstance(root_group, dict):
            return []
        groups = root_group.get("groups", {})
        if not isinstance(groups, dict):
            return []
        names: list[str] = []
        for group in groups.values():
            if not isinstance(group, dict):
                continue
            group_name = str(group.get("name") or "").strip()
            if group_name:
                names.append(group_name)
            checks = group.get("checks", {})
            if isinstance(checks, dict):
                names.extend(str(name) for name in checks.keys())
        return names

    @staticmethod
    def _baseline_quality_note(report_content: str) -> str:
        if "Latency p95: current=" not in report_content:
            return ""
        if "baseline=0 delta=n/a" in report_content:
            return "The latest baseline file does not contain meaningful latency values, so the comparison is not decision-grade."
        return ""

    @staticmethod
    def _extract_endpoint(text: str) -> tuple[str, str]:
        method_path = re.search(r"\b(GET|POST|PUT|PATCH|DELETE)\s+((?:https?://[^\s/]+)?/\S*)", text, re.IGNORECASE)
        if method_path:
            method = method_path.group(1).upper()
            path = method_path.group(2).strip()
            if path.startswith("http://") or path.startswith("https://"):
                slash_index = path.find("/", path.find("//") + 2)
                path = path[slash_index:] if slash_index != -1 else "/"
            return method, path
        endpoint_label = re.search(r"\bendpoint\s*:\s*(GET|POST|PUT|PATCH|DELETE)?\s*((?:https?://[^\s/]+)?/\S+)", text, re.IGNORECASE)
        if endpoint_label:
            method = (endpoint_label.group(1) or "GET").upper()
            path = endpoint_label.group(2).strip()
            if path.startswith("http://") or path.startswith("https://"):
                slash_index = path.find("/", path.find("//") + 2)
                path = path[slash_index:] if slash_index != -1 else "/"
            return method, path
        return "GET", "/"

    @staticmethod
    def _infer_service(text: str, endpoint_path: str) -> str:
        lowered = text.lower()
        service_keywords = {
            "payments": ("payments", "/api/payments", "payment", "card declined", "transaction_id"),
            "auth": ("auth", "/api/auth", "login", "token"),
            "products": ("products", "/api/products", "catalog", "inventory"),
            "cart": ("cart", "/api/cart", "basket", "checkout cart"),
            "orders": ("orders", "/api/orders", "order id", "order status"),
        }
        for service, hints in service_keywords.items():
            if any(hint in lowered or hint in endpoint_path.lower() for hint in hints):
                return service
        return ""

    @staticmethod
    def _extract_int(text: str, pattern: str, default: int) -> int:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return default
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _extract_float(text: str, pattern: str, default: float) -> float:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return default
        try:
            return float(match.group(1))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _extract_duration(text: str) -> str | None:
        match = re.search(r"\bduration\s*[:=]?\s*(\d+\s*(?:ms|s|m|h|sec|secs|seconds|minutes?|hours?))\b", text, re.IGNORECASE)
        if match:
            return re.sub(r"\s+", "", match.group(1))
        return None

    @staticmethod
    def _extract_dataset(text: str) -> str | None:
        match = re.search(r"\bdataset\s*[:=]?\s*([A-Za-z0-9_./-]+\.(?:json|csv))\b", text, re.IGNORECASE)
        if match:
            return Path(match.group(1)).name
        return None

    @staticmethod
    def _extract_test_type(text: str) -> str:
        lowered = text.lower()
        if "stress" in lowered:
            return "stress"
        if "soak" in lowered:
            return "soak"
        if "spike" in lowered:
            return "spike"
        return "load"

    @staticmethod
    def _extract_acceptance_criteria(text: str) -> list[str]:
        criteria: list[str] = []
        for raw_line in (text or "").splitlines():
            line = raw_line.strip(" -\t")
            if not line:
                continue
            lowered = line.lower()
            if any(
                token in lowered
                for token in (
                    "approved",
                    "rejected",
                    "transaction_id",
                    "card declined",
                    "traceparent",
                    "tempo",
                    "80%",
                    "20%",
                    "201",
                    "status",
                    "{ service:",
                )
            ):
                criteria.append(line)
        deduped: list[str] = []
        for item in criteria:
            if item not in deduped:
                deduped.append(item)
        return deduped[:8]


class K6TestConnector(BaseConnector):
    """Discover and run local k6 scripts from the configured performance repo."""

    source_type = "k6"
    target_type = "test"

    def __init__(
        self,
        workspace: K6Workspace | None = None,
        grafana_connector: "GrafanaConnector | None" = None,
        skill_catalog: ProjectSkillCatalog | None = None,
    ) -> None:
        super().__init__()
        self.workspace = workspace or K6Workspace()
        self.grafana_connector = grafana_connector
        self.skill_catalog = skill_catalog or ProjectSkillCatalog()

    @property
    def configured(self) -> bool:
        return self.workspace.configured

    @property
    def configuration_message(self) -> str:
        return self.workspace.configuration_message

    def execute(self, request: ActionRequest) -> ActionResult:
        if request.operation == "run":
            return self.run(request)
        return super().execute(request)

    def search(self, query: str, limit: int) -> list[SearchDocument]:
        return self.workspace.search_documents(query, limit)

    def create(self, request: ActionRequest) -> ActionResult:
        return ActionResult(False, "k6 test scripts are discovered locally. Use run k6 test <service>.")

    def read(self, request: ActionRequest) -> ActionResult:
        service = request.identifier or request.fields.get("service") or ""
        script_path = self.workspace.find_test_script(service)
        if script_path is None:
            return ActionResult(False, f"Could not find a k6 script for service '{service}'.")
        document = SearchDocument(
            source_type=self.source_type,
            title=f"k6 test script for {service}",
            url=str(script_path),
            content=script_path.read_text(encoding="utf-8", errors="ignore")[:1500],
            metadata={"service": service, "script_path": str(script_path)},
        )
        return ActionResult(True, f"Loaded k6 test script for {service}.", document=document)

    def update(self, request: ActionRequest) -> ActionResult:
        return ActionResult(False, "Updating k6 test scripts is not supported through the bot.")

    def delete(self, request: ActionRequest) -> ActionResult:
        return ActionResult(False, "Deleting k6 test scripts is not supported through the bot.")

    def run(self, request: ActionRequest) -> ActionResult:
        service = request.identifier or request.fields.get("service") or ""
        if not service:
            return ActionResult(False, "Running k6 requires a service name, for example: run k6 test auth")

        run_result = self.workspace.run_test(service, request.fields)
        status = "passed" if run_result.exit_code == 0 else "failed"
        failure_excerpt = (run_result.stderr or run_result.stdout).strip().replace("\r", " ")
        if failure_excerpt:
            failure_excerpt = failure_excerpt[:400]
        document = SearchDocument(
            source_type=self.source_type,
            title=f"k6 run {status} for {service}",
            url=str(run_result.summary_path),
            content=(run_result.stdout or run_result.stderr or "k6 run completed.")[:1500],
            metadata={
                "service": service,
                "status": status,
                "exit_code": run_result.exit_code,
                "summary_path": str(run_result.summary_path),
                "dashboard_path": str(run_result.dashboard_path),
                "run_dir": str(run_result.run_dir),
            },
        )
        message = (
            f"Ran k6 test for {service}. Exit code={run_result.exit_code}. "
            f"Summary: {run_result.summary_path}. Dashboard: {run_result.dashboard_path}."
        )
        grafana_document = _safe_grafana_lookup(self.grafana_connector, service)
        if grafana_document is not None:
            via = grafana_document.metadata.get("via")
            via_label = f" via {via}" if via else ""
            message += f" Grafana{via_label}: {grafana_document.url}."
        message += self.skill_catalog.format_for_message(self.skill_catalog.for_k6_action("test"))
        message += self.skill_catalog.summarize_for_message(
            "test",
            metrics=_k6_metric_summary(run_result),
        )
        if run_result.exit_code != 0 and failure_excerpt:
            message += f" Output: {failure_excerpt}"
        return ActionResult(run_result.exit_code == 0, message, document=document)


class K6ReportConnector(BaseConnector):
    """Generate or search local markdown reports derived from k6 summary JSON."""

    source_type = "k6"
    target_type = "report"

    def __init__(
        self,
        workspace: K6Workspace | None = None,
        grafana_connector: "GrafanaConnector | None" = None,
        skill_catalog: ProjectSkillCatalog | None = None,
    ) -> None:
        super().__init__()
        self.workspace = workspace or K6Workspace()
        self.grafana_connector = grafana_connector
        self.skill_catalog = skill_catalog or ProjectSkillCatalog()

    @property
    def configured(self) -> bool:
        return self.workspace.configured

    @property
    def configuration_message(self) -> str:
        return self.workspace.configuration_message

    def search(self, query: str, limit: int) -> list[SearchDocument]:
        return self.workspace.search_documents(query, limit)

    def create(self, request: ActionRequest) -> ActionResult:
        service = request.identifier or request.fields.get("service") or ""
        if not service:
            return ActionResult(False, "Creating a k6 report requires a service name.")
        grafana_document = _safe_grafana_lookup(self.grafana_connector, service)
        document = self.workspace.generate_report_with_context(
            service,
            dashboard_url=grafana_document.url if grafana_document else "",
            playbooks=self.skill_catalog.for_k6_action("report"),
            playbook_notes=self.skill_catalog.guidance_for_k6_action("report"),
            workflow_context={
                "jira_issue": request.fields.get("ticket", "") or request.fields.get("jira_issue", ""),
                "dataset": request.fields.get("dataset", ""),
                "test_type": request.fields.get("type", "report"),
            },
        )
        message = f"Generated k6 report for {service}."
        if grafana_document is not None:
            via = grafana_document.metadata.get("via")
            via_label = f" via {via}" if via else ""
            message += f" Grafana{via_label}: {grafana_document.url}."
        preview = _report_preview(document.content)
        if preview:
            message += f"\n\nSlack Report Preview:\n{preview}"
        message += self.skill_catalog.format_for_message(self.skill_catalog.for_k6_action("report"))
        message += self.skill_catalog.summarize_for_message("report")
        return ActionResult(True, message, document=document)

    def read(self, request: ActionRequest) -> ActionResult:
        service = request.identifier or request.fields.get("service") or ""
        report_path = self.workspace.latest_report_for_service(service)
        if report_path is None:
            return ActionResult(False, f"Could not find a k6 report for service '{service}'.")
        document = SearchDocument(
            source_type=self.source_type,
            title=f"Latest k6 report for {service}",
            url=str(report_path),
            content=report_path.read_text(encoding="utf-8", errors="ignore")[:1500],
            metadata={"service": service, "report_path": str(report_path)},
        )
        return ActionResult(True, f"Loaded latest k6 report for {service}.", document=document)

    def update(self, request: ActionRequest) -> ActionResult:
        return ActionResult(False, "Updating k6 reports is not supported through the bot.")

    def delete(self, request: ActionRequest) -> ActionResult:
        return ActionResult(False, "Deleting k6 reports is not supported through the bot.")


class K6WorkflowConnector(BaseConnector):
    """Run a k6 script and immediately generate a markdown report from the summary."""

    source_type = "k6"
    target_type = "workflow"

    def __init__(
        self,
        workspace: K6Workspace | None = None,
        grafana_connector: "GrafanaConnector | None" = None,
        skill_catalog: ProjectSkillCatalog | None = None,
    ) -> None:
        super().__init__()
        self.workspace = workspace or K6Workspace()
        self.grafana_connector = grafana_connector
        self.skill_catalog = skill_catalog or ProjectSkillCatalog()

    @property
    def configured(self) -> bool:
        return self.workspace.configured

    @property
    def configuration_message(self) -> str:
        return self.workspace.configuration_message

    def search(self, query: str, limit: int) -> list[SearchDocument]:
        return self.workspace.search_documents(query, limit)

    def create(self, request: ActionRequest) -> ActionResult:
        service = request.identifier or request.fields.get("service") or ""
        if not service:
            return ActionResult(False, "k6 workflow requires a service name.")

        run_result = self.workspace.run_test(service, request.fields)
        grafana_document = _safe_grafana_lookup(self.grafana_connector, service)
        report_document = self.workspace.generate_report_with_context(
            service,
            summary_path=run_result.summary_path,
            dashboard_url=grafana_document.url if grafana_document else "",
            playbooks=self.skill_catalog.for_k6_action("workflow"),
            playbook_notes=self.skill_catalog.guidance_for_k6_action(
                "workflow",
                metrics=_k6_metric_summary(run_result),
            ),
            workflow_context={
                "jira_issue": request.fields.get("ticket", "") or request.fields.get("jira_issue", ""),
                "dataset": request.fields.get("dataset", ""),
                "test_type": request.fields.get("type", "load"),
                "script_path": self._workflow_script_path(run_result.script_path),
                "include_workflow_trace": "true",
            },
        )
        report_document.metadata.update(
            {
                "exit_code": run_result.exit_code,
                "summary_path": str(run_result.summary_path),
                "dashboard_path": str(run_result.dashboard_path),
                "run_dir": str(run_result.run_dir),
            }
        )
        message = (
            f"Completed k6 workflow for {service}. Exit code={run_result.exit_code}. "
            f"Report: {report_document.url}."
        )
        try:
            run_dir_display = str(run_result.run_dir.relative_to(self.workspace.project_root)).replace("\\", "/")
        except ValueError:
            run_dir_display = str(run_result.run_dir)
        if grafana_document is not None:
            via = grafana_document.metadata.get("via")
            via_label = f" via {via}" if via else ""
            message += f" Grafana{via_label}: {grafana_document.url}."
        jira_issue = request.fields.get("ticket", "") or request.fields.get("jira_issue", "")
        if jira_issue:
            message += f" Jira: {jira_issue}."
        message += f" Git: git add {run_dir_display}."
        preview = _report_preview(report_document.content)
        if preview:
            message += f"\n\nSlack Report Preview:\n{preview}"
        message += self.skill_catalog.format_for_message(self.skill_catalog.for_k6_action("workflow"))
        message += self.skill_catalog.summarize_for_message(
            "workflow",
            metrics=_k6_metric_summary(run_result),
        )
        return ActionResult(run_result.exit_code == 0, message, document=report_document)

    def read(self, request: ActionRequest) -> ActionResult:
        return ActionResult(False, "Use create k6 workflow <service> to run the full flow.")

    def update(self, request: ActionRequest) -> ActionResult:
        return ActionResult(False, "Updating k6 workflow records is not supported.")

    def delete(self, request: ActionRequest) -> ActionResult:
        return ActionResult(False, "Deleting k6 workflow artifacts is not supported.")

    def _workflow_script_path(self, script_path: Path) -> str:
        try:
            return str(script_path.resolve().relative_to(self.workspace.project_root.resolve())).replace("\\", "/")
        except ValueError:
            return str(script_path)


class GrafanaConnector(BaseConnector):
    """Search Grafana dashboards and return dashboard links for Slack/CLI replies."""

    source_type = "grafana"
    target_type = "dashboard"

    def __init__(self, mcp_adapter: MCPAdapter | None = None) -> None:
        super().__init__(mcp_adapter=mcp_adapter)

    @property
    def configured(self) -> bool:
        if self.mcp_adapter and self.mcp_adapter.is_enabled(self.source_type):
            return True
        return bool(self._connection_settings()[0])

    def search(self, query: str, limit: int) -> list[SearchDocument]:
        if not self.configured:
            return []
        if self.mcp_adapter:
            delegated = self.mcp_adapter.search(self.source_type, query, limit)
            if delegated is not None:
                return delegated
            # MCP-first design: if a Grafana MCP server is configured but no live handler is
            # attached in this process, we fall back to direct API search using the same
            # MCP-provided connection settings.
        dashboards, _ = self._search_dashboards(query, limit)
        if dashboards:
            return dashboards
        return []

    def create(self, request: ActionRequest) -> ActionResult:
        return ActionResult(False, "Creating Grafana dashboards is not supported through the bot.")

    def read(self, request: ActionRequest) -> ActionResult:
        if self.mcp_adapter:
            delegated = self.mcp_adapter.execute(self.source_type, request)
            if delegated is not None:
                return delegated
        query = request.identifier or request.fields.get("service") or request.fields.get("query") or ""
        if not query:
            return ActionResult(False, "Reading a Grafana dashboard requires a search term or service name.")
        dashboard, error_message = self.lookup_dashboard(query)
        if error_message:
            return ActionResult(False, error_message)
        if dashboard is None:
            return ActionResult(False, f"Could not find a Grafana dashboard for '{query}'.")
        return ActionResult(True, f"Loaded Grafana dashboard for {query}.", document=dashboard)

    def update(self, request: ActionRequest) -> ActionResult:
        return ActionResult(False, "Updating Grafana dashboards is not supported through the bot.")

    def delete(self, request: ActionRequest) -> ActionResult:
        return ActionResult(False, "Deleting Grafana dashboards is not supported through the bot.")

    def lookup_dashboard(self, query: str) -> tuple[SearchDocument | None, str | None]:
        dashboards, error_message = self._search_dashboards(query, 1)
        if error_message:
            return None, error_message
        if dashboards:
            return dashboards[0], None
        return None, None

    def _search_dashboards(self, query: str, limit: int) -> tuple[list[SearchDocument], str | None]:
        base_url, token, via = self._connection_settings()
        if not base_url or not token:
            return [], None

        try:
            response = self.session.get(
                f"{base_url.rstrip('/')}/api/search",
                params={"query": query, "type": "dash-db"},
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code == 404:
                return [], (
                    f"Grafana is configured at {base_url}, but that server did not expose "
                    f"the Grafana search API. Check that GRAFANA_URL points to a real Grafana instance."
                )
            return [], f"Grafana lookup failed against {base_url}: {exc}"
        except requests.RequestException as exc:
            return [], f"Grafana lookup failed against {base_url}: {exc}"

        payload = response.json()
        documents: list[SearchDocument] = []
        for item in payload[:limit]:
            uid = item.get("uid", "")
            url = item.get("url", "")
            full_url = f"{base_url.rstrip('/')}{url}" if url.startswith("/") else url
            documents.append(
                SearchDocument(
                    source_type=self.source_type,
                    title=item.get("title", "Untitled Grafana dashboard"),
                    url=full_url or f"{base_url.rstrip('/')}/d/{uid}",
                    content=item.get("title", ""),
                    metadata={
                        "uid": uid,
                        "folder": item.get("folderTitle"),
                        "type": item.get("type"),
                        "via": via,
                    },
                )
            )
        return documents, None

    def _connection_settings(self) -> tuple[str, str, str]:
        if self.mcp_adapter:
            server = self.mcp_adapter.server_config_for(self.source_type)
            if server is not None:
                mcp_url = (server.url or (server.env or {}).get("GRAFANA_URL", "")).strip()
                mcp_token = ((server.env or {}).get("GRAFANA_SERVICE_ACCOUNT_TOKEN", "")).strip()
                if _is_real_value(mcp_url) and _is_real_value(mcp_token):
                    return mcp_url, mcp_token, "mcp-config"
        direct_url = settings.grafana_url.strip()
        direct_token = settings.grafana_service_account_token.strip()
        if _is_real_value(direct_url) and _is_real_value(direct_token):
            return direct_url, direct_token, "direct"
        return "", "", ""


def build_connectors() -> list[BaseConnector]:
    """Create the default connector set used by the agent."""
    workspace = K6Workspace()
    mcp_adapter = build_mcp_adapter(config_path=settings.mcp_config_path)
    skill_catalog = ProjectSkillCatalog()
    jira_connector = JiraConnector(mcp_adapter=mcp_adapter)
    grafana_connector = GrafanaConnector(mcp_adapter=mcp_adapter)
    return [
        AS400ManualConnector(),
        ConfluenceConnector(mcp_adapter=mcp_adapter),
        jira_connector,
        JiraPerformanceWorkflowConnector(
            jira_connector=jira_connector,
            workspace=workspace,
            grafana_connector=grafana_connector,
            skill_catalog=skill_catalog,
        ),
        K6TestConnector(workspace, grafana_connector=grafana_connector, skill_catalog=skill_catalog),
        K6ReportConnector(workspace, grafana_connector=grafana_connector, skill_catalog=skill_catalog),
        K6WorkflowConnector(workspace, grafana_connector=grafana_connector, skill_catalog=skill_catalog),
        grafana_connector,
    ]

