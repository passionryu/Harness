# Kanban State Machine

```text
Backlog -> Todo -> In Progress -> System QA -> Human QA -> Done
                      ^              |
                      |              v
                      +---------- In Progress
```

## Transition Table

| From | To | Required Evidence |
|---|---|---|
| Backlog | Todo | human triage or normalized issue |
| Todo | In Progress | plan artifact |
| In Progress | System QA | implementation and test report |
| System QA | In Progress | QA failure and retry remaining |
| System QA | Human QA | QA pass report |
| Human QA | In Progress | human rejection |
| Human QA | Done | human approval |

