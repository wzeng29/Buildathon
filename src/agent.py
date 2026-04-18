from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from config import settings
from src.command_parser import parse_action_request, parse_contextual_action_request
from src.connectors import BaseConnector, build_connectors
from src.llm import OpenAIResponder
from src.memory import RedisConversationMemory
from src.multi_agent import AnswerSynthesisAgent, RequirementUnderstandingAgent, RetrievalAgent
from src.models import ActionRequest, AgentAnswer, SearchDocument
from src.skills import parse_skill_request

CONNECTOR_HINTS: dict[str, tuple[str, ...]] = {
    "as400": ("as400", "ibm i", "ibmi", "command", "cl", "wrkobj", "dspobjd"),
    "jira": ("jira", "ticket", "story", "bug", "status"),
    "confluence": ("confluence", "doc", "page", "knowledge", "kb"),
    "k6": ("k6", "performance", "load", "stress", "soak", "test", "report"),
    "grafana": ("grafana", "dashboard", "metrics", "latency", "panel"),
}
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SOURCE_ROOT = (PROJECT_ROOT / "files").resolve()


class BuildAgents:
    """Coordinates retrieval and explicit Jira/Confluence CRUD operations."""

    def __init__(
        self,
        connectors: Iterable[BaseConnector] | None = None,
        responder: OpenAIResponder | None = None,
        memory: RedisConversationMemory | None = None,
        understanding_agent: RequirementUnderstandingAgent | None = None,
        retrieval_agent: RetrievalAgent | None = None,
        synthesis_agent: AnswerSynthesisAgent | None = None,
    ) -> None:
        self.connectors = list(connectors or build_connectors())
        self.responder = responder or OpenAIResponder()
        self.memory = memory or RedisConversationMemory()
        self.understanding_agent = understanding_agent or RequirementUnderstandingAgent()
        self.retrieval_agent = retrieval_agent or RetrievalAgent()
        self.synthesis_agent = synthesis_agent or AnswerSynthesisAgent()

    def answer(self, question: str, conversation_id: str | None = None) -> AgentAnswer:
        """Route explicit CRUD commands or answer a source-backed search question."""
        reasoning_trace: list[str] = []
        conversation_history = self.memory.get_history(conversation_id)
        last_reference = self.memory.get_last_citation(conversation_id)
        if conversation_history:
            reasoning_trace.append(
                f"Loaded {len(conversation_history)} prior messages from conversation memory"
            )

        action_request = parse_skill_request(question)
        if action_request is not None:
            reasoning_trace.append(
                "Resolved slash skill: "
                f"{action_request.operation} {action_request.target_system} {action_request.target_type}"
            )
        else:
            action_request = parse_action_request(question)
        if action_request is None:
            action_request = parse_contextual_action_request(question, last_reference)
            if action_request is not None:
                reasoning_trace.append(
                    "Resolved follow-up action against the last referenced document in memory"
                )
        if action_request is not None:
            reasoning_trace.append(
                "Parsed action: "
                f"{action_request.operation} {action_request.target_system} {action_request.target_type}"
            )
            result = self._execute_action(action_request, reasoning_trace)
            self.memory.append_turn(conversation_id, question, result.answer, result.citations)
            return result

        interpreted = self.understanding_agent.analyze(question, last_reference)
        if interpreted.retrieval_question != question:
            reasoning_trace.append("Expanded the follow-up question using the last referenced document")
        if interpreted.preferred_sources:
            reasoning_trace.append(
                "Understanding agent preferred sources: " + ", ".join(interpreted.preferred_sources)
            )
        selected = self.retrieval_agent.select_connectors(
            self.connectors,
            interpreted,
            CONNECTOR_HINTS,
            last_reference,
        )
        reasoning_trace.append(
            "Selected tools: " + ", ".join(connector.source_type for connector in selected)
        )

        evidence = self._collect_evidence(interpreted.retrieval_question, selected, reasoning_trace)
        ranked = self._rank(interpreted.retrieval_question, self._deduplicate(evidence))[: settings.max_citations]
        citations = self._filter_relevant_citations(ranked, last_reference)
        reasoning_trace.append(f"Kept {len(ranked)} source-backed documents after ranking")
        if len(citations) != len(ranked):
            reasoning_trace.append(
                f"Filtered citations down to {len(citations)} documents relevant to the current context"
            )

        evidence_text = self._format_evidence(citations)
        answer = self.synthesis_agent.compose(
            self.responder,
            question,
            evidence_text,
            conversation_history,
        )
        self.memory.append_turn(conversation_id, question, answer, citations)
        return AgentAnswer(answer=answer, citations=citations, reasoning_trace=reasoning_trace)

    def _execute_action(
        self,
        request: ActionRequest,
        reasoning_trace: list[str],
    ) -> AgentAnswer:
        """Run a CRUD action against the matching connector and render a user answer."""
        connector = self._find_connector(request.target_system, request.target_type)
        if connector is None:
            message = f"No connector is available for {request.target_system} {request.target_type}."
            reasoning_trace.append(message)
            return AgentAnswer(answer=message, citations=[], reasoning_trace=reasoning_trace)

        if not connector.configured:
            message = connector.configuration_message
            reasoning_trace.append(message)
            return AgentAnswer(answer=message, citations=[], reasoning_trace=reasoning_trace)

        try:
            result = connector.execute(request)
        except Exception as exc:
            message = f"{connector.source_type.title()} {request.operation} failed: {exc}"
            reasoning_trace.append(message)
            return AgentAnswer(answer=message, citations=[], reasoning_trace=reasoning_trace)

        reasoning_trace.append(result.message)
        citations = [result.document] if result.document else []
        return AgentAnswer(answer=result.message, citations=citations, reasoning_trace=reasoning_trace)

    def _find_connector(self, target_system: str, target_type: str) -> BaseConnector | None:
        """Find the connector responsible for a parsed CRUD action."""
        for connector in self.connectors:
            if connector.source_type == target_system and connector.target_type == target_type:
                return connector
        return None

    def _collect_evidence(
        self,
        question: str,
        connectors: list[BaseConnector],
        reasoning_trace: list[str],
    ) -> list[SearchDocument]:
        """Run all selected connectors and keep a readable execution trace."""
        evidence: list[SearchDocument] = []
        for connector in connectors:
            try:
                results = connector.search(question, settings.max_documents_per_source)
                reasoning_trace.append(
                    f"Retrieved {len(results)} documents from {connector.source_type}"
                )
                evidence.extend(results)
            except Exception as exc:
                reasoning_trace.append(f"{connector.source_type} retrieval failed: {exc}")
        return evidence

    @staticmethod
    def _deduplicate(documents: list[SearchDocument]) -> list[SearchDocument]:
        """Remove repeated documents that resolve to the same backing URL."""
        seen: set[str] = set()
        deduplicated: list[SearchDocument] = []
        for document in documents:
            document_key = f"{document.source_type}:{document.url}"
            if document_key in seen:
                continue
            seen.add(document_key)
            deduplicated.append(document)
        return deduplicated

    @staticmethod
    def _rank(question: str, documents: list[SearchDocument]) -> list[SearchDocument]:
        """Rank by term overlap first, then prefer documents with more content."""
        if documents and all(
            document.source_type == "as400" and document.metadata.get("source_kind") == "table_catalog"
            for document in documents
        ):
            return documents

        terms = set(re.findall(r"[a-zA-Z0-9_]+", question.lower()))
        if not terms:
            return documents

        def score(document: SearchDocument) -> tuple[float, int]:
            searchable = " ".join(
                [document.title, document.content, str(document.metadata)]
            ).lower()
            overlap = sum(1 for term in terms if term in searchable)
            return (overlap / len(terms), len(document.content))

        return sorted(documents, key=score, reverse=True)

    @staticmethod
    def _format_evidence(documents: list[SearchDocument]) -> str:
        """Flatten retrieved documents into the evidence block sent to the LLM."""
        if not documents:
            return ""

        blocks: list[str] = []
        for index, document in enumerate(documents, start=1):
            blocks.append(
                "\n".join(
                    [
                        f"[{index}] Source: {document.source_type}",
                        f"Title: {document.title}",
                        f"URL: {document.url}",
                        f"Metadata: {document.metadata}",
                        f"Content: {document.content[:1500]}",
                    ]
                )
            )
        return "\n\n".join(blocks)

    @staticmethod
    def _filter_relevant_citations(
        documents: list[SearchDocument],
        last_reference: SearchDocument | None,
    ) -> list[SearchDocument]:
        """Prefer citations that match the current remembered ticket/page when available."""
        if not documents:
            return documents
        if last_reference is None:
            return documents

        reference_key = BuildAgents._document_identity(last_reference)
        if reference_key is None:
            return documents

        matching = [
            document
            for document in documents
            if BuildAgents._document_identity(document) == reference_key
        ]
        return matching or documents

    @staticmethod
    def _document_identity(document: SearchDocument) -> tuple[str, str] | None:
        """Return a stable identity for Jira tickets and Confluence pages."""
        if document.source_type == "jira" and document.metadata.get("key"):
            return ("jira", str(document.metadata["key"]))
        if document.source_type == "confluence" and document.metadata.get("id"):
            return ("confluence", str(document.metadata["id"]))
        if document.source_type == "as400" and document.metadata.get("table_name"):
            return ("as400", str(document.metadata["table_name"]))
        return None



def format_slack_response(result: AgentAnswer) -> str:
    """Render the final answer as a Slack-friendly message with citations."""
    citations = [
        f"{index}. [{citation.source_type}] {citation.title} - {citation.url}"
        for index, citation in enumerate(_visible_citations(result.citations), start=1)
    ]
    citation_block = "\n".join(citations) if citations else "No supporting sources found."
    return f"{result.answer}\n\nSources:\n{citation_block}"


def _visible_citations(citations: list[SearchDocument]) -> list[SearchDocument]:
    """Hide local paths outside files/ while keeping web URLs visible."""
    visible: list[SearchDocument] = []
    for citation in citations:
        if _is_visible_citation_url(citation.url):
            visible.append(citation)
    return visible


def _is_visible_citation_url(url: str) -> bool:
    lowered = (url or "").lower()
    if lowered.startswith(("http://", "https://")):
        return True

    local_spec = (url or "").split("#", 1)[0]
    if not local_spec:
        return False

    try:
        local_path = Path(local_spec).resolve()
    except OSError:
        return False

    try:
        local_path.relative_to(ALLOWED_SOURCE_ROOT)
        return True
    except ValueError:
        return False
