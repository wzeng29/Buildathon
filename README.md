# Buildathon

Buildathon is a Slack-first support and performance assistant. It combines enterprise connectors, local retrieval, and a skill-driven k6 workflow in one repository.

## Core Capabilities

- Jira search and CRUD actions
- Confluence search and CRUD actions
- Local k6 execution from the in-repo `performance/` suite
- Jira ticket-driven k6 script generation and execution
- Markdown performance report generation from k6 summary exports
- Grafana dashboard lookup with MCP-first resolution and direct fallback
- IBM i / AS400 / Synon 2E retrieval from local manuals and CSV catalogs
- Conversation memory for Slack threads, channels, and local CLI sessions
- Reusable project playbooks under `docs/skills/`

## Common Commands

Slack mentions or CLI text:

- `run k6 test auth vus=2 duration=30s`
- `create k6 report auth`
- `create k6 workflow auth duration=30s`
- `test jira KAN-5`
- `test KAN-5 service=payments vus=2 duration=30s`
- `read grafana dashboard auth`
- `create jira ticket summary="Build RAG bot" description="Create the Slack agent flow"`
- `update jira ticket KAN-1 status="Done"`
- `delete confluence page 459028`

Lightweight slash skills:

- `/k6-test auth duration: 30s vus: 2`
- `/k6-report auth`
- `/k6-workflow auth duration: 30s`
- `/grafana-dashboard auth`

## Project Skills

The repo includes project-owned, model-agnostic playbooks in [docs/skills/README.md](docs/skills/README.md):

- [k6 best practices](docs/skills/k6-best-practices/README.md)
- [performance report analysis](docs/skills/performance-report-analysis/README.md)
- [performance testing strategy](docs/skills/performance-testing-strategy/README.md)

They work with OpenAI, Codex, ChatGPT Projects, Claude, or manual workflows. A good prompt pattern is:

```text
Use docs/skills/k6-best-practices as the workflow.
Read SKILL.md first.
Load references only when needed.
Apply the output format from the skill.
```

The k6 flows apply these playbooks automatically:

- `run k6 test <service>` adds `k6-best-practices` guidance to the result message
- `create k6 report <service>` embeds `performance-report-analysis` guidance in the generated report
- `create k6 workflow <service>` aligns to the full Jira -> strategy -> script validation -> run -> report -> analysis flow, applies all three performance playbooks, compares against the latest baseline in `performance/results/`, and includes Jira/Git follow-up notes in the output
- `test jira <KEY>` runs the ticket-driven workflow and now consumes each selected skill's `SKILL.md`, `references/*.md`, and `evals/evals.json`

## Jira Performance Workflow

The intended end-to-end workflow is:

1. Read the Jira issue and extract SLAs, VUs, duration, datasets, and acceptance criteria
2. Apply `docs/skills/performance-testing-strategy`
   Load `SKILL.md`, `references/*.md`, and `evals/evals.json` to build the strategy plan
3. Generate a ticket-scoped k6 script using `docs/skills/k6-best-practices`
   Load `SKILL.md`, `references/*.md`, and `evals/evals.json` to drive script generation and local validation
4. Validate the generated script against k6 skill assertions
5. Run `k6` against `tests/<service>/<service>.test.js`
6. Generate a report with baseline comparison, executive summary, technical detail, and Grafana references
7. Apply `docs/skills/performance-report-analysis`
   Load `SKILL.md`, `references/*.md`, and `evals/evals.json` to generate technical and business analysis
8. Comment back on Jira with the executive summary, image/link references, and analysis
9. Version the run artifacts in git so future runs can compare against a historical baseline

The generated Jira-ticket scripts are written to:

```text
performance/tests/<service>/<service>.<ticket-key-lower>.test.js
```

## Architecture

High-level flow:

1. Slack Socket Mode or the local CLI sends a request to `BuildAgents`
2. The agent checks for an explicit action first
3. CRUD-style actions route into connectors
4. Search questions route through the lightweight multi-agent retrieval flow
5. Ticket-based performance requests route into the Jira performance workflow connector
6. Results are grounded with source documents and returned to Slack or the CLI

Main modules:

- [src/agent.py](src/agent.py)
  Main orchestration entrypoint
- [src/connectors.py](src/connectors.py)
  Jira, Jira performance workflow, Confluence, Grafana, AS400, and k6 connectors
- [src/perf_tools.py](src/perf_tools.py)
  k6 workspace resolution, execution, and report generation
