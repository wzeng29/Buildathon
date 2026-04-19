from __future__ import annotations

import re
from typing import Any, Iterable

from src.connectors import BaseConnector


def build_llm_tools(connectors: Iterable[BaseConnector]) -> list[dict[str, object]]:
    """Expose each configured connector as explicit LLM-callable tools."""
    tools: list[dict[str, object]] = []
    seen_search_sources: set[str] = set()
    seen_action_targets: set[tuple[str, str]] = set()

    for connector in connectors:
        if not connector.configured:
            continue
        if connector.source_type not in seen_search_sources:
            seen_search_sources.add(connector.source_type)
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": search_tool_name(connector.source_type),
                        "description": f"Search {connector.source_type} for evidence relevant to the user's request.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                            },
                            "required": ["query"],
                            "additionalProperties": False,
                        },
                    },
                }
            )

        target_key = (connector.source_type, connector.target_type)
        if target_key in seen_action_targets:
            continue
        seen_action_targets.add(target_key)
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": action_tool_name(connector.source_type, connector.target_type),
                    "description": (
                        f"Execute {connector.source_type} {connector.target_type}. "
                        "Use this when the user wants the assistant to perform a concrete operation."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "operation": {
                                "type": "string",
                                "enum": ["create", "read", "update", "delete", "run"],
                            },
                            "identifier": {"type": "string"},
                            "fields": {
                                "type": "object",
                                "additionalProperties": {"type": "string"},
                            },
                        },
                        "required": ["operation", "identifier", "fields"],
                        "additionalProperties": False,
                    },
                },
            }
        )

    return tools


def search_tool_name(source_type: str) -> str:
    suffix = _pluralize_target(source_type)
    return f"search_{suffix}"


def action_tool_name(source_type: str, target_type: str) -> str:
    return f"{_operation_prefix(target_type)}_{source_type}_{target_type}"


def source_from_search_tool_name(tool_name: str) -> str | None:
    match = re.fullmatch(r"search_([a-z0-9_]+)", tool_name or "")
    if not match:
        return None
    suffix = match.group(1)
    if suffix.endswith("ies"):
        return suffix[:-3] + "y"
    if suffix.endswith("s"):
        return suffix[:-1]
    return suffix


def target_from_action_tool_name(tool_name: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"(get|create|update|delete|run)_([a-z0-9_]+)_([a-z0-9_]+)", tool_name or "")
    if not match:
        return None
    _, source_type, target_type = match.groups()
    return source_type, target_type


def operation_from_action_tool_name(tool_name: str) -> str | None:
    match = re.fullmatch(r"(get|create|update|delete|run)_([a-z0-9_]+)_([a-z0-9_]+)", tool_name or "")
    if not match:
        return None
    operation = match.group(1)
    if operation == "get":
        return "read"
    return operation


def connector_catalog(connectors: Iterable[BaseConnector]) -> str:
    """Describe available connectors for the LLM router."""
    seen: set[tuple[str, str]] = set()
    entries: list[str] = []
    for connector in connectors:
        key = (connector.source_type, connector.target_type)
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            f"- system={connector.source_type}, target_type={connector.target_type}, configured={connector.configured}"
        )
    return "\n".join(entries)


def normalize_tool_fields(raw_fields: Any) -> dict[str, str]:
    """Normalize arbitrary tool-call fields into a simple string dictionary."""
    if not isinstance(raw_fields, dict):
        raw_fields = {}
    return {
        str(key): str(value)
        for key, value in raw_fields.items()
        if str(key).strip() and value is not None
    }


def _operation_prefix(target_type: str) -> str:
    if target_type in {"workflow", "test"}:
        return "run"
    if target_type in {"ticket", "page", "report", "dashboard"}:
        return "get"
    return "get"


def _pluralize_target(source_type: str) -> str:
    if source_type.endswith("s"):
        return source_type
    if source_type.endswith("y"):
        return source_type[:-1] + "ies"
    return source_type + "s"
