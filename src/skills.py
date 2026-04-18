from __future__ import annotations

from src.command_parser import _extract_fields
from src.models import ActionRequest


SKILL_TO_ACTION: dict[str, tuple[str, str, str]] = {
    "/k6-test": ("run", "k6", "test"),
    "/k6-report": ("create", "k6", "report"),
    "/k6-workflow": ("create", "k6", "workflow"),
    "/grafana-dashboard": ("read", "grafana", "dashboard"),
}


def parse_skill_request(text: str) -> ActionRequest | None:
    """Translate lightweight slash skills into normalized action requests."""
    normalized = (text or "").strip()
    if not normalized.startswith("/"):
        return None

    command, _, remainder = normalized.partition(" ")
    action = SKILL_TO_ACTION.get(command.lower())
    if action is None:
        return None

    operation, target_system, target_type = action
    tail = remainder.strip()
    fields = _extract_fields(tail)

    identifier = None
    if tail:
        cleaned = tail
        for key, value in fields.items():
            cleaned = cleaned.replace(f"{key}={value}", "")
            cleaned = cleaned.replace(f"{key}: {value}", "")
            cleaned = cleaned.replace(f"{key}:{value}", "")
        tokens = cleaned.split()
        if tokens:
            identifier = tokens[0].strip()

    return ActionRequest(
        operation=operation,
        target_system=target_system,
        target_type=target_type,
        identifier=identifier,
        fields=fields,
    )
