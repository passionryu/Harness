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
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
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

