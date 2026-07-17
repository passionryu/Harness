from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class AgentStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    RETRYABLE_FAILED = "retryable_failed"
    NEEDS_HUMAN = "needs_human"


@dataclass(frozen=True)
class AgentInput:
    task_id: str
    title: str
    body: str
    state: str
    artifacts_root: Path
    timeout_seconds: int
    retry_count: int
    retry_limit: int


@dataclass(frozen=True)
class ArtifactSpec:
    kind: str
    path: Path


@dataclass(frozen=True)
class AgentResult:
    status: AgentStatus
    summary: str
    artifacts: list[ArtifactSpec] = field(default_factory=list)
    error: str | None = None


class AgentProtocol(Protocol):
    name: str

    def run(self, input_data: AgentInput) -> AgentResult:
        """Run an agent and return a structured, auditable result."""
