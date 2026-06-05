import re
from pathlib import Path

from git import GitCommandError, Repo

from agents.base import AgentInput, AgentResult, AgentStatus, ArtifactSpec
from agents.runners.base import DevRunner, DevRunnerContext, DevRunnerResult
from agents.runners.responsibility_runners import (
    APIConnectRunner,
    APIImplementationRunner,
    DBMigrationRunner,
    DDDModelingRunner,
    EventFlowRunner,
    FrontendImplementationRunner,
    RefactoringRunner,
    TestImplementationRunner,
)
from agents.runners.infra_runner import InfraRunner
from orchestrator.core.settings import settings


def _extract_section(markdown: str, heading: str) -> list[str]:
    lines = markdown.splitlines()
    collected: list[str] = []
    in_section = False
    section_level: int | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped[level:].strip()
            if in_section and section_level is not None and level <= section_level:
                break
            if level in {2, 3} and title == heading:
                in_section = True
                section_level = level
                continue
        if in_section and stripped:
            collected.append(stripped)
    return collected


def _extract_metadata_value(markdown: str, key: str) -> str | None:
    for line in _extract_section(markdown, "Harness Metadata"):
        prefix = f"- {key}:"
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    return None


def _extract_issue_type(markdown: str) -> str:
    labels = _extract_metadata_value(markdown, "labels") or ""
    for label in [item.strip() for item in labels.split(",")]:
        if label.startswith("type: "):
            return label.removeprefix("type: ").strip()
    return "unspecified"


def _extract_refactor_request(markdown: str) -> list[str]:
    return _extract_section(markdown, "Human Refactor Request")


def _is_refactor_mode(markdown: str) -> bool:
    return bool(_extract_refactor_request(markdown))


# 이슈 타입에 맞는 개발 브랜치 prefix를 결정한다.
def _branch_prefix(issue_type: str) -> str:
    return {
        "beFeature": "feature(BE)",
        "feFeature": "feature(FE)",
        "fullstackFeature": "feature(FS)",
        "apiConnect": "api-connect",
        "bugfix": "bugfix",
        "hotfix": "hotfix",
        "infra": "infra",
        "config": "config",
        "docs": "docs",
    }.get(issue_type, "task")


def _branch_name(issue_type: str, issue_number: str) -> str:
    number = issue_number if issue_number and issue_number != "unknown" else "no-issue"
    return f"{_branch_prefix(issue_type)}-{number}"


def _feature_name(title: str) -> str:
    cleaned = re.sub(r"\[[^\]]+\]", "", title).strip()
    return cleaned or title.strip() or "작업"


# 이슈 타입별로 커밋 단위와 구현 단계를 정의한다.
def _commit_units(issue_type: str) -> list[tuple[str, str]]:
    if issue_type == "feFeature":
        return [
            ("UI 진입점 추가", "버튼/라우팅 추가"),
            ("화면 구현", "페이지 또는 컴포넌트 구현"),
            ("테스트 추가", "프론트엔드 테스트 코드 추가"),
            ("검증 정리", "빌드와 린트 검증"),
        ]
    if issue_type == "beFeature":
        return [
            ("도메인/UseCase 구현", "도메인과 application 흐름 추가"),
            ("API/인프라 연결", "controller, DTO, persistence 연결"),
            ("테스트 추가", "단위/통합 테스트 코드 추가"),
            ("검증 정리", "서버 빌드와 테스트 검증"),
        ]
    if issue_type == "apiConnect":
        return [
            ("API contract 정리", "request/response schema 확정"),
            ("연동 구현", "FE 호출과 BE endpoint 연결"),
            ("테스트 추가", "contract와 실패 케이스 테스트 추가"),
            ("검증 정리", "FE/BE smoke test 검증"),
        ]
    if issue_type == "fullstackFeature":
        return [
            ("사용자 흐름/API contract 정리", "화면 UX와 request/response schema 확정"),
            ("백엔드 구현", "도메인, usecase, endpoint, persistence 구현"),
            ("프론트엔드 구현", "화면, 상태, 검증 UI 구현"),
            ("연동 구현", "FE API client와 submit 흐름 연결"),
            ("통합 검증", "API 호출과 FE/BE smoke test 검증"),
        ]
    if issue_type in {"bugfix", "hotfix"}:
        return [
            ("재현 테스트 추가", "버그 재현 또는 회귀 테스트 추가"),
            ("수정 구현", "최소 범위 수정"),
            ("검증 정리", "회귀 테스트와 빌드 검증"),
        ]
    return [
        ("변경 범위 구현", "요구사항 기반 최소 변경"),
        ("테스트 추가", "관련 테스트 코드 추가"),
        ("검증 정리", "빌드와 smoke test 검증"),
    ]


