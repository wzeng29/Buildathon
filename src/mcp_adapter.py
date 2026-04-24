from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from src.models import ActionRequest, ActionResult, SearchDocument


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    transport_type: str
    command: str = ""
    args: tuple[str, ...] = ()
    url: str = ""
    env: dict[str, str] | None = None


class MCPHandler(Protocol):
    """Small interface for system-specific MCP handlers."""

    def search(self, query: str, limit: int) -> list[SearchDocument]:
        ...

    def execute(self, request: ActionRequest) -> ActionResult:
        ...


class MCPAdapter:
    """Configuration-aware MCP router used by connectors as an optional first hop."""

    SYSTEM_SERVER_ALIASES: dict[str, tuple[str, ...]] = {
        "jira": ("atlassian", "jira"),
        "confluence": ("atlassian", "confluence"),
        "grafana": ("grafana",),
        "datadog": ("datadog",),
    }

    def __init__(
        self,
        handlers: dict[str, MCPHandler] | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        self.config_path = self._resolve_config_path(config_path)
        self.handlers = handlers or {}
        self.server_configs = self._load_configs(self.config_path)

    def has_server_for(self, system: str) -> bool:
        aliases = self.SYSTEM_SERVER_ALIASES.get(system, (system,))
        return any(alias in self.server_configs for alias in aliases)

    def server_config_for(self, system: str) -> MCPServerConfig | None:
        aliases = self.SYSTEM_SERVER_ALIASES.get(system, (system,))
        for alias in aliases:
            config = self.server_configs.get(alias)
            if config is not None:
                return config
        return None

    def is_enabled(self, system: str) -> bool:
        return self.has_server_for(system) and system in self.handlers

    def search(self, system: str, query: str, limit: int) -> list[SearchDocument] | None:
        if not self.is_enabled(system):
            return None
        return self.handlers[system].search(query, limit)

    def execute(self, system: str, request: ActionRequest) -> ActionResult | None:
        if not self.is_enabled(system):
            return None
        return self.handlers[system].execute(request)

    @classmethod
    def _resolve_config_path(cls, config_path: str | Path | None) -> Path | None:
        if config_path is not None:
            path = Path(config_path)
            return path if path.exists() else None

        project_root = Path(__file__).resolve().parents[1]
        for candidate in (project_root / ".mcp.json", project_root / ".mcp.example.json"):
            if candidate.exists():
                return candidate
        return None

    @classmethod
    def _load_configs(cls, config_path: Path | None) -> dict[str, MCPServerConfig]:
        if config_path is None:
            return {}

        payload = json.loads(config_path.read_text(encoding="utf-8"))
        servers = payload.get("mcpServers", {})
        configs: dict[str, MCPServerConfig] = {}
        for name, server in servers.items():
            configs[name] = MCPServerConfig(
                name=name,
                transport_type=str(server.get("type", "stdio")),
                command=str(server.get("command", "")),
                args=tuple(server.get("args", []) or []),
                url=str(server.get("url", "")),
                env=dict(server.get("env", {}) or {}),
            )
        return configs


def build_mcp_adapter(
    handlers: dict[str, MCPHandler] | None = None,
    config_path: str | Path | None = None,
) -> MCPAdapter:
    """Create the default MCP adapter used by Jira, Confluence, and Grafana connectors."""
    return MCPAdapter(handlers=handlers, config_path=config_path)
