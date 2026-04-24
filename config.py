from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
DOTENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_AS400_MANUAL_GLOB = f"{PROJECT_ROOT / 'files' / '*.pdf'};{PROJECT_ROOT / 'files' / '*.csv'}"
DEFAULT_AS400_INDEX_PATH = PROJECT_ROOT / ".cache" / "as400_manual_index.npz"
DEFAULT_K6_PROJECT_ROOT = PROJECT_ROOT / "performance"
DEFAULT_MCP_CONFIG_PATH = PROJECT_ROOT / ".mcp.json"

# Load the project-level .env explicitly so the app behaves the same whether it
# is started from the repository root, src/, or an IDE task runner.
load_dotenv(dotenv_path=DOTENV_PATH)


def _env(name: str, default: str = "") -> str:
    """Read a string environment variable and trim surrounding whitespace."""
    return os.getenv(name, default).strip()


def _flag(name: str, default: str = "false") -> bool:
    """Parse common truthy values from environment variables."""
    return _env(name, default).lower() in {"1", "true", "yes", "on"}


def _is_real_value(value: str) -> bool:
    """Reject blank values and template placeholders from local config."""
    lowered = value.strip().lower()
    if not lowered:
        return False

    placeholders = {
        "https://your-company.atlassian.net",
        "your-company",
        "xxx",
        "changeme",
        "<your-grafana-service-account-token>",
    }
    return lowered not in placeholders


@dataclass(frozen=True)
class Settings:
    """Typed view over all environment variables used by the application."""

    openai_api_key: str = _env("OPENAI_API_KEY")
    openai_model: str = _env("OPENAI_MODEL", "gpt-4o-mini")

    grafana_url: str = _env("GRAFANA_URL")
    grafana_service_account_token: str = _env("GRAFANA_SERVICE_ACCOUNT_TOKEN")

    confluence_base_url: str = _env("CONFLUENCE_BASE_URL")
    confluence_username: str = _env("CONFLUENCE_USERNAME")
    confluence_api_token: str = _env("CONFLUENCE_API_TOKEN")
    confluence_space_key: str = _env("CONFLUENCE_SPACE_KEY")

    datadog_api_key: str = _env("DATADOG_API_KEY")
    datadog_app_key: str = _env("DATADOG_APP_KEY")

    jira_base_url: str = _env("JIRA_BASE_URL")
    jira_username: str = _env("JIRA_USERNAME")
    jira_api_token: str = _env("JIRA_API_TOKEN")
    jira_project_key: str = _env("JIRA_PROJECT_KEY")

    slack_bot_token: str = _env("SLACK_BOT_TOKEN")
    slack_app_token: str = _env("SLACK_APP_TOKEN")
    slack_signing_secret: str = _env("SLACK_SIGNING_SECRET")
    slack_allowed_channel: str = _env("SLACK_ALLOWED_CHANNEL")

    as400_manual_path: str = _env("AS400_MANUAL_PATH", str(DEFAULT_AS400_MANUAL_GLOB))
    as400_chunk_chars: int = int(_env("AS400_CHUNK_CHARS", "1400"))
    as400_embedding_model: str = _env(
        "AS400_EMBEDDING_MODEL",
        "sentence-transformers/all-MiniLM-L6-v2",
    )
    as400_index_path: str = _env("AS400_INDEX_PATH", str(DEFAULT_AS400_INDEX_PATH))

    redis_url: str = _env("REDIS_URL")
    redis_key_prefix: str = _env("REDIS_KEY_PREFIX", "ragbot")
    memory_max_turns: int = int(_env("MEMORY_MAX_TURNS", "6"))
    memory_ttl_seconds: int = int(_env("MEMORY_TTL_SECONDS", "86400"))

    max_documents_per_source: int = int(_env("MAX_DOCUMENTS_PER_SOURCE", "5"))
    max_citations: int = int(_env("MAX_CITATIONS", "6"))
    verify_ssl: bool = _flag("VERIFY_SSL", "true")

    k6_command: str = _env("K6_COMMAND", "k6")
    k6_project_root: str = _env("K6_PROJECT_ROOT", str(DEFAULT_K6_PROJECT_ROOT))
    mcp_config_path: str = _env("MCP_CONFIG_PATH", str(DEFAULT_MCP_CONFIG_PATH))

    @property
    def raw_environment(self) -> dict[str, str]:
        """Return a copy of the current process environment for subprocess use."""
        return dict(os.environ)


settings = Settings()
