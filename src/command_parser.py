from __future__ import annotations

import re

from src.models import ActionRequest, SearchDocument

COMMAND_PATTERN = re.compile(
    r"^\s*(create|read|get|update|edit|delete|remove|close|run)\s+"
    r"(jira|confluence|k6|grafana)\s+"
    r"(ticket|issue|page|test|report|workflow|dashboard)\b",
    re.IGNORECASE,
)
NATURAL_COMMAND_PATTERN = re.compile(
    r"^\s*(create|read|get|update|edit|delete|remove|close|run)\s+"
    r"(?:a|an|the)?\s*"
    r"(ticket|issue|page|test|report|workflow|dashboard)\s+"
    r"(?:in|on|from)?\s*"
    r"(jira|confluence|k6|grafana)\b[:\s-]*",
    re.IGNORECASE,
)
FOLLOW_UP_COMMAND_PATTERN = re.compile(
    r"^\s*(close|read|get|update|edit|delete|remove)\s+"
    r"(?:(?:it|this|that)\b|(?:this|that)\s+(ticket|issue|page)\b)",
    re.IGNORECASE,
)
JIRA_PERF_WORKFLOW_PATTERN = re.compile(
    r"^\s*(?:test|run)\s+(?:jira\s+)?(?:(ticket|issue)\s+)?([A-Z][A-Z0-9_]+-\d+)\b",
    re.IGNORECASE,
)
FIELD_PATTERN = re.compile(r"(\w+)=('([^']*)'|\"([^\"]*)\"|(\S+))")
LABELLED_FIELD_PATTERN = re.compile(
    r"(\w+)\s*:\s*(.*?)(?=\s+\w+\s*:|$)",
    re.IGNORECASE,
)

OPERATION_ALIASES = {
    "close": "close",
    "get": "read",
    "edit": "update",
    "remove": "delete",
    "issue": "ticket",
    "title": "summary",
}


def parse_action_request(text: str) -> ActionRequest | None:
    """Parse explicit CRUD commands from Slack or CLI text.

    Parsing order:

    - Jira workflow shorthand like `test KAN-5`
    - explicit system commands like `read jira ticket KAN-1`
    - natural word-order commands like `create a ticket in jira: ...`
    """
    normalized = text or ""
    return (
        _parse_jira_workflow_shorthand(normalized)
        or _parse_explicit_command(normalized)
        or _parse_natural_command(normalized)
    )


def parse_contextual_action_request(
    text: str,
    last_reference: SearchDocument | None,
) -> ActionRequest | None:
    """Resolve follow-up commands like 'close it' using the last cited document."""
    if last_reference is None:
        return None

    match = FOLLOW_UP_COMMAND_PATTERN.match(text or "")
    if not match:
        return None

    operation = OPERATION_ALIASES.get(match.group(1).lower(), match.group(1).lower())
    remainder = (text or "")[match.end() :].strip()
    fields = _extract_fields(remainder)
    target_system = last_reference.source_type
    target_type = "page" if target_system == "confluence" else "ticket"
    identifier = _identifier_from_reference(last_reference)

    if operation == "close":
        if target_system != "jira":
            return None
        operation = "update"
        fields.setdefault("status", "closed")

    return ActionRequest(
        operation=operation,
        target_system=target_system,
        target_type=target_type,
        identifier=identifier,
        fields=fields,
    )


def _parse_jira_workflow_shorthand(text: str) -> ActionRequest | None:
    """Parse `test jira DEV-42 ...` and `test DEV-42 ...` into Jira workflow actions."""
    match = JIRA_PERF_WORKFLOW_PATTERN.match(text)
    if not match:
        return None
    _, issue_key = match.groups()
    remainder = text[match.end() :].strip()
    return ActionRequest(
        operation="run",
        target_system="jira",
        target_type="workflow",
        identifier=issue_key.upper(),
        fields=_extract_fields(remainder),
    )


def _parse_explicit_command(text: str) -> ActionRequest | None:
    """Parse commands with explicit `<system> <type>` ordering."""
    match = COMMAND_PATTERN.match(text)
    if not match:
        return None
    operation, target_system, target_type = match.groups()
    return _build_action_request(
        operation=operation,
        target_system=target_system,
        target_type=target_type,
        remainder=text[match.end() :].strip(),
    )


def _parse_natural_command(text: str) -> ActionRequest | None:
    """Parse natural word-order commands like `create a ticket in jira`."""
    match = NATURAL_COMMAND_PATTERN.match(text)
    if not match:
        return None
    operation, target_type, target_system = match.groups()
    return _build_action_request(
        operation=operation,
        target_system=target_system,
        target_type=target_type,
        remainder=text[match.end() :].strip(),
    )


def _build_action_request(
    operation: str,
    target_system: str,
    target_type: str,
    remainder: str,
) -> ActionRequest:
    """Build a normalized action request from parsed command parts."""
    normalized_operation = _normalize_alias(operation)
    normalized_target_type = _normalize_alias(target_type)
    fields = _extract_fields(remainder)
    identifier = _extract_identifier(remainder, fields)
    return ActionRequest(
        operation=normalized_operation,
        target_system=target_system.lower(),
        target_type=normalized_target_type.lower(),
        identifier=identifier,
        fields=fields,
    )


def _extract_fields(remainder: str) -> dict[str, str]:
    """Extract `key=value` or `label: value` fields from the command tail."""
    fields: dict[str, str] = {}
    for match in FIELD_PATTERN.finditer(remainder):
        key = match.group(1).lower()
        value = match.group(3) or match.group(4) or match.group(5) or ""
        fields[_normalize_alias(key)] = value.strip()

    if fields:
        return fields

    for match in LABELLED_FIELD_PATTERN.finditer(remainder):
        key = match.group(1).lower().strip()
        value = match.group(2).strip().strip("\"'")
        if value:
            fields[_normalize_alias(key)] = value
    return fields


def _extract_identifier(remainder: str, fields: dict[str, str]) -> str | None:
    """Treat the first non key=value token as the resource identifier."""
    cleaned = FIELD_PATTERN.sub("", remainder).strip()
    if cleaned:
        token = cleaned.split()[0].strip()
        if token:
            return token

    for key in ("id", "key", "title"):
        if fields.get(key):
            return fields[key]
    return None


def _normalize_alias(value: str) -> str:
    """Normalize operation/type/field aliases into the canonical project vocabulary."""
    return OPERATION_ALIASES.get(value.lower(), value.lower())


def _identifier_from_reference(reference: SearchDocument) -> str | None:
    """Resolve a stable follow-up identifier from the last cited document."""
    metadata = reference.metadata
    if metadata.get("key"):
        return str(metadata["key"])
    if metadata.get("id"):
        return str(metadata["id"])
    return reference.title

