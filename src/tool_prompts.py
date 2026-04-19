from __future__ import annotations

from typing import Iterable

from src.connectors import BaseConnector
from src.models import ActionRequest
from src.models import SearchDocument
from src.tool_registry import connector_catalog


def build_llm_tool_messages(
    connectors: Iterable[BaseConnector],
    question: str,
    conversation_history: list[dict[str, str]],
    last_reference: SearchDocument | None,
    preferred_action: ActionRequest | None = None,
) -> list[dict[str, object]]:
    """Build the conversation used by the LLM tool-calling loop."""
    registry_catalog = connector_catalog(connectors)
    last_reference_text = format_last_reference(last_reference)
    preferred_action_text = format_preferred_action(preferred_action)
    conversation_focus_text = format_conversation_focus(last_reference)
    messages: list[dict[str, object]] = [
        {
            "role": "system",
            "content": (
                "You are an enterprise assistant with access to connector tools. "
                "Decide which tool to call, inspect results, and continue only when needed. "
                "When you have enough information, answer directly and stop calling tools. "
                "Prefer the smallest useful number of tool calls. "
                "If the user asks a follow-up like 'it' or 'that', use the last referenced document to preserve context. "
                "Treat the conversation focus as the default entity for ambiguous follow-up questions unless new evidence clearly overrides it. "
                "If a preferred explicit action is provided, honor it unless the request is clearly just informational."
            ),
        },
        {
            "role": "system",
            "content": (
                f"Available connectors:\n{registry_catalog}\n\n"
                f"Conversation focus:\n{conversation_focus_text}\n\n"
                f"Last referenced document:\n{last_reference_text}\n\n"
                f"Preferred explicit action:\n{preferred_action_text}"
            ),
        },
    ]
    for message in conversation_history:
        if message.get("role") in {"user", "assistant"} and message.get("content"):
            messages.append(
                {
                    "role": message["role"],
                    "content": message["content"],
                }
            )
    messages.append({"role": "user", "content": question})
    return messages


def format_last_reference(last_reference: SearchDocument | None) -> str:
    if last_reference is None:
        return "None"
    return (
        f"source={last_reference.source_type}, title={last_reference.title}, "
        f"url={last_reference.url}, metadata={last_reference.metadata}"
    )


def format_preferred_action(preferred_action: ActionRequest | None) -> str:
    if preferred_action is None:
        return "None"
    return (
        f"operation={preferred_action.operation}, "
        f"target_system={preferred_action.target_system}, "
        f"target_type={preferred_action.target_type}, "
        f"identifier={preferred_action.identifier}, "
        f"fields={preferred_action.fields}"
    )


def format_conversation_focus(last_reference: SearchDocument | None) -> str:
    if last_reference is None:
        return "None"
    if last_reference.source_type == "jira":
        return f"jira ticket {last_reference.metadata.get('key') or last_reference.title}"
    if last_reference.source_type == "confluence":
        return f"confluence page {last_reference.metadata.get('id') or last_reference.title}"
    if last_reference.source_type == "as400":
        return f"as400 table/manual {last_reference.metadata.get('table_name') or last_reference.title}"
    return f"{last_reference.source_type} {last_reference.title}"
