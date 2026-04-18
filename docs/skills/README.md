# Project Skills

This folder is the project-wide home for reusable AI playbooks.

These skills are not tied to Claude. They are plain markdown workflows and reference packs that can be used with:

- OpenAI and Codex
- ChatGPT projects
- Claude Code
- Cursor, Windsurf, or any editor that can read repo docs
- Manual team workflows during testing and reporting

## Available Skills

### [k6-best-practices](./k6-best-practices/README.md)

Use this when you need to write, fix, or review k6 scripts for HTTP, WebSocket, or gRPC testing.

### [performance-report-analysis](./performance-report-analysis/README.md)

Use this after a performance test has run and you need help interpreting results, diagnosing bottlenecks, or writing technical and business reports.

### [performance-testing-strategy](./performance-testing-strategy/README.md)

Use this when you are still planning the test approach and need help choosing test types, sizing load, defining SLAs, and sequencing test execution.

## How To Use With OpenAI Or Codex

Point the model at the relevant skill folder and tell it to use that playbook.

Examples:

```text
Use docs/skills/k6-best-practices to fix performance/tests/auth/auth.test.js.
```

```text
Use docs/skills/performance-report-analysis to analyze this k6 summary JSON and write a technical report.
```

```text
Use docs/skills/performance-testing-strategy to design a load test plan for our auth API.
```

Recommended prompt pattern:

```text
Use [skill path] as the workflow.
Read SKILL.md first.
Load reference files only when needed.
Apply the output format from the skill.
```

## How To Use Manually

1. Open the skill folder you need.
2. Read `SKILL.md`.
3. Use the referenced docs only when the task needs them.
4. Reuse the templates and checklists in your test plan, script review, or report.

## Compatibility Layer

The same three skills are also kept under `.claude/skills/` for Claude-compatible tooling.

In this repo, `docs/skills/` is the human-facing, model-agnostic location.
