# k6 Best Practices

This playbook helps write, repair, and review k6 scripts in a consistent way.

## Use It For

- creating a new k6 script
- fixing a broken k6 script
- choosing the right executor
- reviewing VU, arrival-rate, threshold, or `SharedArray` usage
- structuring reusable test flows

## Start Here

- Main workflow: [SKILL.md](./SKILL.md)
- Executors and workload models: [references/EXECUTORS.md](./references/EXECUTORS.md)
- Protocol guidance: [references/PROTOCOLS.md](./references/PROTOCOLS.md)
- Design patterns: [references/DESIGN-PATTERNS.md](./references/DESIGN-PATTERNS.md)

## Example Prompt

```text
Use docs/skills/k6-best-practices as the workflow.
Read SKILL.md first.
Fix performance/tests/auth/auth.test.js and explain which executor fits the load goal.
```
