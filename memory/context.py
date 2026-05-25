from dataclasses import dataclass, field


@dataclass
class TaskMemory:
    task_id: str
    requirement_summary: str = ""
    artifact_refs: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)

    def compact(self) -> dict:
        return {
            "task_id": self.task_id,
            "requirement_summary": self.requirement_summary[:2000],
            "artifact_refs": self.artifact_refs[-20:],
            "decisions": self.decisions[-20:],
        }

