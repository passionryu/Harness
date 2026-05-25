# DB Schema

This schema is intentionally small and auditable.

## tasks

Workflow task mapped to one GitHub issue.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | primary key |
| `github_issue_url` | text | optional for local MVP |
| `github_issue_number` | integer | optional |
| `title` | text | required |
| `body` | text | markdown requirement |
| `state` | text | Kanban state |
| `retry_count` | integer | current retry count |
| `retry_limit` | integer | max retries |
| `human_approved_at` | timestamp | required before Done |
| `created_at` | timestamp | server time |
| `updated_at` | timestamp | server time |

## runs

One agent execution attempt.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | primary key |
| `task_id` | UUID | FK tasks |
| `agent_name` | text | plan/dev/qa |
| `status` | text | success/failed/retryable_failed/needs_human |
| `started_at` | timestamp | |
| `finished_at` | timestamp | |
| `timeout_seconds` | integer | |
| `summary` | text | concise result |
| `error` | text | failure details |

## artifacts

Generated files and metadata.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | primary key |
| `task_id` | UUID | FK tasks |
| `run_id` | UUID | FK runs, nullable |
| `kind` | text | plan, patch, test-report, qa-report |
| `path` | text | filesystem path |
| `sha256` | text | content hash |
| `created_at` | timestamp | |

## state_transitions

State change timeline.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | primary key |
| `task_id` | UUID | FK tasks |
| `from_state` | text | nullable on create |
| `to_state` | text | |
| `reason` | text | |
| `actor` | text | system/human/agent |
| `created_at` | timestamp | |

## audit_logs

Append-only audit event records.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | primary key |
| `task_id` | UUID | FK tasks, nullable |
| `run_id` | UUID | FK runs, nullable |
| `event_type` | text | |
| `payload` | json | sanitized details |
| `created_at` | timestamp | |

