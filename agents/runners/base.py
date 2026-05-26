from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from git import Repo

from agents.base import AgentStatus, ArtifactSpec


@dataclass(frozen=True)
class DevRunnerContext:
    task_id: str
    title: str
    body: str
    issue_type: str
    issue_number: str
    branch_name: str
    feature_name: str
    repo: Repo
    repo_path: Path
    task_dir: Path
    timeout_seconds: int


@dataclass
class DevRunnerResult:
    status: AgentStatus
    summary: str
    commits: list[str] = field(default_factory=list)
    progress: list[str] = field(default_factory=list)
    verification: list[str] = field(default_factory=list)
    artifacts: list[ArtifactSpec] = field(default_factory=list)
    error: str | None = None


class DevRunner(Protocol):
    name: str

    def can_handle(self, context: DevRunnerContext) -> bool:
        """Return whether this runner can execute the requested implementation."""

    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        """Execute implementation, tests, and commits for the context."""
