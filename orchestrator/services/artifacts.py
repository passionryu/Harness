import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from agents.base import ArtifactSpec
from orchestrator.db.models import Artifact


class ArtifactStore:
    def __init__(self, db: Session):
        self.db = db

    def persist_agent_artifacts(
        self, task_id: str, run_id: str, artifacts: list[ArtifactSpec]
    ) -> list[Artifact]:
        rows: list[Artifact] = []
        for spec in artifacts:
            path = Path(spec.path)
            digest = _artifact_digest(path)
            row = Artifact(
                task_id=task_id,
                run_id=run_id,
                kind=spec.kind,
                path=str(path),
                sha256=digest,
            )
            self.db.add(row)
            rows.append(row)
        return rows


# 파일과 디렉토리 artifact를 모두 안정적으로 해시한다.
def _artifact_digest(path: Path) -> str:
    if path.is_dir():
        hasher = hashlib.sha256()
        for child in sorted(item for item in path.rglob("*") if item.is_file()):
            hasher.update(str(child.relative_to(path)).encode("utf-8"))
            hasher.update(child.read_bytes())
        return hasher.hexdigest()
    return hashlib.sha256(path.read_bytes()).hexdigest()
