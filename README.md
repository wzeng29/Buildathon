# Buildathon

Buildathon is a Slack-first engineering assistant that unifies enterprise knowledge retrieval, observability lookup, and performance-testing workflows behind one conversational interface.

It is built for teams that regularly jump between AS400 manuals, Jira, Confluence, Grafana, Datadog, Slack, and local k6 tooling. Instead of opening each system manually, users can ask in Slack or the local CLI and let the agent route the request to the right source or workflow.

## What The Project Does

Buildathon is not only a "find me an answer" bot. It supports four practical categories of work:

- Knowledge retrieval from AS400 / IBM i PDF manuals, Confluence, and Jira
- Observability lookup from Grafana and Datadog dashboards
- Performance workflow orchestration around Jira and k6
- Team collaboration through Slack updates, summaries, and report delivery

Example requests:

- `whats the command for checking library list in as400`
- `what is KAN-16 about`
- `read datadog dashboard test`
- `read grafana dashboard payments`
- `test jira KAN-5`
- `run k6 test auth vus=2 duration=30s`

## Project Goal

The goal of the project is to reduce the cost of context switching in engineering teams.

In a real team workflow, the answer to one question may require:

- documentation from Confluence
- issue context from Jira
- command knowledge from AS400 manuals
- live telemetry from Grafana or Datadog
- or a k6 performance test and report

Buildathon provides one entry point for all of these, using natural language in Slack or the CLI.

## Current Architecture

The current implementation is best described as:

- one orchestrator agent
- multiple source-specific connectors
- multiple execution paths

It is not a fully autonomous multi-agent system. The main control flow lives in [src/agent.py](src/agent.py), which:

- normalizes the question
- selects relevant connectors
- retrieves evidence
- ranks and filters citations
- chooses between a local fast path or LLM-backed answer generation
- formats the final response for Slack or CLI

## Main Capabilities

### 1. AS400 / IBM i Retrieval

The project indexes local AS400 manuals from PDF and CSV files under `files/`.

It supports:

- semantic retrieval over PDF chunks
- command-oriented answers for IBM i questions
- Slack-friendly evidence summaries with citations

Relevant files:

- [src/connectors.py](src/connectors.py)
- [src/semantic_retrieval.py](src/semantic_retrieval.py)

### 2. Jira And Confluence Retrieval

The agent can read enterprise work artifacts such as:

- Jira tickets
- Confluence documentation

This enables use cases such as:

- understanding a ticket before a test run
- finding internal docs for a system
- grounding Slack answers in team-owned knowledge

### 3. Grafana And Datadog Observability

The project can read observability sources, including:

- Grafana dashboard discovery
- Datadog dashboard lookup
- Datadog dashboard detail summaries
- Datadog widget query extraction
- Datadog widget data summaries through the query API

This lets the bot answer more than plain documentation questions. It can also surface monitoring context.

### 4. k6 Performance Workflows

Buildathon includes a local k6 workflow layer for performance engineering.

It can:

- read a Jira ticket
- build a performance plan
- generate or scope ticket-specific k6 work
- run k6 locally
- summarize results
- attach reports back into Slack and Jira flows

Relevant files:

- [src/perf_tools.py](src/perf_tools.py)
- [docs/skills/](docs/skills/)
- [performance/](performance/)

## Repository Layout

