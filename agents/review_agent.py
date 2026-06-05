import re
import subprocess
from pathlib import Path

from agents.base import AgentInput, AgentResult, AgentStatus, ArtifactSpec
from orchestrator.core.settings import settings


class ReviewAgent:
    name = "review"

    # Dev 결과물을 QA 전에 정적 규칙으로 검토하고 품질 게이트 결과를 남긴다.
    def run(self, input_data: AgentInput) -> AgentResult:
        review_dir = input_data.artifacts_root / input_data.task_id / "review"
        review_dir.mkdir(parents=True, exist_ok=True)
        report = review_dir / "review-report.md"

        repo_path = settings.target_repo_path.expanduser()
        changed_files = _changed_files(repo_path)
        findings = _review_changed_files(repo_path, changed_files)
        criticals = [finding for finding in findings if finding.startswith("[critical]")]
        finding_lines = findings if findings else ["- 발견 사항 없음"]

        report.write_text(
            "\n".join(
                [
                    f"# Review Report: {input_data.title}",
                    "",
                    "## 목적",
                    "Dev 완료 후 QA 전에 코드 품질과 하네스 생성물의 안전성을 확인한다.",
                    "",
                    "## 변경 파일",
                    *([f"- `{path}`" for path in changed_files] or ["- 변경 파일을 찾지 못했습니다."]),
                    "",
                    "## 검토 항목",
                    "- DDD/Hexagonal 경계 위반 가능성",
                    "- 컨트롤러 내부 DTO/data class 존재 여부",
                    "- 테스트명 한국어 표현 여부",
                    "- 사용자 메시지/예외 메시지 한국어 우선 여부",
                    "- 로그 key 규칙 who/what/requestData/reason 적용 여부",
                    "- 불필요한 scaffold/TODO/하네스 잔재 존재 여부",
                    "",
                    "## 발견 사항",
                    *finding_lines,
                    "",
                    "## 결과",
                    "통과" if not criticals else "차단",
                ]
            ),
            encoding="utf-8",
        )

        if criticals:
            return AgentResult(
                status=AgentStatus.FAILED,
                summary="Review Agent가 QA 전 차단 이슈를 발견했습니다.",
                artifacts=[ArtifactSpec("review-report", report)],
                error="; ".join(criticals),
            )

        return AgentResult(
            status=AgentStatus.SUCCESS,
            summary="Review Agent가 QA 전 코드 품질 검토를 통과했습니다.",
            artifacts=[ArtifactSpec("review-report", report)],
        )


# 기준 브랜치 대비 변경 파일 목록을 반환한다.
def _changed_files(repo_path: Path) -> list[str]:
    for base in ["stage", "origin/stage", "main", "origin/main"]:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return []


# 변경 파일을 하네스 품질 규칙으로 점검한다.
def _review_changed_files(repo_path: Path, changed_files: list[str]) -> list[str]:
    findings: list[str] = []
    for relative_path in changed_files:
        path = repo_path / relative_path
        if not path.exists() or path.suffix not in {".kt", ".ts", ".tsx", ".mjs"}:
            continue
        text = path.read_text(encoding="utf-8")

        if "TODO(\"" in text or "AI Harness가 route를 기준으로 생성한 초기 scaffold" in text:
            findings.append(f"[critical] `{relative_path}`에 불완전한 scaffold/TODO 구현이 남아 있습니다.")

        if relative_path.endswith("Controller.kt") and re.search(r"\bdata\s+class\b", text):
            findings.append(f"[critical] `{relative_path}` 컨트롤러 파일 안에 data class가 있습니다.")

        if relative_path.endswith("Test.kt"):
            english_names = _english_test_names(text)
            for name in english_names:
                findings.append(f"[warning] `{relative_path}` 테스트명 `{name}`은 한국어 표현이 아닙니다.")

        if "logWarn" in text or "logError" in text:
            missing_keys = [key for key in ["who=", "what=", "requestData=", "reason="] if key not in text]
            if missing_keys:
                findings.append(f"[warning] `{relative_path}` 로그에 고정 key가 부족합니다: {', '.join(missing_keys)}")

    return findings


# Kotlin 테스트 함수명 중 한국어가 전혀 없는 이름을 찾는다.
def _english_test_names(text: str) -> list[str]:
    names = re.findall(r"fun\s+`([^`]+)`\s*\(", text)
    return [name for name in names if not re.search(r"[가-힣]", name)]
