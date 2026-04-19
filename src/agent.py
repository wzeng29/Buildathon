from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Iterable

from config import settings
from src.connectors import BaseConnector, _fix_mojibake, _strip_html, build_connectors
from src.llm import OpenAIResponder
from src.memory import RedisConversationMemory
from src.models import ActionRequest, AgentAnswer, LLMToolResponse, SearchDocument
from src.command_parser import parse_action_request, parse_contextual_action_request
from src.skills import parse_skill_request
from src.tool_prompts import build_llm_tool_messages
from src.tool_registry import (
    build_llm_tools,
    normalize_tool_fields,
    operation_from_action_tool_name,
    source_from_search_tool_name,
    target_from_action_tool_name,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SOURCE_ROOT = (PROJECT_ROOT / "files").resolve()
LOGGER = logging.getLogger(__name__)
TOOL_CALL_LIMIT = 6


class BuildAgents:
    """Coordinates retrieval and explicit Jira/Confluence CRUD operations."""

    def __init__(
        self,
        connectors: Iterable[BaseConnector] | None = None,
        responder: OpenAIResponder | None = None,
        memory: RedisConversationMemory | None = None,
    ) -> None:
        self.connectors = list(connectors or build_connectors())
        self.responder = responder or OpenAIResponder()
        self.memory = memory or RedisConversationMemory()

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
        if action_request is None:
            action_request = parse_action_request(question)
        if action_request is None:
            action_request = parse_contextual_action_request(question, last_reference)
        if action_request is not None:
            reasoning_trace.append(
                "Resolved explicit action request: "
                f"{action_request.operation} {action_request.target_system} {action_request.target_type}"
            )
        llm_result = self._answer_via_llm_tools(
            question=question,
            conversation_history=conversation_history,
            last_reference=last_reference,
            reasoning_trace=reasoning_trace,
            preferred_action=action_request,
        )
        if llm_result is not None:
            self.memory.append_turn(conversation_id, question, llm_result.answer, llm_result.citations)
            return llm_result
        if action_request is not None:
            reasoning_trace.append(
                "Parsed action: "
                f"{action_request.operation} {action_request.target_system} {action_request.target_type}"
            )
            result = self._execute_action(action_request, reasoning_trace)
            self.memory.append_turn(conversation_id, question, result.answer, result.citations)
            return result

        retrieval_question = self._expand_retrieval_question(question, last_reference)
        if retrieval_question != question:
            reasoning_trace.append("Expanded the follow-up question using the last referenced document")
        selected = [connector for connector in self.connectors if connector.configured]
        reasoning_trace.append(
            "Selected tools: " + ", ".join(connector.source_type for connector in selected)
        )

        evidence = self._collect_evidence(retrieval_question, selected, reasoning_trace)
        ranked = self._rank(retrieval_question, self._deduplicate(evidence))[: settings.max_citations]
        citations = self._filter_relevant_citations(ranked, last_reference)
        reasoning_trace.append(f"Kept {len(ranked)} source-backed documents after ranking")
        if len(citations) != len(ranked):
            reasoning_trace.append(
                f"Filtered citations down to {len(citations)} documents relevant to the current context"
            )

        evidence_text = self._format_evidence(citations)
        answer = self.responder.generate(question, evidence_text, conversation_history)
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

    def _answer_via_llm_tools(
        self,
        question: str,
        conversation_history: list[dict[str, str]],
        last_reference: SearchDocument | None,
        reasoning_trace: list[str],
        preferred_action: ActionRequest | None = None,
    ) -> AgentAnswer | None:
        """Let the LLM plan and execute connector tool calls in a bounded loop."""
        tools = self._llm_tools()
        if not tools:
            return None

        messages = build_llm_tool_messages(
            self.connectors,
            question,
            conversation_history,
            last_reference,
            preferred_action=preferred_action,
        )
        collected_citations: list[SearchDocument] = []

        for iteration in range(TOOL_CALL_LIMIT):
            response = self.responder.respond_with_tools(messages=messages, tools=tools, temperature=0.0)
            if self._has_tool_response(response):
                reasoning_trace.append(
                    f"LLM tool loop iteration {iteration + 1} returned {len(response.tool_calls)} tool call(s)"
                )
            if not response.tool_calls:
                final_text = (response.content or "").strip()
                if final_text:
                    reasoning_trace.append("LLM finished after tool execution")
                    return AgentAnswer(
                        answer=final_text,
                        citations=self._deduplicate(collected_citations)[: settings.max_citations],
                        reasoning_trace=reasoning_trace,
                    )
                return None

            messages.append(
                {
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": [
                        {
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_call.name,
                                "arguments": json.dumps(tool_call.arguments),
                            },
                        }
                        for tool_call in response.tool_calls
                    ],
                }
            )

            for tool_call in response.tool_calls:
                tool_result, tool_citations = self._execute_llm_tool_call(
                    tool_call.name,
                    tool_call.arguments,
                    reasoning_trace,
                )
                collected_citations.extend(tool_citations)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_result,
                    }
                )

        reasoning_trace.append("LLM tool loop hit the safety iteration limit")
        return None

    def _llm_tools(self) -> list[dict[str, object]]:
        """Expose each connector as explicit LLM-callable tools."""
        return build_llm_tools(self.connectors)

    def _execute_llm_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, object],
        reasoning_trace: list[str],
    ) -> tuple[str, list[SearchDocument]]:
        """Execute one LLM-requested tool call and serialize the result back to the model."""
        search_source = source_from_search_tool_name(tool_name)
        if search_source is not None:
            query = str(arguments.get("query") or "").strip()
            selected = [
                connector
                for connector in self.connectors
                if connector.configured and connector.source_type == search_source
            ]
            if not query or not selected:
                reasoning_trace.append("LLM requested search tool with insufficient arguments")
                return json.dumps({"ok": False, "message": "Missing query or valid source."}), []

            reasoning_trace.append(
                "LLM selected tools: " + ", ".join(connector.source_type for connector in selected)
            )
            evidence = self._collect_evidence(query, selected, reasoning_trace)
            ranked = self._rank(query, self._deduplicate(evidence))[: settings.max_citations]
            reasoning_trace.append(f"LLM search kept {len(ranked)} source-backed documents after ranking")
            return json.dumps(
                {
                    "ok": True,
                    "query": query,
                    "documents": [
                        {
                            "source_type": document.source_type,
                            "title": document.title,
                            "url": document.url,
                            "metadata": document.metadata,
                            "content": document.content[:1500],
                        }
                        for document in ranked
                    ],
                }
            ), ranked

        action_target = target_from_action_tool_name(tool_name)
        if action_target is not None:
            operation = (
                str(arguments.get("operation") or "").strip().lower()
                or str(operation_from_action_tool_name(tool_name) or "").strip().lower()
            )
            identifier = str(arguments.get("identifier") or "").strip() or None
            fields = normalize_tool_fields(arguments.get("fields") or {})
            target_system, target_type = action_target
            request = ActionRequest(
                operation=operation,
                target_system=target_system,
                target_type=target_type,
                identifier=identifier,
                fields=fields,
            )
            reasoning_trace.append(f"LLM selected action tool: {operation} {target_system} {target_type}")
            result = self._execute_action(request, reasoning_trace)
            return json.dumps(
                {
                    "ok": True,
                    "message": result.answer,
                    "citations": [
                        {
                            "source_type": citation.source_type,
                            "title": citation.title,
                            "url": citation.url,
                            "metadata": citation.metadata,
                            "content": citation.content[:1500],
                        }
                        for citation in result.citations
                    ],
                }
            ), result.citations

        reasoning_trace.append(f"LLM requested unknown tool: {tool_name}")
        return json.dumps({"ok": False, "message": f"Unknown tool {tool_name}."}), []

    @staticmethod
    def _has_tool_response(response: LLMToolResponse) -> bool:
        """Return whether the LLM returned any tool calls."""
        return bool(response.tool_calls)

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
    def _expand_retrieval_question(
        question: str,
        last_reference: SearchDocument | None,
    ) -> str:
        """Thin fallback-only follow-up expansion using the last cited document."""
        if last_reference is None or not re.search(r"\b(it|this|that|its|their|them|they|one|table|ticket|page)\b", question, re.IGNORECASE):
            return question

        reference_terms = [
            last_reference.source_type,
            last_reference.title.strip(),
            str(last_reference.metadata.get("key", "")).strip(),
            str(last_reference.metadata.get("id", "")).strip(),
            str(last_reference.metadata.get("table_name", "")).strip(),
            str(last_reference.metadata.get("table_text", "")).strip(),
        ]
        suffix = " ".join(term for term in reference_terms if term)
        if not suffix:
            return question
        return f"{question} about {suffix}".strip()

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
        explicit_table = ""
        for document in documents:
            table_name = str(document.metadata.get("table_name", "")).strip()
            if table_name and table_name.lower() in (question or "").lower():
                explicit_table = table_name.upper()
                break

        if documents and all(
            document.source_type == "as400" and document.metadata.get("source_kind") == "table_catalog"
            for document in documents
        ):
            if explicit_table:
                prioritized = sorted(
                    documents,
                    key=lambda document: (
                        str(document.metadata.get("table_name", "")).upper() == explicit_table,
                        len(document.content),
                    ),
                    reverse=True,
                )
                return prioritized
            return documents

        terms = set(re.findall(r"[a-zA-Z0-9_]+", question.lower()))
        if not terms:
            return documents
        explicit_jira_key_match = re.search(r"\b([A-Z][A-Z0-9_]+-\d+)\b", question or "", re.IGNORECASE)
        explicit_jira_key = explicit_jira_key_match.group(1).upper() if explicit_jira_key_match else ""

        def score(document: SearchDocument) -> tuple[float, int, int]:
            searchable = " ".join(
                [document.title, document.content, str(document.metadata)]
            ).lower()
            overlap = sum(1 for term in terms if term in searchable)
            explicit_key_boost = 0
            if (
                explicit_jira_key
                and document.source_type == "jira"
                and str(document.metadata.get("key", "")).upper() == explicit_jira_key
            ):
                explicit_key_boost = 1
            return (explicit_key_boost, overlap / len(terms), len(document.content))

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
    visible_citations = _visible_citations(result.citations)
    answer = _clean_slack_answer(result.answer, visible_citations)
    citations = [
        f"{index}. [{citation.source_type}] {citation.title} - {citation.url}"
        for index, citation in enumerate(visible_citations, start=1)
    ]
    if not citations:
        return answer
    citation_block = "\n".join(citations)
    return f"{answer}\n\nSources:\n{citation_block}"