# 백엔드 구현 규칙을 반드시 적용해야 하는 이슈 타입인지 판단한다.
def _requires_backend_style(issue_type: str) -> bool:
    return issue_type in {"beFeature", "apiConnect", "fullstackFeature", "bugfix", "hotfix"}


def _backend_style_skill_path() -> Path:
    return Path.home() / ".codex/skills/usecase-orchestration-style/SKILL.md"


def _backend_style_lines(issue_type: str) -> list[str]:
    if not _requires_backend_style(issue_type):
        return ["- backend orchestration style skill: 이 이슈 타입에는 필수가 아닙니다."]

    skill_path = _backend_style_skill_path()
    backend_rules_path = Path("rules/backend-runner.md")
    return [
        "- backend orchestration style skill: required",
        f"- skill_path: `{skill_path}`",
        f"- backend_runner_rules: `{backend_rules_path}`",
        "- localization_rules: `rules/localization.md`",
        "- 컨트롤러는 얇게 유지하고 request/response DTO는 컨트롤러 파일 밖의 별도 파일로 둔다.",
        "- domain/application/port/infrastructure/bootstrap 경계를 지킨다.",
        "- 메인 서비스 메서드는 유스케이스 흐름이 보이게 작성한다.",
        "- 의미 없는 private 메서드와 한 줄 위임 메서드를 남발하지 않는다.",
        "- 정책, 검증, 외부 연동, 상태 변경 책임은 이름이 명확한 외부 책임 객체로 분리한다.",
        "- 책임 객체의 public 메서드에는 한국어 한 줄 주석을 작성한다.",
        "- 클래스와 메서드는 유비쿼터스 언어와 주어/동사/목적어가 드러나게 명명한다.",
        "- 사용자 응답, 프론트엔드 검증 메시지, 내부 예외, 로그는 한국어를 우선 사용한다.",
        "- 사용자 응답 메시지는 안전하고 이해 가능하게 작성하고, 내부 로그에는 who/what/requestData/reason을 남긴다.",
        "- 모든 백엔드 API에는 한국어 Swagger/OpenAPI summary와 description만 작성한다.",
    ]


# Dev Agent가 선택할 수 있는 러너 목록을 우선순위대로 반환한다.
def _dev_runners() -> list[DevRunner]:
    return [
        InfraRunner(),
        DDDModelingRunner(),
        DBMigrationRunner(),
        APIImplementationRunner(),
        FrontendImplementationRunner(),
        APIConnectRunner(),
        EventFlowRunner(),
        RefactoringRunner(),
        TestImplementationRunner(),
    ]


# 이슈 컨텍스트에 맞는 러너를 선택하고 조합 실행 여부를 결정한다.
def _select_runners(context: DevRunnerContext) -> list[DevRunner]:
    return [runner for runner in _dev_runners() if runner.can_handle(context)]


# 현재 체크아웃된 브랜치 이름을 안전하게 반환한다.
def _active_branch_name(repo: Repo) -> str:
    try:
        return repo.active_branch.name
    except TypeError:
        return "detached-head"


# 하네스가 관리하는 이슈 전용 브랜치 이름인지 판단한다.
def _is_managed_issue_branch(branch_name: str) -> bool:
    return branch_name.startswith(
        (
            "feature(BE)-",
            "feature(FE)-",
            "feature(FS)-",
            "api-connect-",
            "bugfix-",
            "hotfix-",
            "infra-",
            "config-",
            "docs-",
            "task-",
        )
    ) or bool(re.fullmatch(r".+-\d+", branch_name))