- [src/llm.py](src/llm.py)
  OpenAI-backed strategy, script, and analysis generation
- [src/mcp_adapter.py](src/mcp_adapter.py)
  Optional MCP-aware configuration layer
- [src/project_skills.py](src/project_skills.py)
  Project playbook discovery for k6 flows
- [src/slack_app.py](src/slack_app.py)
  Slack Socket Mode entrypoint

Diagrams:

- [docs/architecture.mmd](docs/architecture.mmd)
- [docs/architecture.pdf](docs/architecture.pdf)
- [docs/project-structure.mmd](docs/project-structure.mmd)
- [docs/project-structure.pdf](docs/project-structure.pdf)
- [docs/workflow.mmd](docs/workflow.mmd)
- [docs/workflow.pdf](docs/workflow.pdf)

## Repository Layout

```text
.
|-- config.py
|-- docs/
|   |-- architecture.mmd
|   |-- architecture.pdf
|   |-- project-structure.mmd
|   |-- project-structure.pdf
|   `-- skills/
|-- files/
|-- performance/
|   |-- data/
|   |-- lib/
|   |-- results/
|   |-- tests/
|   |-- mock_auth_server.py
|   |-- run-auth-local.ps1
|   `-- start-auth-local.ps1
|-- src/
|-- tests/
|-- .mcp.example.json
`-- .mcp.json
```

## Configuration

### Required for Slack

- `SLACK_BOT_TOKEN`
- `SLACK_APP_TOKEN`

### Required for OpenAI-backed answers

- `OPENAI_API_KEY`
- `OPENAI_MODEL`

The Jira performance workflow uses the OpenAI-backed path to:

- build a strategy plan from Jira + skill bundles
- generate a ticket-scoped k6 script from Jira + skill bundles
- generate technical and business report sections from k6 results + skill bundles

### Jira

- `JIRA_BASE_URL`
- `JIRA_USERNAME`
- `JIRA_API_TOKEN`
- `JIRA_PROJECT_KEY`

### Confluence

- `CONFLUENCE_BASE_URL`
- `CONFLUENCE_USERNAME`
- `CONFLUENCE_API_TOKEN`
- `CONFLUENCE_SPACE_KEY`

### Grafana

- `GRAFANA_URL`
- `GRAFANA_SERVICE_ACCOUNT_TOKEN`

Grafana can also be configured through [`.mcp.json`](.mcp.json). When both are present, the connector prefers MCP-sourced Grafana connection details.

Important:

- `auth` test traffic and the mock auth server use `127.0.0.1:3001`
- Grafana must point to an actual Grafana server
- `127.0.0.1:3001` is not a Grafana instance in this project

### k6

- `K6_COMMAND`
- `K6_PROJECT_ROOT`
- `MCP_CONFIG_PATH`

## Local Setup

Install dependencies:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Start the mock auth service:

```powershell
cd "C:\Program Files\code\Buildathon\performance"
powershell -ExecutionPolicy Bypass -File .\start-auth-local.ps1
```

Run the Slack app:

```powershell
cd "C:\Program Files\code\Buildathon"
.venv\Scripts\python.exe -m src.slack_app
```

Run a local auth test directly:

```powershell
cd "C:\Program Files\code\Buildathon\performance"
powershell -ExecutionPolicy Bypass -File .\run-auth-local.ps1 -BaseUrl http://127.0.0.1:3001 -Vus 2 -Duration 30s
```

Run a local Jira ticket-driven workflow:

```powershell
.venv\Scripts\python.exe -m src.main test jira KAN-5
```

## MCP Usage

The repository ships with [`.mcp.example.json`](.mcp.example.json) as a starter template. The active local configuration is [`.mcp.json`](.mcp.json).

Current MCP-aware systems:

- Jira
- Confluence
- Grafana

Behavior:

- if a matching MCP server is configured and a live handler is attached, the connector uses MCP first
- if no live MCP handler is attached in-process, Grafana falls back to direct API lookup using the same MCP-sourced connection settings
- this keeps Grafana wired to MCP configuration while still allowing local execution in this project

## Quality Notes

- k6 subprocess output is decoded safely on Windows
- local source citations are filtered so only `files/` content is exposed as local sources
- Grafana now fails with a clearer message when the configured URL is not actually a Grafana server
- ticket-driven script generation is model-backed and uses each selected skill's `SKILL.md`, `references`, and `evals`

