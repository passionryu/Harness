# Kanban State Machine

```text
Backlog
-> Plan Review
-> Dev Ready
-> Dev Review
-> QA Ready
-> QA Review
-> Ready To Deploy
-> Done

QA Review -- QA failure or human rejection --> Dev Ready
Dev Review -- human rejection --> Dev Ready
```

## Transition Table

| From | To | Required Evidence |
|---|---|---|
| Backlog | Plan Review | Plan Agent artifact |
| Plan Review | Dev Ready | human plan approval |
| Dev Ready | Dev Review | implementation and test report |
| Dev Review | QA Ready | human dev approval |
| QA Ready | QA Review | QA report |
| QA Review | Dev Ready | QA failure or human rejection |
| QA Review | Ready To Deploy | human QA approval |
| Ready To Deploy | Done | human deploy approval |
