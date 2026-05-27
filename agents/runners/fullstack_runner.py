import re
from pathlib import Path

from agents.base import AgentStatus, ArtifactSpec
from agents.runners.base import DevRunnerContext, DevRunnerResult


class FullstackRunner:
    name = "fullstack_runner"

    # 풀스택 기능 이슈와 StudyHub FE/BE 구조가 모두 있는지 확인한다.
    def can_handle(self, context: DevRunnerContext) -> bool:
        return (
            context.issue_type == "fullstackFeature"
            and (context.repo_path / "apps/server/build.gradle.kts").exists()
            and (context.repo_path / "apps/web/package.json").exists()
        )

    # API contract, 백엔드, 프론트엔드, 연동 검증을 순서대로 실행한다.
    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        if not _is_signup_fullstack_feature(context):
            return _unsupported_result(context)

        from agents.dev_agent import _implement_signup_feature
        from agents.runners.kotlin_spring_runner import _implement_member_signup_api
        from agents.runners.nextjs_runner import _implement_signup_api_connect

        commits: list[str] = []
        progress: list[str] = []
        verification: list[str] = []
        artifacts: list[ArtifactSpec] = []

        contract_paths = _write_signup_contract(context)
        contract_commit = _stage_and_commit(
            context,
            contract_paths,
            f"[{context.feature_name}] : 풀스택 API contract 정리",
        )
        commits.append(f"1. {contract_commit} [{context.feature_name}] : 풀스택 API contract 정리")
        progress.append("- [x] step 1: 사용자 흐름/API contract 정리")

        backend_result = _implement_member_signup_api(context)
        commits.extend(_prefix_commits("BE", backend_result.commits))
        progress.extend(_prefix_progress("BE", backend_result.progress))
        verification.extend(["## Fullstack Backend Runner", "", *backend_result.verification, ""])
        artifacts.extend(backend_result.artifacts)
        if backend_result.status != AgentStatus.SUCCESS:
            return _final_result(
                context=context,
                status=backend_result.status,
                commits=commits,
                progress=progress,
                verification=verification,
                artifacts=artifacts,
                error=f"백엔드 구현 단계 실패: {backend_result.error}",
            )

        frontend_commits, frontend_progress, frontend_verification = _implement_signup_feature(
            repo=context.repo,
            repo_path=context.repo_path,
            feature_name=context.feature_name,
            timeout_seconds=context.timeout_seconds,
        )
        commits.extend(_prefix_commits("FE", frontend_commits))
        progress.extend(_prefix_progress("FE", frontend_progress))
        verification.extend(["## Fullstack Frontend Runner", "", *frontend_verification, ""])

        api_connect_result = _implement_signup_api_connect(context)
        commits.extend(_prefix_commits("API Connect", api_connect_result.commits))
        progress.extend(_prefix_progress("API Connect", api_connect_result.progress))
        verification.extend(["## Fullstack API Connect Runner", "", *api_connect_result.verification, ""])
        artifacts.extend(api_connect_result.artifacts)
        if api_connect_result.status != AgentStatus.SUCCESS:
            return _final_result(
                context=context,
                status=api_connect_result.status,
                commits=commits,
                progress=progress,
                verification=verification,
                artifacts=artifacts,
                error=f"연동 구현 단계 실패: {api_connect_result.error}",
            )

        report = context.task_dir / "fullstack-runner.md"
        report.write_text(
            "\n".join(
                [
                    "# Fullstack Runner",
                    "",
                    f"- runner: `{FullstackRunner.name}`",
                    f"- branch: `{context.branch_name}`",
                    "- flow: API contract -> backend -> frontend -> integration -> smoke test",
                    "",
                    "## 지원된 자동 구현",
                    "",
                    "- 회원가입 API contract 정리",
                    "- Kotlin/Spring Boot 회원가입 API 구현",
                    "- Next.js 회원가입 화면 구현",
                    "- 프론트엔드 submit/API client 연동",
                    "- Gradle 테스트와 프론트 smoke test 실행",
                ]
            ),
            encoding="utf-8",
        )
        artifacts.append(ArtifactSpec("fullstack-runner-report", report))

        return _final_result(
            context=context,
            status=AgentStatus.SUCCESS,
            commits=commits,
            progress=progress,
            verification=verification,
            artifacts=artifacts,
        )


# 현재 풀스택 자동화가 지원하는 회원가입 기능인지 판별한다.
def _is_signup_fullstack_feature(context: DevRunnerContext) -> bool:
    haystack = f"{context.title}\n{context.body}".lower()
    return ("회원" in haystack and "가입" in haystack) or "signup" in haystack or "sign up" in haystack


