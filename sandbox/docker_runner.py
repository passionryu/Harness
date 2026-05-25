from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SandboxSpec:
    image: str
    workspace: Path
    command: list[str]
    timeout_seconds: int
    memory_limit: str | None = None
    cpus: float | None = None


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    artifacts_dir: Path


class DockerSandboxRunner:
    """Interface placeholder for isolated Docker execution.

    The MVP keeps this non-mutating. A later phase should implement subprocess
    execution with docker resource flags, controlled mounts, timeout handling,
    and cleanup.
    """

    def run(self, spec: SandboxSpec) -> SandboxResult:
        raise NotImplementedError("Docker sandbox execution is not enabled in MVP")

