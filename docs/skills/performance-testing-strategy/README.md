# Performance Testing Strategy

This playbook helps plan performance testing before scripts are written or runs are executed.

## Use It For

- deciding which test types to run
- sizing users or request rates
- defining SLAs and pass/fail criteria
- sequencing smoke, load, stress, spike, and endurance tests
- building a release or regression performance plan

## Start Here

- Main workflow: [SKILL.md](./SKILL.md)
- Test type selection: [references/TEST-TYPES.md](./references/TEST-TYPES.md)
- Metrics and SLAs: [references/METRICS-AND-SLAS.md](./references/METRICS-AND-SLAS.md)

## Example Prompt

```text
Use docs/skills/performance-testing-strategy as the workflow.
Read SKILL.md first.
Design a performance test plan for the auth service and recommend the test sequence.
```