def _clean_slack_answer(answer: str, citations: list[SearchDocument]) -> str:
    """Turn raw fallback evidence dumps into a cleaner Slack-facing summary."""
    text = (answer or "").strip()
    if "I found relevant evidence and summarized it below." not in text:
        return text

    task_answer = _task_oriented_answer(citations)
    if task_answer:
        return task_answer

    direct_summary = _primary_citation_summary(citations)
    if direct_summary:
        return direct_summary

    suggestions = _suggest_options_from_citations(citations)
    if suggestions:
        suggestion_lines = "\n".join(f"- {item}" for item in suggestions)
        return (
            "I found a few likely options based on the retrieved docs.\n\n"
            f"{suggestion_lines}\n\n"
            "If you want, I can also narrow this down to the best single command for your exact use case."
        )

    summary_lines: list[str] = []
    for citation in citations[:3]:
        line = f"- [{citation.source_type}] {citation.title}"
        preview = _citation_preview(citation)
        if preview:
            line += f": {preview}"
        summary_lines.append(line)
    if summary_lines:
        return "I found relevant references and shortlisted the most useful ones:\n\n" + "\n".join(summary_lines)
    return text


def _suggest_options_from_citations(citations: list[SearchDocument]) -> list[str]:
    """Extract a few command-like options from citation content for Slack replies."""
    options: list[str] = []
    seen: set[str] = set()
    for citation in citations:
        if citation.source_type == "jira":
            continue
        matches = re.findall(r"\b[A-Z]{3,12}[A-Z0-9_]{0,4}\b", citation.content or "")
        for match in matches:
            if match in seen:
                continue
            seen.add(match)
            options.append(f"`{match}` from {citation.title}")
            if len(options) >= 4:
                return options
    return options