# 새 개발 브랜치의 기준이 될 base branch 또는 remote ref를 찾는다.
def _resolve_base_ref(repo: Repo, base_branch: str) -> str | None:
    if base_branch in {head.name for head in repo.heads}:
        return base_branch

    remote_ref = f"origin/{base_branch}"
    if "origin" in {remote.name for remote in repo.remotes}:
        try:
            repo.git.fetch("origin", base_branch)
        except GitCommandError:
            pass

    if remote_ref in {ref.name for ref in repo.refs}:
        return remote_ref
    return None


# 개발 브랜치를 checkout하고, 새 브랜치는 항상 설정된 base branch에서 생성한다.
def _checkout_branch(repo_path: Path, branch_name: str, base_branch: str) -> str:
    repo = Repo(repo_path)
    current_branch = _active_branch_name(repo)
    is_dirty = repo.is_dirty(untracked_files=True)

    if is_dirty and current_branch != branch_name:
        return (
            "blocked: target repository has uncommitted changes on another branch "
            f"(current={current_branch}, expected={branch_name}). 먼저 현재 변경사항을 커밋/정리하세요."
        )

    if current_branch not in {branch_name, base_branch} and _is_managed_issue_branch(current_branch):
        return (
            "blocked: target repository is on another managed issue branch "
            f"(current={current_branch}, expected={branch_name}). 먼저 `{base_branch}` 또는 `{branch_name}`으로 이동하세요."
        )

    existing = {head.name for head in repo.heads}
    if branch_name in existing:
        repo.git.checkout(branch_name)
        return "기존 브랜치 체크아웃"

    base_ref = _resolve_base_ref(repo, base_branch)
    if base_ref is None:
        return (
            "blocked: development base branch not found "
            f"(requested_base={base_branch}). 현재 브랜치에서 임의로 새 이슈 브랜치를 만들지 않습니다."
        )

    repo.git.checkout("-b", branch_name, base_ref)
    return f"새 브랜치 생성 (base={base_ref})"


# 구현 diff를 설정된 base branch 기준으로 생성한다.
def _diff_against_base(repo: Repo, base_branch: str) -> str:
    base_ref = _resolve_base_ref(repo, base_branch)
    if base_ref is None:
        base_ref = "HEAD"
    try:
        return repo.git.diff(f"{base_ref}...HEAD")
    except GitCommandError:
        return repo.git.diff("HEAD")


