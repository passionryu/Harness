# Core Harness Rules

- Do not move a task to `Done` without human approval.
- Do not let an agent mutate workflow state directly.
- Do not overwrite prior artifacts.
- Do not retry indefinitely.
- Do not run agents against a dirty shared workspace.
- Do not log secrets or full credentials.
- Prefer explicit state transitions over implicit behavior.
- Prefer small deterministic scripts over broad framework magic.