```text
.
|-- src/                     Core app: agent, connectors, Slack entrypoint, retrieval
|-- tests/                   Python tests
|-- files/                   Local AS400 manuals and searchable artifacts
|-- performance/             k6 scripts, data, results, generated reports
|-- docs/                    Architecture diagrams and workflow documentation
|-- website/                 Demo e-commerce system and observability stack
|-- config.py                Environment-backed settings
`-- requirements.txt         Python dependencies
```

## Core Stack And What Each Piece Does

### Python

Primary application language for:

- orchestration
- connectors
- Slack integration
- local retrieval
- performance workflows

### Slack SDK

Used in [src/slack_app.py](src/slack_app.py) to:

- receive `app_mention` events
- post a placeholder message
- run the agent asynchronously
- update Slack with the final answer
- upload HTML reports when available

### OpenAI API

Used for:

- natural language understanding
- answer generation from retrieved evidence
- workflow synthesis where local deterministic logic is not enough

Some high-frequency AS400 command questions now use a local fast path instead of always calling the LLM.

### Sentence Transformers + NumPy

Used for local semantic retrieval:

- encode document chunks and user questions into embeddings
- compare them with vector similarity
- rank relevant AS400 manual chunks

### pypdf

Used to:

- read IBM i / AS400 PDF manuals
- extract text page by page
- feed the chunking and indexing pipeline

### Requests

Used for API integration with:

- Jira
- Confluence
- Grafana
- Datadog

### Redis

Used for short-lived conversation memory so Slack replies can preserve context across a thread or channel.

### Docker / Docker Compose

Used for:

- the local demo e-commerce stack
- observability services
- Datadog agent integration testing

### k6

Used for:

- performance test execution
- workflow-driven testing
- summary generation
- report production

## How AS400 Retrieval Works

The AS400 retrieval pipeline is a RAG-style local retrieval flow:

1. PDF manuals are loaded from `files/`
2. Text is extracted page by page
3. Long pages are split into chunks
4. Chunks are embedded with a transformer model
5. Embeddings are cached locally in a semantic index
6. A user question is embedded and matched against the document chunks
7. The best chunks are used as evidence for answer generation or local command selection

This allows the bot to answer AS400 questions using local documentation instead of only keyword search.

## Slack And CLI Entry Points

### Slack

Start the Slack Socket Mode app:

```powershell
.venv\Scripts\python.exe -m src.slack_app
```

### CLI

Run a one-shot question locally:

```powershell
.venv\Scripts\python.exe -m src.main "read datadog dashboard test"
```

## Setup

Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

The app reads `.env` from the repository root.

### Slack

- `SLACK_BOT_TOKEN`
- `SLACK_APP_TOKEN`

### OpenAI

- `OPENAI_API_KEY`
- `OPENAI_MODEL`

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

### Datadog

- `DATADOG_API_KEY`
- `DATADOG_APP_KEY`

### AS400 Retrieval

- `AS400_MANUAL_PATH`
- `AS400_CHUNK_CHARS`
- `AS400_EMBEDDING_MODEL`
- `AS400_INDEX_PATH`

### Memory

- `REDIS_URL`
- `REDIS_KEY_PREFIX`
- `MEMORY_MAX_TURNS`
- `MEMORY_TTL_SECONDS`

### k6

- `K6_COMMAND`
- `K6_PROJECT_ROOT`
- `MCP_CONFIG_PATH`

## Demo Website

The demo e-commerce platform lives under [website/](website/README.md).

Start the full stack:

```powershell
cd website
docker compose up -d
docker compose ps
```

Main URLs:

- Frontend: `http://localhost:4000`
- Grafana: `http://localhost:3000`
- Prometheus: `http://localhost:9090`
- Users API: `http://localhost:3001`
- Products API: `http://localhost:3002`
- Cart API: `http://localhost:3003`
- Orders API: `http://localhost:3004`
- Payments API: `http://localhost:3005`

Stop the stack:

```powershell
cd website
docker compose down
```

## Jira Performance Workflow

The Jira-driven performance flow currently looks like this:

1. Read a Jira issue
2. Decide whether to stop at planning or continue to execution
3. Build a structured performance plan
4. Generate ticket-scoped k6 work
5. Run k6 locally when needed
6. Generate summaries and reports
7. Feed results back into the collaboration loop

Generated ticket-scoped scripts are written under:

```text
performance/tests/<service>/<service>.<ticket-key-lower>.test.js
```

Generated results are written under:

```text
performance/results/<timestamp>_bot_<service>/
```

## Documentation

Project diagrams and PDFs live in [docs/](docs/).

Useful files:

- [docs/high-level-architecture.mmd](docs/high-level-architecture.mmd)
- [docs/high-level-architecture.pdf](docs/high-level-architecture.pdf)
- [docs/low-level-execution-flow.mmd](docs/low-level-execution-flow.mmd)
- [docs/low-level-execution-flow.pdf](docs/low-level-execution-flow.pdf)
- [docs/workflow.mmd](docs/workflow.mmd)
- [docs/workflow.pdf](docs/workflow.pdf)

### Architecture Diagrams

The Mermaid source files are the editable source of truth. The matching PDFs are generated artifacts for sharing or presentation.

- High-level architecture: [docs/high-level-architecture.mmd](docs/high-level-architecture.mmd)
- Low-level execution flow: [docs/low-level-execution-flow.mmd](docs/low-level-execution-flow.mmd)
- Workflow overview: [docs/workflow.mmd](docs/workflow.mmd)

If Mermaid CLI is installed, regenerate a PDF with:

```powershell
mmdc -i docs/high-level-architecture.mmd -o docs/high-level-architecture.pdf
```

## Testing

Run the full suite:

```powershell
.venv\Scripts\python.exe -m unittest
```

Run one focused test:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_app.AgentTests.test_datadog_connector_summarizes_dashboard_details_on_read
```

## Known Implementation Notes

- The current system is an orchestrator architecture, not a fully autonomous multi-agent system
- AS400 command handling includes a local fast path for speed and stability
- Datadog support includes dashboard lookup plus widget-level summaries, not full Datadog APM analytics yet
- The demo website originally used Grafana/Prometheus/Loki/Tempo; Datadog support was added on top for validation and observability experiments