# 지원하지 않는 풀스택 요구사항은 가짜 성공 없이 중단 리포트를 만든다.
def _unsupported_result(context: DevRunnerContext) -> DevRunnerResult:
    report = context.task_dir / "fullstack-runner.md"
    report.write_text(
        "\n".join(
            [
                "# Fullstack Runner",
                "",
                f"- runner: `{FullstackRunner.name}`",
                f"- issue_type: `{context.issue_type}`",
                f"- branch: `{context.branch_name}`",
                "",
                "## Status",
                "",
                "- Fullstack Runner가 선택되었습니다.",
                "- 아직 이 풀스택 기능은 자동 구현 지원 목록에 없습니다.",
                "- 가짜 성공을 보고하지 않고 중단했습니다.",
                "",
                "## 현재 자동 구현 지원 범위",
                "",
                "- 회원가입 풀스택 기능: API contract, BE 구현, FE 화면, FE/BE 연동, smoke test",
                "",
                "## 다음 선택지",
                "",
                "1. 이슈 본문에 회원가입/sign up 요구사항을 명확히 적은 뒤 다시 실행하세요.",
                "2. 새로운 풀스택 기능이라면 먼저 해당 기능 패턴을 Fullstack Runner에 추가하세요.",
            ]
        ),
        encoding="utf-8",
    )
    return DevRunnerResult(
        status=AgentStatus.NEEDS_HUMAN,
        summary="Fullstack Runner가 선택되었지만 아직 이 풀스택 기능은 자동 구현 지원 목록에 없습니다.",
        progress=[
            "- [x] Fullstack Runner 선택",
            "- [ ] 지원되는 풀스택 구현 패턴 매칭",
        ],
        verification=[
            "## fullstack_runner",
            "",
            "- status: needs_human",
            "- reason: 아직 이 풀스택 기능은 자동 구현 지원 목록에 없습니다.",
            "",
            "## 현재 지원 범위",
            "",
            "- 회원가입 풀스택 기능",
        ],
        artifacts=[ArtifactSpec("fullstack-runner-report", report)],
        error="아직 이 풀스택 기능은 자동 구현 지원 목록에 없습니다.",
    )


# 회원가입 풀스택 구현 전에 FE/BE가 공유할 API contract 문서를 작성한다.
def _write_signup_contract(context: DevRunnerContext) -> list[str]:
    contract_path = context.repo_path / "docs/api" / f"fullstack-{context.issue_number}-signup-contract.md"
    _write_text(
        contract_path,
        "\n".join(
            [
                "# 회원가입 풀스택 API Contract",
                "",
                "## 사용자 경험",
                "",
                "- 사용자는 회원가입 화면에서 이름, 이메일, 비밀번호, 비밀번호 확인, 선택 전화번호, 관심 영역을 입력한다.",
                "- 정상 가입 시 완료 안내를 보고 메인 화면으로 돌아간다.",
                "- 입력값 오류나 API 실패는 한국어 메시지로 안전하게 안내한다.",
                "",
                "## API",
                "",
                "- method/path: `POST /api/members/signup`",
                "- auth: 인증 없이 접근 가능",
                "",
                "## Request",
                "",
                "```json",
                '{ "name": "류성열", "email": "user@example.com", "password": "Password1!", "phone": null, "interests": ["kotlin"] }',
                "```",
                "",
                "## Response",
                "",
                "```json",
                '{ "memberId": 1, "name": "류성열", "email": "user@example.com" }',
                "```",
                "",
                "## Error",
                "",
                "- `400`: 입력값 검증 실패",
                "- `409`: 이미 가입된 이메일",
                "- `500`: 서버 처리 실패",
            ]
        ),
    )
    return [str(contract_path.relative_to(context.repo_path))]


# 지정한 경로에 UTF-8 텍스트 파일을 생성한다.
def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content + "\n", encoding="utf-8")


# 변경된 파일만 스테이징하고 비어 있지 않을 때 커밋한다.
def _stage_and_commit(context: DevRunnerContext, paths: list[str], message: str) -> str:
    existing_paths = [path for path in paths if (context.repo_path / path).exists()]
    context.repo.index.add(existing_paths)
    if not context.repo.index.diff("HEAD"):
        return "스킵: 스테이징된 변경사항 없음"
    commit = context.repo.index.commit(message)
    return commit.hexsha[:12]


# 하위 러너의 커밋 기록에 풀스택 단계명을 붙인다.
def _prefix_commits(prefix: str, commits: list[str]) -> list[str]:
    return [re.sub(r"^\d+\.\s*", f"{prefix}: ", commit) for commit in commits]


# 하위 러너의 진행 상황에 풀스택 단계명을 붙인다.
def _prefix_progress(prefix: str, progress: list[str]) -> list[str]:
    return [f"{line} ({prefix})" for line in progress]


# 풀스택 러너의 최종 실행 결과를 공통 형식으로 만든다.
def _final_result(
    context: DevRunnerContext,
    status: AgentStatus,
    commits: list[str],
    progress: list[str],
    verification: list[str],
    artifacts: list[ArtifactSpec],
    error: str | None = None,
) -> DevRunnerResult:
    return DevRunnerResult(
        status=status,
        summary=(
            f"Fullstack Runner가 {context.branch_name}에서 "
            f"{'구현을 완료했습니다' if status == AgentStatus.SUCCESS else '구현 중 중단되었습니다'}."
        ),
        commits=commits,
        progress=progress,
        verification=verification,
        artifacts=artifacts,
        error=error,
    )
