from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.models import SearchDocument

PRONOUN_PATTERN = re.compile(r"\b(it|this|that|its|it's|their|them|they|one)\b", re.IGNORECASE)


@dataclass
class InterpretedRequest:
    """Structured handoff between the lightweight internal agents."""

    original_question: str
    retrieval_question: str
    preferred_sources: list[str] = field(default_factory=list)
    wants_command_answer: bool = False


class RequirementUnderstandingAgent:
    """Infer intent, preferred sources, and a better retrieval query."""

    AS400_HINTS = (
        "as400",
        "ibm i",
        "ibmi",
        "synon",
        "2e",
        "ca 2e",
        "ca2e",
        "command",
        "cl",
        "wrkobj",
        "dspobjd",
        "obj",
        "table",
        "physical file",
        "physical files",
        "direct deposit",
        "library list",
        "jobq",
        "msgq",
    )

    def analyze(
        self,
        question: str,
        last_reference: SearchDocument | None = None,
    ) -> InterpretedRequest:
        lowered = question.lower()
        retrieval_question = self._expand_reference(question, last_reference)
        preferred_sources = self._preferred_sources(lowered, last_reference)
        return InterpretedRequest(
            original_question=question,
            retrieval_question=retrieval_question,
            preferred_sources=preferred_sources,
            wants_command_answer="command" in lowered or "cmd" in lowered,
        )

    def _preferred_sources(
        self,
        lowered_question: str,
        last_reference: SearchDocument | None,
    ) -> list[str]:
        preferred: list[str] = []
        if any(hint in lowered_question for hint in self.AS400_HINTS):
            preferred.append("as400")
        if "jira" in lowered_question or "ticket" in lowered_question or "issue" in lowered_question:
            preferred.append("jira")
        if "confluence" in lowered_question or "page" in lowered_question or "doc" in lowered_question:
            preferred.append("confluence")

        if not preferred and last_reference is not None and PRONOUN_PATTERN.search(lowered_question):
            preferred.append(last_reference.source_type)
        return preferred

    @staticmethod
    def _expand_reference(
        question: str,
        last_reference: SearchDocument | None,
    ) -> str:
        if last_reference is None or not PRONOUN_PATTERN.search(question):
            return question

        if last_reference.source_type == "jira":
            key = str(last_reference.metadata.get("key", "")).strip()
            if key:
                return f"{question} about jira ticket {key} {last_reference.title}"
            return f"{question} about jira ticket {last_reference.title}"

        if last_reference.source_type == "confluence":
            page_id = str(last_reference.metadata.get("id", "")).strip()
            if page_id:
                return f"{question} about confluence page {page_id} {last_reference.title}"
            return f"{question} about confluence page {last_reference.title}"

        if last_reference.source_type == "as400":
            table_name = str(last_reference.metadata.get("table_name", "")).strip()
            table_text = str(last_reference.metadata.get("table_text", "")).strip()
            if table_name:
                return f"{question} about AS400 table {table_name} {table_text}".strip()
            command_candidates = last_reference.metadata.get("command_candidates") or []
            candidate_text = " ".join(str(candidate) for candidate in command_candidates[:4])
            if candidate_text:
                return f"{question} about IBM i AS400 Synon 2E commands {candidate_text}"
            return f"{question} about IBM i AS400 Synon 2E command guidance {last_reference.title}"

        return question


class RetrievalAgent:
    """Select the right data sources for the interpreted request."""

    def select_connectors(
        self,
        connectors: list,
        interpreted: InterpretedRequest,
        connector_hints: dict[str, tuple[str, ...]],
        last_reference: SearchDocument | None = None,
    ) -> list:
        selected = self._select_by_preference(connectors, interpreted.preferred_sources)
        if selected:
            return selected

        lowered = interpreted.retrieval_question.lower()
        hinted = [
            connector
            for connector in connectors
            if connector.configured
            and any(token in lowered for token in connector_hints.get(connector.source_type, ()))
        ]
        if hinted:
            return hinted

        if last_reference is not None:
            remembered = [
                connector
                for connector in connectors
                if connector.configured and connector.source_type == last_reference.source_type
            ]
            if remembered:
                return remembered

        return [connector for connector in connectors if connector.configured]

    @staticmethod
    def _select_by_preference(connectors: list, preferred_sources: list[str]) -> list:
        if not preferred_sources:
            return []
        return [
            connector
            for connector in connectors
            if connector.configured and connector.source_type in preferred_sources
        ]


class AnswerSynthesisAgent:
    """Generate the final user-facing answer from retrieved evidence."""

    def compose(
        self,
        responder,
        question: str,
        evidence_text: str,
        conversation_history: list[dict[str, str]],
    ) -> str:
        return responder.generate(question, evidence_text, conversation_history)
