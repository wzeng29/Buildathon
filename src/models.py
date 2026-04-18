from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SearchDocument:
    """Normalized search result returned by a connector."""

    source_type: str
    title: str
    url: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentAnswer:
    """Final answer package passed back to the CLI or Slack layer."""

    answer: str
    citations: list[SearchDocument]
    reasoning_trace: list[str]


@dataclass
class ActionRequest:
    """Normalized command parsed from a Slack or CLI message."""

    operation: str
    target_system: str
    target_type: str
    identifier: str | None = None
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class ActionResult:
    """Result returned by a Jira or Confluence CRUD operation."""

    success: bool
    message: str
    document: SearchDocument | None = None
    details: dict[str, Any] = field(default_factory=dict)