def _task_oriented_answer(citations: list[SearchDocument]) -> str:
    """Turn raw evidence into a short task answer when the source clearly contains command guidance."""
    if not citations:
        return ""

    first = citations[0]
    cleaned = _clean_citation_content(first.content or "")
    plain_preview = str(first.metadata.get("plain_text_preview", "") or "").strip()
    combined = " ".join(part for part in [first.title, plain_preview, cleaned] if part)

    if first.source_type == "jira":
        jira_text = _clean_text_noise(combined)
        lines = jira_text.split(": ", 1)
        title = first.title.strip()
        description = jira_text
        if len(description) > 420:
            description = description[:420].rstrip() + "..."
        return f"{title}\n\n{description}"

    commands = []
    seen: set[str] = set()
    for match in re.findall(r"\b[A-Z]{3,12}[A-Z0-9_]{0,4}\b", combined):
        if match in seen:
            continue
        if not match.startswith(("WRK", "DSP", "SBM", "END", "STR", "CHG", "CPY", "RTV", "CRT", "DLT")):
            continue
        seen.add(match)
        commands.append(match)
        if len(commands) >= 4:
            break

    if not commands:
        return ""

    best = commands[0]
    alternatives = commands[1:3]
    answer = f"最相关的命令是 `{best}`。"
    if alternatives:
        answer += " 备选还有 " + "、".join(f"`{item}`" for item in alternatives) + "。"
    if plain_preview:
        answer += f"\n\n依据: {_clean_text_noise(plain_preview)[:220].rstrip()}..."
    return answer