class DevAgent:
    name = "dev"

    def run(self, input_data: AgentInput) -> AgentResult:
        task_dir = input_data.artifacts_root / input_data.task_id / "dev"
        task_dir.mkdir(parents=True, exist_ok=True)
        issue_type = _extract_issue_type(input_data.body)
        issue_number = _extract_metadata_value(input_data.body, "issue_number") or "unknown"
        branch_name = _branch_name(issue_type, issue_number)
        base_branch = settings.development_base_branch
        feature_name = _feature_name(input_data.title)
        commit_units = _commit_units(issue_type)
        backend_style_lines = _backend_style_lines(issue_type)
        refactor_request = _extract_refactor_request(input_data.body)
        is_refactor_mode = _is_refactor_mode(input_data.body)
        repo_path = settings.target_repo_path.expanduser().resolve()

        repo: Repo | None = None
        branch_blocked = False
        commits: list[str] = []
        progress_override: list[str] | None = None
        verification: list[str] = []
        runner_name = "none"
        runner_error: str | None = None
        runner_artifacts: list[ArtifactSpec] = []
        result_status = AgentStatus.SUCCESS

        if repo_path.exists():
            repo = Repo(repo_path)
            branch_status = _checkout_branch(repo_path, branch_name, base_branch)
            branch_blocked = branch_status.startswith("blocked:")
        else:
            branch_status = f"blocked: target repository does not exist: {repo_path}"
            branch_blocked = True

        if repo is not None and not branch_blocked:
            context = DevRunnerContext(
                task_id=input_data.task_id,
                title=input_data.title,
                body=input_data.body,
                issue_type=issue_type,
                issue_number=issue_number,
                branch_name=branch_name,
                feature_name=feature_name,
                repo=repo,
                repo_path=repo_path,
                task_dir=task_dir,
                timeout_seconds=input_data.timeout_seconds,
            )
            runners = _select_runners(context)
            if not runners:
                result_status = AgentStatus.NEEDS_HUMAN
                runner_error = f"issue_type={issue_type}를 처리할 수 있는 Dev Runner가 없습니다."
                verification = [
                    "## runner_selection",
                    "",
                    "- status: needs_human",
                    f"- reason: {runner_error}",
                ]
            else:
                runner_names: list[str] = []
                progress_lines: list[str] = []
                verification_lines: list[str] = []
                errors: list[str] = []
                for runner in runners:
                    runner_names.append(runner.name)
                    runner_result: DevRunnerResult = runner.run(context)
                    if runner_result.status != AgentStatus.SUCCESS:
                        result_status = runner_result.status
                    commits.extend(runner_result.commits)
                    progress_lines.extend(runner_result.progress)
                    verification_lines.extend(runner_result.verification)
                    runner_artifacts.extend(runner_result.artifacts)
                    if runner_result.error:
                        errors.append(f"{runner.name}: {runner_result.error}")

                runner_name = ", ".join(runner_names)
                progress_override = progress_lines
                verification = verification_lines
                runner_error = "; ".join(errors) if errors else None
        elif branch_blocked:
            result_status = AgentStatus.NEEDS_HUMAN
            runner_error = branch_status
            verification = [
                "## Branch Guard",
                "",
                "- status: needs_human",
                f"- reason: {branch_status}",
            ]

        if progress_override is None:
            progress_override = [
                f"- [ ] step {index}: {title}"
                for index, (title, _) in enumerate(commit_units, start=1)
            ]

        if repo is None:
            result_status = AgentStatus.FAILED
            runner_error = branch_status
            verification = [
                "## Runner 선택",
                "",
                "- status: failed",
                f"- reason: {branch_status}",
            ]

        commit_plan = task_dir / "commit-plan.md"
        commit_plan.write_text(
            "\n".join(
                [
                    "# 커밋 계획",
                    "",
                    f"- issue_type: `{issue_type}`",
                    f"- issue_number: `{issue_number}`",
                    f"- branch: `{branch_name}`",
                    f"- base_branch: `{base_branch}`",
                    f"- branch_status: {branch_status}",
                    f"- selected_runner: `{runner_name}`",
                    f"- mode: `{'refactor' if is_refactor_mode else 'develop'}`",
                    "",
                    "## 규칙",
                    "",
                    "- 구현 단계 하나가 끝날 때마다 커밋한다.",
                    "- 빈 커밋은 만들지 않는다.",
                    "- 각 커밋 전에 관련 테스트를 추가하거나 갱신한다.",
                    "",
                    "## Backend Style Skill",
                    *backend_style_lines,
                    "",
                    *(
                        [
                            "## 사람 리팩터링 요청",
                            *refactor_request,
                            "",
                        ]
                        if is_refactor_mode
                        else []
                    ),
                    "## 커밋 단위",
                    *[
                        f"{index}. [{feature_name}] : {message}"
                        for index, (_, message) in enumerate(commit_units, start=1)
                    ],
                    "",
                    "## 실제 커밋",
                    *(commits or ["- 구현 Runner 실행 대기 중"]),
                    "",
                    "## Runner 결과",
                    f"- status: `{result_status.value}`",
                    f"- error: `{runner_error or 'none'}`",
                ]
            ),
            encoding="utf-8",
        )

        status = task_dir / "dev-status.md"
        status.write_text(
            "\n".join(
                [
                    "# Dev 상태",
                    "",
                    f"- branch: `{branch_name}`",
                    f"- base_branch: `{base_branch}`",
                    f"- branch_status: {branch_status}",
                    f"- selected_runner: `{runner_name}`",
                    f"- mode: `{'refactor' if is_refactor_mode else 'develop'}`",
                    f"- current_step: {'완료' if commits else '구현 전 중단'}",
                    "- visibility: GitHub 이슈 댓글과 이 artifact에서 확인합니다.",
                    "",
                    "## 백엔드 스타일",
                    *backend_style_lines,
                    "",
                    *(
                        [
                            "## 사람 리팩터링 요청",
                            *refactor_request,
                            "",
                        ]
                        if is_refactor_mode
                        else []
                    ),
                    "## 진행 상황",
                    *progress_override,
                    "",
                    "## 커밋",
                    *(commits or ["- 구현 Runner 실행 대기 중"]),
                    "",
                    "## Runner 결과",
                    f"- status: `{result_status.value}`",
                    f"- error: `{runner_error or 'none'}`",
                ]
            ),
            encoding="utf-8",
        )

        style_guide = task_dir / "backend-style-checklist.md"
        style_guide.write_text(
            "\n".join(
                [
                    "# 백엔드 스타일 체크리스트",
                    "",
                    f"- mode: `{'refactor' if is_refactor_mode else 'develop'}`",
                    "",
                    *backend_style_lines,
                    "",
                    *(
                        [
                            "## 사람 리팩터링 요청",
                            *refactor_request,
                            "",
                        ]
                        if is_refactor_mode
                        else []
                    ),
                    "## 리뷰 항목",
                    "- [ ] 메인 서비스 메서드가 조회, 검증, 수행/요청, 기록/상태 변경, 반환 흐름을 직접 보여준다.",
                    "- [ ] 정책적 의미가 있는 로직은 명확한 책임 객체로 분리되어 있다.",
                    "- [ ] 책임 객체 public 메서드에는 한국어 한 줄 주석이 있다.",
                    "- [ ] validate/process/handle/execute 같은 모호한 이름을 남발하지 않는다.",
                    "- [ ] 외부 시스템 호출 이름에 외부 경계 또는 제휴사가 드러난다.",
                    "- [ ] 상태 변경, 정합성, 재시도, 멱등성 지점이 코드와 로그에서 추적 가능하다.",
                ]
            ),
            encoding="utf-8",
        )

        patch = task_dir / "implementation.patch"
        if repo is not None:
            diff = _diff_against_base(repo, base_branch)
        else:
            diff = ""
        patch.write_text(
            diff
            or "\n".join(
                [
                    "# 생성된 구현 diff가 없습니다.",
                    f"# task_id={input_data.task_id}",
                    f"# branch={branch_name}",
                ]
            ),
            encoding="utf-8",
        )

        report = task_dir / "test-report.md"
        report.write_text(
            "\n".join(
                [
                    "# Dev 테스트 리포트",
                    "",
                    f"- branch: `{branch_name}`",
                    f"- base_branch: `{base_branch}`",
                    f"- branch_status: {branch_status}",
                    f"- selected_runner: `{runner_name}`",
                    f"- runner_status: `{result_status.value}`",
                    "- test code: 각 구현 단위마다 테스트 코드가 필요합니다.",
                    "- smoke test: 실행된 경우 아래 command 섹션에서 확인하세요.",
                    "- edge case test: 지원되는 경우 생성된 smoke check에 포함됩니다.",
                    "- build: 수동 또는 다음 QA 단계에서 실행합니다.",
                    "",
                    *(verification or ["- 이 이슈 타입에는 자동 검증이 실행되지 않았습니다."]),
                ]
            ),
            encoding="utf-8",
        )

        action_label = "리팩터링" if is_refactor_mode else "개발 구현"
        summary = (
            f"{action_label}이 {runner_name}에 의해 {branch_name}에서 완료되었습니다. 커밋 기록 {len(commits)}개가 생성되었습니다."
            if commits
            else (
                f"{action_label} 러너가 {branch_name}에서 구현 전 중단되었습니다: {runner_error}"
                if runner_error
                else f"{action_label} 브랜치가 준비되었습니다: {branch_name}. 커밋 계획이 생성되었습니다."
            )
        )

        return AgentResult(
            status=result_status,
            summary=summary,
            error=runner_error,
            artifacts=[
                ArtifactSpec("commit-plan", Path(commit_plan)),
                ArtifactSpec("dev-status", Path(status)),
                ArtifactSpec("backend-style-checklist", Path(style_guide)),
                ArtifactSpec("patch", Path(patch)),
                ArtifactSpec("test-report", Path(report)),
                *runner_artifacts,
            ],
        )
