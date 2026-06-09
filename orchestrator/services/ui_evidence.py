import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class UiEvidencePublishResult:
    target_branch: str
    evidence_branch: str
    evidence_commit: str
    merge_commit: str
    files: list[str]
    pushed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "status": "published",
            "target_branch": self.target_branch,
            "evidence_branch": self.evidence_branch,
            "evidence_commit": self.evidence_commit,
            "merge_commit": self.merge_commit,
            "files": self.files,
            "pushed": self.pushed,
        }


# UI 증거 이미지를 target repo에 커밋하고 stage 계열 브랜치에 병합한다.
def publish_ui_evidence_to_stage(
    source_paths: list[Path],
    repo_path: Path,
    target_branch: str = "stage",
    slug: str | None = None,
    issue_number: int | None = None,
    push: bool = True,
    remote: str = "origin",
) -> UiEvidencePublishResult:
    repo = repo_path.expanduser().resolve()
    if not (repo / ".git").exists():
        raise ValueError(f"Git 저장소를 찾을 수 없습니다: {repo}")

    sources = [path.expanduser().resolve() for path in source_paths]
    if not sources:
        raise ValueError("게시할 UI 증거 이미지가 없습니다.")
    for source in sources:
        if not source.exists() or not source.is_file():
            raise ValueError(f"UI 증거 이미지 파일을 찾을 수 없습니다: {source}")

    _assert_clean_worktree(repo)
    original_branch = _git_text(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    safe_slug = _safe_slug(slug or _default_slug(issue_number))
    evidence_branch = f"qa-assets/{safe_slug}"
    target_dir = Path("docs/qa-screenshots") / safe_slug
    copied_files: list[str] = []

    try:
        _checkout_target_branch(repo, target_branch, remote)
        _git(repo, ["checkout", "-B", evidence_branch, target_branch])

        destination_dir = repo / target_dir
        destination_dir.mkdir(parents=True, exist_ok=True)
        for source in sources:
            destination = destination_dir / source.name
            shutil.copy2(source, destination)
            copied_files.append(str(target_dir / source.name))

        _git(repo, ["add", str(target_dir)])
        if not _git_text(repo, ["status", "--porcelain", "--", str(target_dir)]):
            raise RuntimeError(f"커밋할 UI 증거 이미지 변경이 없습니다: {target_dir}")

        _git(repo, ["commit", "-m", _evidence_commit_message(issue_number)])
        evidence_commit = _git_text(repo, ["rev-parse", "HEAD"])

        _git(repo, ["checkout", target_branch])
        _git(repo, ["merge", "--no-ff", evidence_branch, "-m", _merge_commit_message(issue_number)])
        merge_commit = _git_text(repo, ["rev-parse", "HEAD"])

        if push:
            _git(repo, ["push", remote, evidence_branch])
            _git(repo, ["push", remote, target_branch])

        return UiEvidencePublishResult(
            target_branch=target_branch,
            evidence_branch=evidence_branch,
            evidence_commit=evidence_commit,
            merge_commit=merge_commit,
            files=copied_files,
            pushed=push,
        )
    finally:
        if original_branch != target_branch:
            _git(repo, ["checkout", original_branch])


def _assert_clean_worktree(repo: Path) -> None:
    status = _git_text(repo, ["status", "--porcelain"])
    if status:
        raise RuntimeError("UI 증거 이미지를 병합하기 전에 target repo working tree가 깨끗해야 합니다.")


def _checkout_target_branch(repo: Path, target_branch: str, remote: str) -> None:
    if _git_ok(repo, ["rev-parse", "--verify", target_branch]):
        _git(repo, ["checkout", target_branch])
        return
    if _git_ok(repo, ["rev-parse", "--verify", f"{remote}/{target_branch}"]):
        _git(repo, ["checkout", "-B", target_branch, f"{remote}/{target_branch}"])
        return
    raise RuntimeError(f"대상 브랜치를 찾을 수 없습니다: {target_branch}")


def _default_slug(issue_number: int | None) -> str:
    date = datetime.now().strftime("%Y-%m-%d")
    if issue_number is not None:
        return f"issue-{issue_number}-ui-evidence-{date}"
    return f"ui-evidence-{date}"


def _safe_slug(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z._-]+", "-", value.strip()).strip("-._")
    return normalized or _default_slug(None)


def _evidence_commit_message(issue_number: int | None) -> str:
    if issue_number is not None:
        return f"[UI 증거] : issue #{issue_number} 화면 이미지 추가"
    return "[UI 증거] : 화면 이미지 추가"


def _merge_commit_message(issue_number: int | None) -> str:
    if issue_number is not None:
        return f"[UI 증거] : issue #{issue_number} 화면 이미지를 stage에 병합"
    return "[UI 증거] : 화면 이미지를 stage에 병합"


def _git(repo: Path, args: list[str]) -> None:
    completed = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=60, check=False)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or f"git {' '.join(args)} failed").strip())


def _git_text(repo: Path, args: list[str]) -> str:
    completed = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=60, check=False)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or f"git {' '.join(args)} failed").strip())
    return completed.stdout.strip()


def _git_ok(repo: Path, args: list[str]) -> bool:
    completed = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=60, check=False)
    return completed.returncode == 0