def _primary_citation_summary(citations: list[SearchDocument]) -> str:
    """Build a generic direct answer from the top citation when fallback dumped raw evidence."""
    if not citations:
        return ""
    first = citations[0]
    title = first.title.strip()
    preview = _citation_preview(first, limit=260)
    key = str(first.metadata.get("key", "")).strip()
    identifier = key or str(first.metadata.get("id", "")).strip()

    header = title
    if identifier and identifier not in title:
        header = f"{identifier} - {title}"
    if preview:
        return f"{header}\n\n{preview}"
    return header


def _citation_preview(citation: SearchDocument, limit: int = 140) -> str:
    """Build a short one-line preview for Slack."""
    preferred_preview = str(citation.metadata.get("plain_text_preview", "") or "").strip()
    content = preferred_preview or _clean_citation_content(citation.content or "")
    content = re.sub(r"\s+", " ", content).strip()
    if not content:
        return ""
    return content[:limit].rstrip() + ("..." if len(content) > limit else "")


def _clean_citation_content(content: str) -> str:
    """Normalize rich source content into readable plain text for Slack/CLI previews."""
    text = (content or "").strip()
    if not text:
        return ""
    if "<" in text and ">" in text:
        text = _strip_html(text)
    return _fix_mojibake(text)


def _clean_text_noise(text: str) -> str:
    """Remove a few common rendering artifacts from downstream answer text."""
    normalized = _fix_mojibake(text or "").replace("??", "").replace("鈩?", "").replace("�", "")
    normalized = re.sub(r"\bwide\s+\d+\b", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


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
