import re
import subprocess
from pathlib import Path

from agents.base import AgentStatus, ArtifactSpec
from agents.runners.base import DevRunnerContext, DevRunnerResult
from agents.runners.codebase_inspector import (
    backend_test_commands,
    extract_api_endpoint,
    extract_frontend_route,
    frontend_test_commands,
    inspect_codebase,
    next_page_path,
    render_codebase_snapshot,
)


class RefactorSplitResult:
    # controller data class 분리 결과와 변경 경로를 보관한다.
    def __init__(self, controller: str, extracted_classes: list[str], changed_paths: list[str]) -> None:
        self.controller = controller
        self.extracted_classes = extracted_classes
        self.changed_paths = changed_paths


class DDDScaffoldSpec:
    # DDD 유스케이스 scaffold 생성에 필요한 이름과 경로 정보를 보관한다.
    def __init__(
        self,
        domain: str,
        domain_class: str,
        usecase_name: str,
        method_name: str,
        policy_method_name: str,
    ) -> None:
        self.domain = domain
        self.domain_class = domain_class
        self.usecase_name = usecase_name
        self.method_name = method_name
        self.policy_method_name = policy_method_name


class LoginImplementationSpec:
    # 로그인 API 구현에 필요한 경로, package, endpoint 정보를 보관한다.
    def __init__(self, method: str, path: str, base_package: str) -> None:
        self.method = method
        self.path = path
        self.base_package = base_package
        self.domain_package = f"{base_package}.domain.member"
        self.application_package = f"{base_package}.application.auth"
        self.persistence_package = f"{base_package}.infrastructure.persistence.member"
        self.bootstrap_package = f"{base_package}.bootstrap.auth"


class ResponsibilityCapabilityRunner:
    name = "responsibility_capability_runner"
    responsibility = "정의되지 않은 책임"
    supported_issue_types: set[str] = set()

    # 이 책임 러너가 현재 이슈 타입에서 필요한지 판단한다.
    def can_handle(self, context: DevRunnerContext) -> bool:
        return context.issue_type in self.supported_issue_types

    # 현재 책임 러너의 자동 구현 가능 여부를 보고하고 안전하게 중단한다.
    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        report = _write_capability_report(
            context=context,
            runner_name=self.name,
            responsibility=self.responsibility,
        )
        return DevRunnerResult(
            status=AgentStatus.NEEDS_HUMAN,
            summary=f"{self.name}가 필요한 책임을 식별했지만 아직 자동 구현 capability가 없습니다.",
            progress=[
                f"- [x] {self.name} 필요성 확인",
                f"- [ ] {self.responsibility} 자동 구현 capability 확보",
            ],
            verification=[
                f"## {self.name}",
                "",
                "- status: needs_human",
                f"- responsibility: {self.responsibility}",
                "- reason: 아직 이 책임 러너는 자동 구현 대신 capability gate로만 동작합니다.",
            ],
            artifacts=[ArtifactSpec(self.name, report)],
            error=f"{self.name}: 아직 자동 구현 capability가 없습니다. {report.name}을 확인하세요.",
        )


class DDDModelingRunner(ResponsibilityCapabilityRunner):
    name = "ddd_modeling_runner"
    responsibility = "도메인 모델, 정책, 유스케이스 흐름 구현"
    supported_issue_types = {"beFeature", "fullstackFeature", "bugfix", "hotfix"}

    # 명시된 API 요구사항을 기준으로 DDD application 유스케이스 scaffold를 생성한다.
    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        login_spec = _login_spec_from_context(context)
        if login_spec is not None:
            changed_paths = _write_login_domain_application(context, login_spec)
            commit_hash = _stage_and_commit(
                context,
                changed_paths,
                f"[{context.feature_name}] : 로그인 도메인과 유스케이스 구현",
            )
            report = context.task_dir / f"{self.name}.md"
            snapshot = inspect_codebase(context)
            report.write_text(
                "\n".join(
                    [
                        f"# {self.name}",
                        "",
                        f"- branch: `{context.branch_name}`",
                        f"- issue_type: `{context.issue_type}`",
                        "- status: success",
                        "- domain: `member/auth`",
                        "- service: `AuthenticationService`",
                        f"- commit: `{commit_hash}`",
                        f"- changed_paths: `{', '.join(changed_paths)}`",
                        "",
                        *render_codebase_snapshot(snapshot),
                        "## Applied Rules",
                        "",
                        "- Bix-biscuit modules/domain, application, port 구조를 기준으로 생성했습니다.",
                        "- `{code,message}` 에러 응답을 전제로 application exception을 분리했습니다.",
                        "- Refresh Token 저장은 `RefreshTokenStore` port로 추상화했습니다.",
                        "- 책임 객체 public method에는 한국어 한 줄 주석을 작성했습니다.",
                    ]
                ),
                encoding="utf-8",
            )
            return DevRunnerResult(
                status=AgentStatus.SUCCESS,
                summary="로그인 도메인, application usecase, port를 Bix 스타일로 구현했습니다.",
                commits=[f"1. {commit_hash} [{context.feature_name}] : 로그인 도메인과 유스케이스 구현"],
                progress=[
                    "- [x] 로그인 API 요구사항 분석",
                    "- [x] Member 도메인 모델 구현",
                    "- [x] AuthenticationInputPort와 AuthenticationService 구현",
                    "- [x] Repository/JWT/RefreshToken port 정의",
                    "- [x] 로그인 실패 예외 정의",
                ],
                verification=[
                    f"## {self.name}",
                    "",
                    "- status: success",
                    "- service: `AuthenticationService`",
                    "- port: `MemberRepository`, `JwtTokenIssuer`, `RefreshTokenStore`",
                ],
                artifacts=[ArtifactSpec(self.name, report)],
            )

        spec = _ddd_model_from_context(context)
        if spec is None:
            return super().run(context)

        report = context.task_dir / f"{self.name}.md"
        snapshot = inspect_codebase(context)
        report.write_text(
            "\n".join(
                [
                    f"# {self.name}",
                    "",
                    f"- branch: `{context.branch_name}`",
                    f"- issue_type: `{context.issue_type}`",
                    f"- responsibility: {self.responsibility}",
                    f"- domain: `{spec.domain}`",
                    f"- usecase: `{spec.usecase_name}`",
                    f"- method: `{spec.method_name}`",
                    "- commit: 생성하지 않음",
                    "- changed_paths: 없음",
                    "",
                    *render_codebase_snapshot(snapshot),
                    "## Applied Skill",
                    "",
                    "- skill: `usecase-orchestration-style`",
                    "- 메인 서비스는 유스케이스 orchestration 흐름이 보이도록 생성합니다.",
                    "- 정책 검증 책임은 별도 책임 객체로 분리합니다.",
                    "- 책임 객체의 public method에는 한국어 한 줄 주석을 남깁니다.",
                    "",
                    "## Capability",
                    "",
                    "- status: needs_human",
                    "- DDD application layer 자동 구현 capability가 부족한 경우 저장소 scaffold를 생성하지 않습니다.",
                    "- 불완전한 TODO 파일과 불필요한 커밋을 남기지 않기 위해 artifact 보고서만 생성합니다.",
                ]
            ),
            encoding="utf-8",
        )
        return DevRunnerResult(
            status=AgentStatus.NEEDS_HUMAN,
            summary=f"{self.name}가 {spec.usecase_name} 구현 필요성을 식별했지만 자동 구현 전 사람 검토가 필요합니다.",
            commits=[],
            progress=[
                "- [x] API 요구사항에서 도메인과 유스케이스 이름 추출",
                "- [ ] DDD application 구현 capability 확보",
                "- [ ] 상세 도메인 정책과 저장소 연결 구현",
            ],
            verification=[
                f"## {self.name}",
                "",
                "- status: needs_human",
                f"- domain: `{spec.domain}`",
                f"- usecase: `{spec.usecase_name}`",
                "- reason: 불완전한 scaffold를 남기지 않기 위해 자동 구현을 중단했습니다.",
            ],
            artifacts=[ArtifactSpec(self.name, report)],
            error=f"{self.name}: DDD application 자동 구현 capability가 부족합니다. {report.name}을 확인하세요.",
        )


class DBMigrationRunner(ResponsibilityCapabilityRunner):
    name = "db_migration_runner"
    responsibility = "DB schema, nullable, unique, index, migration 구현"
    supported_issue_types = {"beFeature", "fullstackFeature", "config", "infra"}

    # 명시된 DDL이 있을 때만 DB migration 책임을 수행한다.
    def can_handle(self, context: DevRunnerContext) -> bool:
        return context.issue_type in self.supported_issue_types and _extract_sql_ddl(context) is not None

    # 이슈 본문이나 Plan 산출물에 명시된 SQL DDL을 Flyway migration으로 생성한다.
    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        ddl = _extract_sql_ddl(context)
        if ddl is None:
            return super().run(context)

        migration_path = _next_migration_path(context)
        _write_text(migration_path, ddl.rstrip() + "\n")
        relative = _relative(context, migration_path)
        commit_hash = _stage_and_commit(
            context,
            [relative],
            f"[{context.feature_name}] : DB migration 추가",
        )
        report = context.task_dir / f"{self.name}.md"
        snapshot = inspect_codebase(context)
        report.write_text(
            "\n".join(
                [
                    f"# {self.name}",
                    "",
                    f"- branch: `{context.branch_name}`",
                    f"- issue_type: `{context.issue_type}`",
                    f"- responsibility: {self.responsibility}",
                    f"- migration: `{relative}`",
                    f"- commit: `{commit_hash}`",
                    "",
                    *render_codebase_snapshot(snapshot),
                    "## Applied DDL",
                    "",
                    "```sql",
                    ddl.rstrip(),
                    "```",
                ]
            ),
            encoding="utf-8",
        )
        return DevRunnerResult(
            status=AgentStatus.SUCCESS,
            summary=f"{self.name}가 명시된 DDL을 migration으로 생성했습니다.",
            commits=[f"1. {commit_hash} [{context.feature_name}] : DB migration 추가"],
            progress=["- [x] DDL 추출", "- [x] Flyway migration 생성"],
            verification=[
                f"## {self.name}",
                "",
                "- status: success",
                f"- migration: `{relative}`",
            ],
            artifacts=[ArtifactSpec(self.name, report)],
        )


class APIImplementationRunner(ResponsibilityCapabilityRunner):
    name = "api_implementation_runner"
    responsibility = "API endpoint, request/response, application 연결 구현"
    supported_issue_types = {"beFeature", "fullstackFeature"}

    # 명시된 API endpoint를 기준으로 contract 문서를 생성하고 구현 경계를 기록한다.
    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        endpoint = extract_api_endpoint(f"{context.title}\n{context.body}")
        if endpoint is None:
            return super().run(context)

        method, path = endpoint
        login_spec = _login_spec_from_context(context)
        if login_spec is not None:
            contract_path = _api_contract_path(context, method, path)
            changed_paths = [_relative(context, contract_path)] if contract_path.exists() else []
            changed_paths.extend(_write_login_api_infrastructure(context, login_spec))
            commit_hash = _stage_and_commit(
                context,
                changed_paths,
                f"[{context.feature_name}] : 로그인 API와 persistence adapter 구현",
            )
            report = context.task_dir / f"{self.name}.md"
            snapshot = inspect_codebase(context)
            report.write_text(
                "\n".join(
                    [
                        f"# {self.name}",
                        "",
                        f"- branch: `{context.branch_name}`",
                        f"- issue_type: `{context.issue_type}`",
                        "- status: success",
                        f"- endpoint: `{method} {path}`",
                        f"- commit: `{commit_hash}`",
                        f"- changed_paths: `{', '.join(changed_paths)}`",
                        "",
                        *render_codebase_snapshot(snapshot),
                        "## Applied Rules",
                        "",
                        "- Controller는 얇게 유지하고 request/response DTO를 별도 파일로 분리했습니다.",
                        "- JPA 구현은 `JpaMemberRepository` + `MemberPersistenceAdapter` 패턴을 사용했습니다.",
                        "- Redis 구현은 `RefreshTokenStore` port와 `RedisRefreshTokenAdapter`로 연결했습니다.",
                        "- 사용자 오류 응답은 `{code,message}` 한국어 포맷으로 반환합니다.",
                    ]
                ),
                encoding="utf-8",
            )
            return DevRunnerResult(
                status=AgentStatus.SUCCESS,
                summary=f"{method} {path} API와 persistence/Redis adapter를 구현했습니다.",
                commits=[f"1. {commit_hash} [{context.feature_name}] : 로그인 API와 persistence adapter 구현"],
                progress=[
                    "- [x] LoginRequest/LoginResponse DTO 구현",
                    "- [x] AuthController 구현",
                    "- [x] ApiErrorResponse와 GlobalExceptionHandler 구현",
                    "- [x] Member JPA Entity/Repository/Adapter 구현",
                    "- [x] JwtTokenIssuer/RefreshTokenStore adapter 구현",
                ],
                verification=[
                    f"## {self.name}",
                    "",
                    "- status: success",
                    f"- endpoint: `{method} {path}`",
                    "- error_response: `{code,message}`",
                ],
                artifacts=[ArtifactSpec(self.name, report)],
            )

        report = context.task_dir / f"{self.name}.md"
        snapshot = inspect_codebase(context)
        report.write_text(
            "\n".join(
                [
                    f"# {self.name}",
                    "",
                    f"- branch: `{context.branch_name}`",
                    f"- issue_type: `{context.issue_type}`",
                    f"- responsibility: {self.responsibility}",
                    f"- endpoint: `{method} {path}`",
                    "- contract: 저장소에 생성하지 않음",
                    "- commit: 생성하지 않음",
                    "",
                    *render_codebase_snapshot(snapshot),
                    "## Capability",
                    "",
                    "- status: needs_human",
                    "- API 자동 구현 capability가 부족한 경우 저장소 contract 초안을 생성하지 않습니다.",
                    "- 불완전한 API 문서와 불필요한 커밋을 남기지 않기 위해 artifact 보고서만 생성합니다.",
                ]
            ),
            encoding="utf-8",
        )
        return DevRunnerResult(
            status=AgentStatus.NEEDS_HUMAN,
            summary=f"{self.name}가 {method} {path} 구현 필요성을 식별했지만 자동 구현 전 사람 검토가 필요합니다.",
            commits=[],
            progress=[
                "- [x] API endpoint 추출",
                "- [ ] API 구현 capability 확보",
                "- [ ] Controller/DTO/InputPort/Service 구현",
            ],
            verification=[
                f"## {self.name}",
                "",
                "- status: needs_human",
                f"- endpoint: `{method} {path}`",
                "- reason: 불완전한 contract/scaffold를 남기지 않기 위해 자동 구현을 중단했습니다.",
            ],
            artifacts=[ArtifactSpec(self.name, report)],
            error=f"{self.name}: API 자동 구현 capability가 부족합니다. {report.name}을 확인하세요.",
        )


class FrontendImplementationRunner(ResponsibilityCapabilityRunner):
    name = "frontend_implementation_runner"
    responsibility = "화면, 상태, 폼, 사용자 메시지 구현"
    supported_issue_types = {"feFeature", "fullstackFeature"}

    # route가 명확한 프론트엔드 작업은 안전한 page scaffold까지 생성한다.
    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        route = extract_frontend_route(f"{context.title}\n{context.body}")
        existing_changes = _frontend_changed_paths(context)
        if existing_changes:
            return self._return_existing_frontend_changes(context, existing_changes)
        if route is None:
            return super().run(context)

        page_path = next_page_path(context.repo_path, route)
        report = context.task_dir / f"{self.name}.md"
        snapshot = inspect_codebase(context)
        changed_paths: list[str] = []
        commits: list[str] = []

        if not page_path.exists():
            _write_text(page_path, _frontend_page_scaffold(context, route))
            relative = _relative(context, page_path)
            changed_paths.append(relative)
            commit_hash = _stage_and_commit(
                context,
                changed_paths,
                f"[{context.feature_name}] : {route} 화면 scaffold 추가",
            )
            commits.append(f"1. {commit_hash} [{context.feature_name}] : {route} 화면 scaffold 추가")

        report.write_text(
            "\n".join(
                [
                    f"# {self.name}",
                    "",
                    f"- branch: `{context.branch_name}`",
                    f"- issue_type: `{context.issue_type}`",
                    f"- responsibility: {self.responsibility}",
                    f"- route: `{route}`",
                    f"- page_path: `{page_path}`",
                    f"- changed_paths: `{', '.join(changed_paths) if changed_paths else 'none'}`",
                    "",
                    *render_codebase_snapshot(snapshot),
                    "## Capability",
                    "",
                    "- status: partial",
                    "- 명확한 route가 있는 경우 Next.js page scaffold를 생성합니다.",
                    "- 세부 UI, 상태, API 연동은 아직 사람이 검토해야 합니다.",
                ]
            ),
            encoding="utf-8",
        )

        return DevRunnerResult(
            status=AgentStatus.NEEDS_HUMAN,
            summary=f"{self.name}가 {route} 화면 scaffold를 점검했습니다.",
            commits=commits,
            progress=[
                f"- [x] {self.name} route 분석",
                f"- [{'x' if changed_paths else ' '}] {route} page scaffold 생성",
                "- [ ] 세부 UI/상태/API 연동 구현",
            ],
            verification=[
                f"## {self.name}",
                "",
                "- status: needs_human",
                f"- route: `{route}`",
                "- reason: scaffold 이후 상세 화면 구현은 아직 사람 검토가 필요합니다.",
            ],
            artifacts=[ArtifactSpec(self.name, report)],
            error=f"{self.name}: scaffold 이후 상세 구현 capability가 부족합니다. {report.name}을 확인하세요.",
        )

    # 이미 존재하는 프론트엔드 변경을 책임 범위의 구현 결과로 기록한다.
    def _return_existing_frontend_changes(
        self,
        context: DevRunnerContext,
        changed_paths: list[str],
    ) -> DevRunnerResult:
        report = context.task_dir / f"{self.name}.md"
        snapshot = inspect_codebase(context)
        report.write_text(
            "\n".join(
                [
                    f"# {self.name}",
                    "",
                    f"- branch: `{context.branch_name}`",
                    f"- issue_type: `{context.issue_type}`",
                    f"- responsibility: {self.responsibility}",
                    "- status: success",
                    f"- changed_paths: `{', '.join(changed_paths)}`",
                    "",
                    *render_codebase_snapshot(snapshot),
                    "## Capability",
                    "",
                    "- 현재 브랜치에 이미 존재하는 프론트엔드 변경을 구현 결과로 확인했습니다.",
                    "- 실제 품질 판정은 Test Implementation Runner의 빌드와 smoke test 결과로 이어서 검증합니다.",
                ]
            ),
            encoding="utf-8",
        )
        return DevRunnerResult(
            status=AgentStatus.SUCCESS,
            summary=f"{self.name}가 기존 프론트엔드 변경 {len(changed_paths)}개를 확인했습니다.",
            commits=["- 기존 커밋의 프론트엔드 변경을 확인했습니다."],
            progress=[
                "- [x] 현재 브랜치 프론트엔드 변경 확인",
                "- [x] 테스트 러너로 검증 위임",
            ],
            verification=[
                f"## {self.name}",
                "",
                "- status: success",
                f"- changed_paths: `{', '.join(changed_paths)}`",
            ],
            artifacts=[ArtifactSpec(self.name, report)],
        )


class APIConnectRunner(ResponsibilityCapabilityRunner):
    name = "api_connect_runner"
    responsibility = "프론트엔드 요청과 백엔드 API contract 연결"
    supported_issue_types = {"apiConnect", "fullstackFeature"}

    # 로그인 API 연동처럼 contract와 기존 화면이 명확한 경우 프론트엔드 API 연결을 수행한다.
    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        if _is_reissue_api_connect_request(context):
            changed_paths = _connect_reissue_api(context)
            commit_hash = _stage_and_commit(
                context,
                changed_paths,
                f"[{context.feature_name}] : Access Token 자동 재발급 연동",
            )
            report = context.task_dir / f"{self.name}.md"
            snapshot = inspect_codebase(context)
            report.write_text(
                "\n".join(
                    [
                        f"# {self.name}",
                        "",
                        f"- branch: `{context.branch_name}`",
                        f"- issue_type: `{context.issue_type}`",
                        "- status: success",
                        "- api: `POST /api/auth/reissue`",
                        f"- commit: `{commit_hash}`",
                        f"- changed_paths: `{', '.join(changed_paths)}`",
                        "",
                        *render_codebase_snapshot(snapshot),
                        "## Capability",
                        "",
                        "- 401 응답 시 Refresh Token으로 Access Token을 재발급합니다.",
                        "- 재발급 성공 시 토큰을 갱신하고 원래 요청을 1회 재시도합니다.",
                        "- 재발급 실패 시 토큰을 제거하고 한국어 안내 메시지를 표시합니다.",
                        "- 무한 재시도를 방지합니다.",
                    ]
                ),
                encoding="utf-8",
            )
            return DevRunnerResult(
                status=AgentStatus.SUCCESS,
                summary="Access Token 만료 시 Refresh Token 자동 재발급 흐름을 연결했습니다.",
                commits=[f"1. {commit_hash} [{context.feature_name}] : Access Token 자동 재발급 연동"],
                progress=[
                    "- [x] Refresh Token 재발급 API contract 확인",
                    "- [x] 프론트엔드 인증 API client 재발급 흐름 확인",
                    "- [x] 재발급 성공 시 토큰 갱신과 원래 요청 1회 재시도 확인",
                    "- [x] 재발급 실패 시 안전한 로그아웃 처리 확인",
                ],
                verification=[
                    f"## {self.name}",
                    "",
                    "- status: success",
                    "- api: `POST /api/auth/reissue`",
                    "- retry: `401 -> reissue -> retry once`",
                ],
                artifacts=[ArtifactSpec(self.name, report)],
            )

        if not _is_login_api_connect_request(context):
            return super().run(context)

        changed_paths = _connect_login_api(context)
        commit_hash = _stage_and_commit(
            context,
            changed_paths,
            f"[{context.feature_name}] : 로그인 API 프론트엔드 연동",
        )
        report = context.task_dir / f"{self.name}.md"
        snapshot = inspect_codebase(context)
        report.write_text(
            "\n".join(
                [
                    f"# {self.name}",
                    "",
                    f"- branch: `{context.branch_name}`",
                    f"- issue_type: `{context.issue_type}`",
                    "- status: success",
                    "- api: `POST /api/auth/login`",
                    f"- commit: `{commit_hash}`",
                    f"- changed_paths: `{', '.join(changed_paths)}`",
                    "",
                    *render_codebase_snapshot(snapshot),
                    "## Capability",
                    "",
                    "- 로그인 모달 submit handler를 백엔드 로그인 API 호출로 연결합니다.",
                    "- 로그인 성공 시 access token과 refresh token을 localStorage에 저장합니다.",
                    "- 로그인 실패 시 백엔드의 한국어 오류 메시지를 화면에 표시합니다.",
                ]
            ),
            encoding="utf-8",
        )
        return DevRunnerResult(
            status=AgentStatus.SUCCESS,
            summary="로그인 화면과 로그인 API를 연결했습니다.",
            commits=[f"1. {commit_hash} [{context.feature_name}] : 로그인 API 프론트엔드 연동"],
            progress=[
                "- [x] 로그인 API contract 확인",
                "- [x] 프론트엔드 API client 생성",
                "- [x] 로그인 모달 submit handler 연동",
                "- [x] 성공/실패 사용자 메시지 연결",
            ],
            verification=[
                f"## {self.name}",
                "",
                "- status: success",
                "- api: `POST /api/auth/login`",
                "- storage: `myMentalCare.accessToken`, `myMentalCare.refreshToken`",
            ],
            artifacts=[ArtifactSpec(self.name, report)],
        )


class EventFlowRunner(ResponsibilityCapabilityRunner):
    name = "event_flow_runner"
    responsibility = "비동기 이벤트, 실시간 흐름, 상태 전이 구현"
    supported_issue_types = {"fullstackFeature", "beFeature"}

    # 이벤트성 키워드가 있는 경우에만 이 책임 러너를 활성화한다.
    def can_handle(self, context: DevRunnerContext) -> bool:
        haystack = f"{context.title}\n{context.body}".lower()
        has_event_flow = any(
            keyword in haystack
            for keyword in ["event", "websocket", "chat", "message", "알림", "채팅", "실시간", "이벤트"]
        )
        return super().can_handle(context) and has_event_flow


class RefactoringRunner(ResponsibilityCapabilityRunner):
    name = "refactoring_runner"
    responsibility = "기존 구현의 책임 분리와 구조 개선"
    supported_issue_types = {
        "beFeature",
        "feFeature",
        "fullstackFeature",
        "apiConnect",
        "bugfix",
        "hotfix",
    }

    # 사람의 리팩터링 요청이 있는 경우에만 이 책임 러너를 활성화한다.
    def can_handle(self, context: DevRunnerContext) -> bool:
        return super().can_handle(context) and "## Human Refactor Request" in context.body

    # 명확한 controller data class 분리 요청은 자동으로 별도 Kotlin 파일로 분리한다.
    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        if not _requests_controller_data_class_split(context.body):
            return super().run(context)

        results = _split_controller_data_classes(context)
        report = context.task_dir / f"{self.name}.md"
        snapshot = inspect_codebase(context)
        changed_paths = sorted({path for result in results for path in result.changed_paths})
        commit_hash = "no commit"
        if changed_paths:
            commit_hash = _stage_and_commit(
                context,
                changed_paths,
                f"[{context.feature_name}] : controller data class 분리",
            )

        report.write_text(
            "\n".join(
                [
                    f"# {self.name}",
                    "",
                    f"- branch: `{context.branch_name}`",
                    f"- issue_type: `{context.issue_type}`",
                    f"- responsibility: {self.responsibility}",
                    f"- commit: `{commit_hash}`",
                    f"- changed_paths: `{', '.join(changed_paths) if changed_paths else 'none'}`",
                    "",
                    *render_codebase_snapshot(snapshot),
                    "## Refactoring Result",
                    "",
                    *[
                        line
                        for result in results
                        for line in _format_refactor_result(result)
                    ],
                ]
            ),
            encoding="utf-8",
        )

        if not changed_paths:
            return DevRunnerResult(
                status=AgentStatus.NEEDS_HUMAN,
                summary="Controller 내부 data class 분리 대상이 없습니다.",
                progress=["- [ ] Controller 내부 data class 탐지"],
                verification=[
                    f"## {self.name}",
                    "",
                    "- status: needs_human",
                    "- reason: 분리할 controller 내부 data class를 찾지 못했습니다.",
                ],
                artifacts=[ArtifactSpec(self.name, report)],
                error=f"{self.name}: 분리할 controller 내부 data class를 찾지 못했습니다.",
            )

        return DevRunnerResult(
            status=AgentStatus.SUCCESS,
            summary=f"Controller 내부 data class {len(results)}개를 별도 파일로 분리했습니다.",
            commits=[f"1. {commit_hash} [{context.feature_name}] : controller data class 분리"],
            progress=["- [x] Controller 내부 data class 탐지", "- [x] 별도 Kotlin 파일 분리"],
            verification=[
                f"## {self.name}",
                "",
                "- status: success",
                f"- changed_paths: `{', '.join(changed_paths)}`",
            ],
            artifacts=[ArtifactSpec(self.name, report)],
        )


class TestImplementationRunner(ResponsibilityCapabilityRunner):
    name = "test_implementation_runner"
    responsibility = "단위, 통합, smoke 테스트 작성과 실행"
    supported_issue_types = {
        "beFeature",
        "feFeature",
        "fullstackFeature",
        "apiConnect",
        "bugfix",
        "hotfix",
        "config",
        "infra",
    }

    # 현재 코드베이스에 존재하는 테스트 명령을 선택해 실제 검증을 실행한다.
    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        snapshot = inspect_codebase(context)
        commands = _test_commands_for_context(context, snapshot)
        report = context.task_dir / f"{self.name}.md"

        if not commands:
            report.write_text(
                "\n".join(
                    [
                        f"# {self.name}",
                        "",
                        f"- branch: `{context.branch_name}`",
                        f"- issue_type: `{context.issue_type}`",
                        "",
                        *render_codebase_snapshot(snapshot),
                        "## Test Capability",
                        "",
                        "- status: needs_human",
                        "- 실행 가능한 테스트 명령을 찾지 못했습니다.",
                    ]
                ),
                encoding="utf-8",
            )
            return DevRunnerResult(
                status=AgentStatus.NEEDS_HUMAN,
                summary="실행 가능한 테스트 명령을 찾지 못했습니다.",
                progress=["- [ ] 테스트 명령 식별"],
                verification=["## test_implementation_runner", "", "- status: needs_human"],
                artifacts=[ArtifactSpec(self.name, report)],
                error=f"{self.name}: 실행 가능한 테스트 명령을 찾지 못했습니다.",
            )

        command_results = [_run_command(command, _command_cwd(context, command), context.timeout_seconds) for command in commands]
        all_passed = all(exit_code == 0 for command, exit_code, _, _ in command_results)
        report.write_text(
            "\n".join(
                [
                    f"# {self.name}",
                    "",
                    f"- branch: `{context.branch_name}`",
                    f"- issue_type: `{context.issue_type}`",
                    f"- result: `{'pass' if all_passed else 'fail'}`",
                    "",
                    *render_codebase_snapshot(snapshot),
                    *[
                        line
                        for command, exit_code, stdout, stderr in command_results
                        for line in _format_command_result(command, exit_code, stdout, stderr)
                    ],
                ]
            ),
            encoding="utf-8",
        )
        return DevRunnerResult(
            status=AgentStatus.SUCCESS if all_passed else AgentStatus.FAILED,
            summary=f"테스트 명령 {len(commands)}개를 실행했고 {'통과했습니다' if all_passed else '실패했습니다'}.",
            progress=[f"- [{'x' if all_passed else ' '}] 테스트 명령 {len(commands)}개 실행"],
            verification=[
                "## test_implementation_runner",
                "",
                f"- result: `{'pass' if all_passed else 'fail'}`",
                *[
                    f"- command: `{' '.join(command)}`, exit_code={exit_code}"
                    for command, exit_code, _, _ in command_results
                ],
            ],
            artifacts=[ArtifactSpec(self.name, report)],
            error=None if all_passed else f"{self.name}: 테스트 명령이 실패했습니다. {report.name}을 확인하세요.",
        )


# 현재 책임 러너의 한계와 필요한 사람 판단을 artifact로 남긴다.
def _write_capability_report(
    context: DevRunnerContext,
    runner_name: str,
    responsibility: str,
) -> Path:
    report = context.task_dir / f"{runner_name}.md"
    snapshot = inspect_codebase(context)
    report.write_text(
        "\n".join(
            [
                f"# {runner_name}",
                "",
                f"- branch: `{context.branch_name}`",
                f"- issue_type: `{context.issue_type}`",
                f"- responsibility: {responsibility}",
                "",
                *render_codebase_snapshot(snapshot),
                "## Capability Gate",
                "",
                "- status: needs_human",
                "- 현재 이 책임 러너는 범용 구조상 필요한 책임을 식별하지만 자동 구현은 아직 수행하지 않습니다.",
                "- 가짜 성공을 만들지 않기 위해 구현을 중단합니다.",
                "",
                "## 다음 업그레이드 방향",
                "",
                "- 이 책임의 입력 artifact 형식을 고정한다.",
                "- 코드베이스 분석 규칙을 추가한다.",
                "- 수정 가능한 파일 범위와 테스트 명령을 명확히 한다.",
                "- 성공/실패 판정 기준을 테스트로 고정한다.",
            ]
        ),
        encoding="utf-8",
    )
    return report


# UTF-8 텍스트 파일을 생성하고 상위 디렉토리를 보장한다.
def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# 저장소 기준 상대 경로를 반환한다.
def _relative(context: DevRunnerContext, path: Path) -> str:
    return str(path.relative_to(context.repo_path))


# 변경 파일을 스테이징하고 실제 변경이 있을 때만 커밋한다.
def _stage_and_commit(context: DevRunnerContext, paths: list[str], message: str) -> str:
    existing_paths = [path for path in paths if (context.repo_path / path).exists()]
    if not existing_paths:
        return "no commit"
    context.repo.index.add(existing_paths)
    if not context.repo.index.diff("HEAD"):
        return "스킵: 스테이징된 변경사항 없음"
    commit = context.repo.index.commit(message)
    return commit.hexsha[:12]


# 현재 브랜치에서 기준 브랜치 대비 프론트엔드 변경 파일을 찾는다.
def _frontend_changed_paths(context: DevRunnerContext) -> list[str]:
    candidates = ["stage", "origin/stage", "main", "origin/main"]
    for base in candidates:
        exit_code, stdout = _git_name_only(context, base)
        if exit_code == 0:
            return sorted(path for path in stdout.splitlines() if path.startswith("apps/web/"))
    return []


# 기준 브랜치 대비 변경 파일 목록을 git으로 조회한다.
def _git_name_only(context: DevRunnerContext, base: str) -> tuple[int, str]:
    completed = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        cwd=context.repo_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return completed.returncode, completed.stdout


# route 기반 Next.js page scaffold 내용을 만든다.
def _frontend_page_scaffold(context: DevRunnerContext, route: str) -> str:
    return "\n".join(
        [
            "export default function HarnessGeneratedPage() {",
            "  return (",
            '    <main className="min-h-screen bg-background px-6 py-10 text-foreground">',
            '      <section className="mx-auto flex w-full max-w-3xl flex-col gap-4">',
            f'        <p className="text-sm font-medium text-muted-foreground">{route}</p>',
            f'        <h1 className="text-3xl font-semibold tracking-normal">{context.feature_name}</h1>',
            '        <p className="text-muted-foreground">',
            "          이 화면은 AI Harness가 route를 기준으로 생성한 초기 scaffold입니다.",
            "          실제 UX, 상태 관리, API 연동은 후속 구현에서 구체화해야 합니다.",
            "        </p>",
            "      </section>",
            "    </main>",
            "  )",
            "}",
            "",
        ]
    )


# API 요구사항에서 DDD scaffold 생성에 필요한 도메인과 유스케이스 이름을 추론한다.
def _ddd_model_from_context(context: DevRunnerContext) -> DDDScaffoldSpec | None:
    endpoint = extract_api_endpoint(f"{context.title}\n{context.body}")
    if endpoint is None:
        return None

    method, path = endpoint
    segments = [segment for segment in path.split("/") if segment and segment != "api"]
    if not segments:
        return None

    domain = _singular_domain(segments[0])
    domain_class = _pascal_case(domain)
    operation = _operation_name(method, segments, domain)
    usecase_name = f"{operation}{domain_class}"
    return DDDScaffoldSpec(
        domain=domain,
        domain_class=domain_class,
        usecase_name=usecase_name,
        method_name=_camel_case(usecase_name),
        policy_method_name=f"validate{domain_class}Can{operation}",
    )


# 복수형 path segment를 도메인 단수 표현으로 변환한다.
def _singular_domain(value: str) -> str:
    aliases = {
        "members": "member",
        "studies": "study",
        "comments": "comment",
        "messages": "message",
        "notifications": "notification",
        "reviews": "review",
        "notes": "note",
    }
    if value in aliases:
        return aliases[value]
    if value.endswith("ies") and len(value) > 3:
        return f"{value[:-3]}y"
    if value.endswith("s") and len(value) > 1:
        return value[:-1]
    return value


# API method와 path를 유스케이스 동사로 변환한다.
def _operation_name(method: str, segments: list[str], domain: str) -> str:
    action_segment = segments[-1]
    action_aliases = {
        "signup": "Register",
        "login": "Login",
        "logout": "Logout",
        "invite": "Invite",
        "join": "Join",
        "leave": "Leave",
        "publish": "Publish",
        "cancel": "Cancel",
        "approve": "Approve",
        "reject": "Reject",
    }
    if action_segment in action_aliases:
        return action_aliases[action_segment]

    domain_plural = f"{domain}s"
    if action_segment in {domain, domain_plural}:
        method_aliases = {
            "POST": "Create",
            "GET": "Read",
            "PUT": "Update",
            "PATCH": "Update",
            "DELETE": "Delete",
        }
        return method_aliases.get(method.upper(), "Change")

    return _pascal_case(action_segment)


# kebab, snake, path 문자열을 PascalCase로 변환한다.
def _pascal_case(value: str) -> str:
    words = [word for word in re.split(r"[^0-9a-zA-Z가-힣]+", value) if word]
    return "".join(word[:1].upper() + word[1:] for word in words) or "Usecase"


# PascalCase 이름을 camelCase 메서드 이름으로 변환한다.
def _camel_case(value: str) -> str:
    if not value:
        return value
    return value[:1].lower() + value[1:]


# 현재 서버의 bootstrap 모듈 root를 찾는다.
def _bootstrap_module_root(context: DevRunnerContext) -> Path:
    bootstrap_root = context.repo_path / "apps/server/modules/bootstrap"
    candidates = sorted(path for path in bootstrap_root.iterdir() if path.is_dir()) if bootstrap_root.exists() else []
    if candidates:
        return candidates[0]
    return bootstrap_root / "app"


# Kotlin 파일에서 첫 package 선언을 찾아 반환한다.
def _first_package_under(root: Path) -> str | None:
    if not root.exists():
        return None
    for kotlin_file in sorted(root.rglob("*.kt")):
        match = re.search(r"^package\s+([A-Za-z0-9_.]+)", kotlin_file.read_text(encoding="utf-8"), re.MULTILINE)
        if match:
            return match.group(1)
    return None


# application layer에 사용할 package 이름을 현재 프로젝트 구조에서 추론한다.
def _application_package(context: DevRunnerContext) -> str:
    application_root = context.repo_path / "apps/server/modules/application/src/main/kotlin"
    existing_package = _first_package_under(application_root)
    if existing_package:
        return existing_package.rsplit(".", 1)[0] if existing_package.endswith(".member") else existing_package

    bootstrap_package = _first_package_under(_bootstrap_module_root(context) / "src/main/kotlin")
    if bootstrap_package:
        return bootstrap_package.replace(".bootstrap", ".application")

    project_name = re.sub(r"[^0-9a-zA-Z]+", "", context.repo_path.name).lower() or "app"
    return f"com.{project_name}.server.application"


# DDD application layer scaffold 파일들을 생성하고 상대 경로 목록을 반환한다.
def _write_ddd_scaffold(context: DevRunnerContext, spec: DDDScaffoldSpec) -> list[str]:
    application_package = _application_package(context)
    base_dir = (
        context.repo_path
        / "apps/server/modules/application/src/main/kotlin"
        / Path(*application_package.split("."))
        / spec.domain
    )
    files = {
        base_dir / f"{spec.usecase_name}Command.kt": _ddd_command_content(spec, application_package),
        base_dir / f"{spec.usecase_name}Result.kt": _ddd_result_content(spec, application_package),
        base_dir / f"{spec.usecase_name}Service.kt": _ddd_service_content(spec, application_package),
        base_dir / f"{spec.domain_class}PolicyChecker.kt": _ddd_policy_checker_content(spec, application_package),
    }
    changed_paths = []
    for path, content in files.items():
        if path.exists():
            continue
        _write_text(path, content)
        changed_paths.append(_relative(context, path))
    return changed_paths


# 로그인 API 구현 대상인지 판단하고 프로젝트 기본 package를 추론한다.
def _login_spec_from_context(context: DevRunnerContext) -> LoginImplementationSpec | None:
    endpoint = extract_api_endpoint(f"{context.title}\n{context.body}")
    if endpoint is None:
        return None
    method, path = endpoint
    haystack = f"{context.title}\n{context.body}".lower()
    if method.upper() != "POST" or path != "/api/auth/login":
        return None
    if "로그인" not in haystack and "login" not in haystack:
        return None
    return LoginImplementationSpec(method=method, path=path, base_package=_project_base_package(context))


# bootstrap package에서 프로젝트 공통 base package를 추론한다.
def _project_base_package(context: DevRunnerContext) -> str:
    bootstrap_package = _first_package_under(_bootstrap_module_root(context) / "src/main/kotlin")
    if bootstrap_package and ".bootstrap" in bootstrap_package:
        return bootstrap_package.split(".bootstrap", 1)[0]
    if bootstrap_package:
        return bootstrap_package.rsplit(".", 1)[0]
    project_name = re.sub(r"[^0-9a-zA-Z]+", "", context.repo_path.name).lower() or "app"
    return f"com.{project_name}.server"


# 로그인 도메인과 application service/input port Kotlin 파일을 생성한다.
def _write_login_domain_application(context: DevRunnerContext, spec: LoginImplementationSpec) -> list[str]:
    source_root = context.repo_path / "apps/server/modules"
    domain_dir = source_root / "domain/src/main/kotlin" / Path(*spec.domain_package.split("."))
    app_dir = source_root / "application/src/main/kotlin" / Path(*spec.application_package.split("."))
    port_dir = source_root / "application/src/main/kotlin" / Path(*f"{spec.base_package}.application.port".split("."))
    common_dir = source_root / "application/src/main/kotlin" / Path(*f"{spec.base_package}.application.common.extension".split("."))
    files = {
        domain_dir / "Member.kt": _login_member_domain_content(spec),
        app_dir / "AuthenticationInputPort.kt": _authentication_input_port_content(spec),
        app_dir / "AuthenticationService.kt": _authentication_service_content(spec),
        app_dir / "SignInRequest.kt": _sign_in_request_content(spec),
        app_dir / "SignInResponse.kt": _sign_in_response_content(spec),
        app_dir / "LoginMemberReader.kt": _login_member_reader_content(spec),
        app_dir / "PasswordVerifier.kt": _password_verifier_content(spec),
        app_dir / "LoginFailedException.kt": _login_failed_exception_content(spec),
        port_dir / "MemberRepository.kt": _member_repository_port_content(spec),
        port_dir / "JwtTokenIssuer.kt": _jwt_token_issuer_port_content(spec),
        port_dir / "RefreshTokenStore.kt": _refresh_token_store_port_content(spec),
        common_dir / "LoggerExtension.kt": _logger_extension_content(spec),
    }
    changed_paths = _write_files_if_needed(context, files)
    changed_paths.extend(
        _ensure_gradle_dependency(
            context,
            context.repo_path / "apps/server/modules/application/build.gradle.kts",
            'implementation("org.springframework.security:spring-security-crypto")',
        )
    )
    return changed_paths


# 로그인 API bootstrap, JPA, Redis, JWT adapter Kotlin 파일을 생성한다.
def _write_login_api_infrastructure(context: DevRunnerContext, spec: LoginImplementationSpec) -> list[str]:
    source_root = context.repo_path / "apps/server/modules"
    bootstrap_dir = source_root / "bootstrap/mymentalcare/src/main/kotlin" / Path(*spec.bootstrap_package.split("."))
    persistence_dir = source_root / "infrastructure/persistence/src/main/kotlin" / Path(*spec.persistence_package.split("."))
    auth_adapter_dir = source_root / "bootstrap/mymentalcare/src/main/kotlin" / Path(*f"{spec.base_package}.bootstrap.auth.adapter".split("."))
    files = {
        bootstrap_dir / "AuthController.kt": _auth_controller_content(spec),
        bootstrap_dir / "LoginRequest.kt": _login_request_content(spec),
        bootstrap_dir / "LoginResponse.kt": _login_response_content(spec),
        bootstrap_dir / "ApiErrorResponse.kt": _api_error_response_content(spec),
        bootstrap_dir / "AuthExceptionHandler.kt": _auth_exception_handler_content(spec),
        persistence_dir / "MemberEntity.kt": _member_entity_content(spec),
        persistence_dir / "JpaMemberRepository.kt": _jpa_member_repository_content(spec),
        persistence_dir / "MemberPersistenceAdapter.kt": _member_persistence_adapter_content(spec),
        auth_adapter_dir / "JwtTokenAdapter.kt": _jwt_token_adapter_content(spec),
        auth_adapter_dir / "RedisRefreshTokenAdapter.kt": _redis_refresh_token_adapter_content(spec),
    }
    changed_paths = _write_files_if_needed(context, files)
    changed_paths.extend(_ensure_password_encoder_bean(context))
    return changed_paths


# 존재하지 않는 파일만 작성하고 상대 경로 목록을 반환한다.
def _write_files_if_needed(context: DevRunnerContext, files: dict[Path, str]) -> list[str]:
    changed_paths: list[str] = []
    for path, content in files.items():
        if path.exists():
            continue
        _write_text(path, content)
        changed_paths.append(_relative(context, path))
    return changed_paths


# Gradle dependency가 없으면 dependencies block에 추가한다.
def _ensure_gradle_dependency(context: DevRunnerContext, build_file: Path, dependency_line: str) -> list[str]:
    if not build_file.exists():
        return []
    text = build_file.read_text(encoding="utf-8")
    if dependency_line in text:
        return []
    updated = text.replace("dependencies {\n", f"dependencies {{\n    {dependency_line}\n", 1)
    build_file.write_text(updated, encoding="utf-8")
    return [_relative(context, build_file)]


# SecurityConfiguration에 BCrypt PasswordEncoder bean을 보장한다.
def _ensure_password_encoder_bean(context: DevRunnerContext) -> list[str]:
    config_path = (
        _bootstrap_module_root(context)
        / "src/main/kotlin"
        / Path(*f"{_project_base_package(context)}.bootstrap.config.SecurityConfiguration".split("."))
    ).with_suffix(".kt")
    if not config_path.exists():
        return []
    text = config_path.read_text(encoding="utf-8")
    if "PasswordEncoder" in text and "BCryptPasswordEncoder" in text:
        return []
    updated = text
    updated = updated.replace(
        "import org.springframework.security.web.SecurityFilterChain\n",
        "import org.springframework.security.web.SecurityFilterChain\n"
        "import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder\n"
        "import org.springframework.security.crypto.password.PasswordEncoder\n",
    )
    updated = updated.replace(
        "class SecurityConfiguration {\n",
        "class SecurityConfiguration {\n"
        "    @Bean\n"
        "    fun passwordEncoder(): PasswordEncoder = BCryptPasswordEncoder()\n\n",
        1,
    )
    config_path.write_text(updated, encoding="utf-8")
    return [_relative(context, config_path)]


# Member 도메인 모델 Kotlin 소스를 만든다.
def _login_member_domain_content(spec: LoginImplementationSpec) -> str:
    return f"""package {spec.domain_package}

data class Member(
    val id: Long,
    val loginId: String,
    val email: String?,
    val password: String,
    val name: String,
    val phone: String?,
)
"""


# AuthenticationInputPort Kotlin 소스를 만든다.
def _authentication_input_port_content(spec: LoginImplementationSpec) -> str:
    return f"""package {spec.application_package}

interface AuthenticationInputPort {{
    fun signIn(request: SignInRequest): SignInResponse
}}
"""


# 로그인 request Kotlin 소스를 만든다.
def _sign_in_request_content(spec: LoginImplementationSpec) -> str:
    return f"""package {spec.application_package}

data class SignInRequest(
    val identifier: String,
    val password: String,
)
"""


# 로그인 response Kotlin 소스를 만든다.
def _sign_in_response_content(spec: LoginImplementationSpec) -> str:
    return f"""package {spec.application_package}

data class SignInResponse(
    val accessToken: String,
    val refreshToken: String,
    val tokenType: String = "Bearer",
    val expiresInSeconds: Long = 3600,
)
"""


# 로그인 실패 exception Kotlin 소스를 만든다.
def _login_failed_exception_content(spec: LoginImplementationSpec) -> str:
    return f"""package {spec.application_package}

class LoginFailedException(
    message: String = "로그인 정보를 다시 확인해주세요.",
) : RuntimeException(message)
"""


# AuthenticationService Kotlin 소스를 만든다.
def _authentication_service_content(spec: LoginImplementationSpec) -> str:
    return f"""package {spec.application_package}

import {spec.base_package}.application.port.JwtTokenIssuer
import {spec.base_package}.application.port.RefreshTokenStore
import org.springframework.stereotype.Service

@Service
internal class AuthenticationService(
    private val loginMemberReader: LoginMemberReader,
    private val passwordVerifier: PasswordVerifier,
    private val jwtTokenIssuer: JwtTokenIssuer,
    private val refreshTokenStore: RefreshTokenStore,
) : AuthenticationInputPort {{
    // 로그인
    override fun signIn(request: SignInRequest): SignInResponse {{
        val member = loginMemberReader.readMemberByLoginIdentifier(request.identifier)

        passwordVerifier.verifyPasswordMatches(request.password, member.password)

        val accessToken = jwtTokenIssuer.issueAccessToken(member.id)
        val refreshToken = jwtTokenIssuer.issueRefreshToken(member.id)

        refreshTokenStore.storeRefreshToken(member.id, refreshToken)

        return SignInResponse(
            accessToken = accessToken,
            refreshToken = refreshToken,
        )
    }}
}}
"""


# LoginMemberReader Kotlin 소스를 만든다.
def _login_member_reader_content(spec: LoginImplementationSpec) -> str:
    return f"""package {spec.application_package}

import {spec.base_package}.application.common.extension.logWarn
import {spec.base_package}.application.port.MemberRepository
import {spec.domain_package}.Member
import org.springframework.stereotype.Component

@Component
class LoginMemberReader(
    private val memberRepository: MemberRepository,
) {{
    // 로그인 ID 또는 이메일 후보로 회원을 조회하고 없으면 안전한 실패 메시지로 차단한다.
    fun readMemberByLoginIdentifier(identifier: String): Member {{
        return memberRepository.findByLoginIdOrEmail(identifier)
            ?: run {{
                logWarn {{
                    "[로그인] 로그인 대상 회원 조회 실패. " +
                        "who=anonymous, " +
                        "what=POST /api/auth/login, " +
                        "requestData=identifier:$identifier, " +
                        "reason=member_not_found"
                }}
                throw LoginFailedException()
            }}
    }}
}}
"""


# PasswordVerifier Kotlin 소스를 만든다.
def _password_verifier_content(spec: LoginImplementationSpec) -> str:
    return f"""package {spec.application_package}

import {spec.base_package}.application.common.extension.logWarn
import org.springframework.security.crypto.password.PasswordEncoder
import org.springframework.stereotype.Component

@Component
class PasswordVerifier(
    private val passwordEncoder: PasswordEncoder,
) {{
    // 입력 비밀번호가 저장된 해시와 일치하지 않으면 로그인 실패로 처리한다.
    fun verifyPasswordMatches(rawPassword: String, encodedPassword: String) {{
        if (passwordEncoder.matches(rawPassword, encodedPassword)) {{
            return
        }}

        logWarn {{
            "[로그인] 비밀번호 검증 실패. " +
                "who=anonymous, " +
                "what=POST /api/auth/login, " +
                "requestData=password:masked, " +
                "reason=password_mismatch"
        }}
        throw LoginFailedException()
    }}
}}
"""


# MemberRepository port Kotlin 소스를 만든다.
def _member_repository_port_content(spec: LoginImplementationSpec) -> str:
    return f"""package {spec.base_package}.application.port

import {spec.domain_package}.Member

interface MemberRepository {{
    fun findByLoginIdOrEmail(identifier: String): Member?
}}
"""


# JwtTokenIssuer port Kotlin 소스를 만든다.
def _jwt_token_issuer_port_content(spec: LoginImplementationSpec) -> str:
    return f"""package {spec.base_package}.application.port

interface JwtTokenIssuer {{
    fun issueAccessToken(memberId: Long): String

    fun issueRefreshToken(memberId: Long): String
}}
"""


# RefreshTokenStore port Kotlin 소스를 만든다.
def _refresh_token_store_port_content(spec: LoginImplementationSpec) -> str:
    return f"""package {spec.base_package}.application.port

interface RefreshTokenStore {{
    fun storeRefreshToken(memberId: Long, refreshToken: String)
}}
"""


# Bix 스타일 LoggerExtension Kotlin 소스를 만든다.
def _logger_extension_content(spec: LoginImplementationSpec) -> str:
    return f"""package {spec.base_package}.application.common.extension

import org.slf4j.LoggerFactory

fun <T : Any> T.logWarn(message: String) {{
    LoggerFactory.getLogger(this::class.java).warn(message)
}}

inline fun <T : Any> T.logWarn(closure: () -> String) {{
    logWarn(closure())
}}

fun <T : Any> T.logError(message: String, throwable: Throwable? = null) {{
    val logger = LoggerFactory.getLogger(this::class.java)
    if (throwable == null) {{
        logger.error(message)
    }} else {{
        logger.error(message, throwable)
    }}
}}

inline fun <T : Any> T.logError(throwable: Throwable, closure: () -> String) {{
    logError(closure(), throwable)
}}
"""


# AuthController Kotlin 소스를 만든다.
def _auth_controller_content(spec: LoginImplementationSpec) -> str:
    return f"""package {spec.bootstrap_package}

import {spec.application_package}.AuthenticationInputPort
import {spec.application_package}.SignInRequest
import io.swagger.v3.oas.annotations.Operation
import jakarta.validation.Valid
import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/auth")
class AuthController(
    private val authenticationInputPort: AuthenticationInputPort,
) {{
    @Operation(
        summary = "로그인",
        description = "로그인 ID 또는 이메일과 비밀번호로 로그인하고 access token과 refresh token을 발급합니다.",
    )
    @PostMapping("/login")
    fun login(
        @Valid @RequestBody request: LoginRequest,
    ): ResponseEntity<LoginResponse> {{
        val response = authenticationInputPort.signIn(
            SignInRequest(
                identifier = request.identifier,
                password = request.password,
            )
        )

        return ResponseEntity.ok(
            LoginResponse(
                accessToken = response.accessToken,
                refreshToken = response.refreshToken,
                tokenType = response.tokenType,
                expiresInSeconds = response.expiresInSeconds,
            )
        )
    }}
}}
"""


# LoginRequest Kotlin 소스를 만든다.
def _login_request_content(spec: LoginImplementationSpec) -> str:
    return f"""package {spec.bootstrap_package}

import jakarta.validation.constraints.NotBlank

data class LoginRequest(
    @field:NotBlank(message = "로그인 ID 또는 이메일을 입력해주세요.")
    val identifier: String,

    @field:NotBlank(message = "비밀번호를 입력해주세요.")
    val password: String,
)
"""


# LoginResponse Kotlin 소스를 만든다.
def _login_response_content(spec: LoginImplementationSpec) -> str:
    return f"""package {spec.bootstrap_package}

data class LoginResponse(
    val accessToken: String,
    val refreshToken: String,
    val tokenType: String,
    val expiresInSeconds: Long,
)
"""


# ApiErrorResponse Kotlin 소스를 만든다.
def _api_error_response_content(spec: LoginImplementationSpec) -> str:
    return f"""package {spec.bootstrap_package}

data class ApiErrorResponse(
    val code: String,
    val message: String,
)
"""


# AuthExceptionHandler Kotlin 소스를 만든다.
def _auth_exception_handler_content(spec: LoginImplementationSpec) -> str:
    return f"""package {spec.bootstrap_package}

import {spec.application_package}.LoginFailedException
import org.springframework.http.HttpStatus
import org.springframework.http.ResponseEntity
import org.springframework.web.bind.MethodArgumentNotValidException
import org.springframework.web.bind.annotation.ExceptionHandler
import org.springframework.web.bind.annotation.RestControllerAdvice

@RestControllerAdvice
class AuthExceptionHandler {{
    @ExceptionHandler(LoginFailedException::class)
    fun handleLoginFailed(exception: LoginFailedException): ResponseEntity<ApiErrorResponse> {{
        return ResponseEntity
            .status(HttpStatus.UNAUTHORIZED)
            .body(ApiErrorResponse(code = "AUTH_LOGIN_FAILED", message = exception.message ?: "로그인 정보를 다시 확인해주세요."))
    }}

    @ExceptionHandler(MethodArgumentNotValidException::class)
    fun handleInvalidRequest(exception: MethodArgumentNotValidException): ResponseEntity<ApiErrorResponse> {{
        return ResponseEntity
            .badRequest()
            .body(ApiErrorResponse(code = "AUTH_INVALID_REQUEST", message = "입력한 로그인 정보를 다시 확인해주세요."))
    }}
}}
"""


# MemberEntity Kotlin 소스를 만든다.
def _member_entity_content(spec: LoginImplementationSpec) -> str:
    return f"""package {spec.persistence_package}

import {spec.domain_package}.Member
import jakarta.persistence.Column
import jakarta.persistence.Entity
import jakarta.persistence.GeneratedValue
import jakarta.persistence.GenerationType
import jakarta.persistence.Id
import jakarta.persistence.Table

@Entity
@Table(name = "members")
class MemberEntity(
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    val id: Long = 0,

    @Column(name = "login_id", nullable = false, unique = true)
    val loginId: String,

    @Column(name = "email", nullable = true, unique = true)
    val email: String?,

    @Column(name = "password", nullable = false)
    val password: String,

    @Column(name = "name", nullable = false)
    val name: String,

    @Column(name = "phone", nullable = true)
    val phone: String?,
) {{
    fun toDomain(): Member {{
        return Member(
            id = id,
            loginId = loginId,
            email = email,
            password = password,
            name = name,
            phone = phone,
        )
    }}
}}
"""


# JpaMemberRepository Kotlin 소스를 만든다.
def _jpa_member_repository_content(spec: LoginImplementationSpec) -> str:
    return f"""package {spec.persistence_package}

import org.springframework.data.jpa.repository.JpaRepository

interface JpaMemberRepository : JpaRepository<MemberEntity, Long> {{
    fun findByLoginId(identifier: String): MemberEntity?

    fun findByEmail(identifier: String): MemberEntity?
}}
"""


# MemberPersistenceAdapter Kotlin 소스를 만든다.
def _member_persistence_adapter_content(spec: LoginImplementationSpec) -> str:
    return f"""package {spec.persistence_package}

import {spec.base_package}.application.port.MemberRepository
import {spec.domain_package}.Member
import org.springframework.stereotype.Repository

@Repository
class MemberPersistenceAdapter(
    private val jpaMemberRepository: JpaMemberRepository,
) : MemberRepository {{
    override fun findByLoginIdOrEmail(identifier: String): Member? {{
        return jpaMemberRepository.findByLoginId(identifier)?.toDomain()
            ?: jpaMemberRepository.findByEmail(identifier)?.toDomain()
    }}
}}
"""


# JwtTokenAdapter Kotlin 소스를 만든다.
def _jwt_token_adapter_content(spec: LoginImplementationSpec) -> str:
    return f"""package {spec.base_package}.bootstrap.auth.adapter

import {spec.base_package}.application.port.JwtTokenIssuer
import {spec.base_package}.bootstrap.config.JwtProperties
import io.jsonwebtoken.Jwts
import io.jsonwebtoken.SignatureAlgorithm
import io.jsonwebtoken.security.Keys
import org.springframework.stereotype.Component
import java.nio.charset.StandardCharsets
import java.time.Instant
import java.util.Date

@Component
class JwtTokenAdapter(
    private val jwtProperties: JwtProperties,
) : JwtTokenIssuer {{
    override fun issueAccessToken(memberId: Long): String {{
        return issueToken(memberId, jwtProperties.accessTokenExpiration.seconds)
    }}

    override fun issueRefreshToken(memberId: Long): String {{
        return issueToken(memberId, jwtProperties.refreshTokenExpiration.seconds)
    }}

    private fun issueToken(memberId: Long, expirationSeconds: Long): String {{
        val now = Instant.now()
        val key = Keys.hmacShaKeyFor(jwtProperties.secret.toByteArray(StandardCharsets.UTF_8))

        return Jwts.builder()
            .setSubject(memberId.toString())
            .setIssuedAt(Date.from(now))
            .setExpiration(Date.from(now.plusSeconds(expirationSeconds)))
            .signWith(key, SignatureAlgorithm.HS256)
            .compact()
    }}
}}
"""


# RedisRefreshTokenAdapter Kotlin 소스를 만든다.
def _redis_refresh_token_adapter_content(spec: LoginImplementationSpec) -> str:
    return f"""package {spec.base_package}.bootstrap.auth.adapter

import {spec.base_package}.application.port.RefreshTokenStore
import {spec.base_package}.bootstrap.config.JwtProperties
import org.springframework.data.redis.core.StringRedisTemplate
import org.springframework.stereotype.Component
import java.time.Duration

@Component
class RedisRefreshTokenAdapter(
    private val redisTemplate: StringRedisTemplate,
    private val jwtProperties: JwtProperties,
) : RefreshTokenStore {{
    override fun storeRefreshToken(memberId: Long, refreshToken: String) {{
        redisTemplate.opsForValue().set(
            "auth:refresh-token:$memberId",
            refreshToken,
            jwtProperties.refreshTokenExpiration,
        )
    }}
}}
"""


# DDD Command data class의 Kotlin 소스 내용을 생성한다.
def _ddd_command_content(spec: DDDScaffoldSpec, application_package: str) -> str:
    return "\n".join(
        [
            f"package {application_package}.{spec.domain}",
            "",
            f"data class {spec.usecase_name}Command(",
            "    val requestedBy: String? = null,",
            ")",
            "",
        ]
    )


# DDD Result data class의 Kotlin 소스 내용을 생성한다.
def _ddd_result_content(spec: DDDScaffoldSpec, application_package: str) -> str:
    return "\n".join(
        [
            f"package {application_package}.{spec.domain}",
            "",
            f"data class {spec.usecase_name}Result(",
            "    val id: Long? = null,",
            ")",
            "",
        ]
    )


# usecase-orchestration-style을 반영한 application service 내용을 생성한다.
def _ddd_service_content(spec: DDDScaffoldSpec, application_package: str) -> str:
    return "\n".join(
        [
            f"package {application_package}.{spec.domain}",
            "",
            f"class {spec.usecase_name}Service(",
            f"    private val {spec.domain}PolicyChecker: {spec.domain_class}PolicyChecker,",
            ") {",
            f"    // {spec.domain_class} 유스케이스를 처리한다.",
            f"    fun {spec.method_name}(command: {spec.usecase_name}Command): {spec.usecase_name}Result {{",
            f"        {spec.domain}PolicyChecker.{spec.policy_method_name}(command)",
            "",
            f'        TODO("{spec.usecase_name} 유스케이스의 조회, 수행, 기록, 반환 흐름을 구현해야 합니다.")',
            "    }",
            "}",
            "",
        ]
    )


# 책임 객체 public method에 한국어 한 줄 주석을 포함한 정책 검증 scaffold를 생성한다.
def _ddd_policy_checker_content(spec: DDDScaffoldSpec, application_package: str) -> str:
    return "\n".join(
        [
            f"package {application_package}.{spec.domain}",
            "",
            f"class {spec.domain_class}PolicyChecker {{",
            f"    // {spec.domain_class} 유스케이스를 수행할 수 있는 도메인 정책 상태인지 검증한다.",
            f"    fun {spec.policy_method_name}(command: {spec.usecase_name}Command) {{",
            '        TODO("도메인 정책 검증을 구현해야 합니다.")',
            "    }",
            "}",
            "",
        ]
    )


# 이슈 본문과 Plan 산출물에서 SQL code block을 추출한다.
def _extract_sql_ddl(context: DevRunnerContext) -> str | None:
    sources = [context.body]
    plans_dir = context.task_dir.parent / "plans"
    for name in ["architecture.md", "ddl.md"]:
        path = plans_dir / name
        if path.exists():
            sources.append(path.read_text(encoding="utf-8"))

    for source in sources:
        match = re.search(r"```sql\s+(.*?)```", source, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


# 기존 Flyway migration 번호 다음 번호로 새 migration 경로를 만든다.
def _next_migration_path(context: DevRunnerContext) -> Path:
    migration_dir = (
        _bootstrap_module_root(context)
        / "src/main/resources/db/migration"
    )
    migration_dir.mkdir(parents=True, exist_ok=True)
    versions = []
    for path in migration_dir.glob("V*__*.sql"):
        match = re.match(r"V(\d+)__", path.name)
        if match:
            versions.append(int(match.group(1)))
    next_version = max(versions, default=0) + 1
    slug = _migration_slug(context.feature_name)
    return migration_dir / f"V{next_version}__{slug}.sql"


# migration 파일명에 사용할 안전한 slug를 만든다.
def _migration_slug(value: str) -> str:
    slug = re.sub(r"[^0-9a-zA-Z가-힣]+", "_", value).strip("_")
    return slug or "harness_migration"


# API contract 문서를 저장할 경로를 만든다.
def _api_contract_path(context: DevRunnerContext, method: str, path: str) -> Path:
    slug = re.sub(r"[^0-9a-zA-Z]+", "-", f"{method}-{path}").strip("-").lower()
    return context.repo_path / "docs/api" / f"harness-{context.issue_number}-{slug}.md"


# API contract 초안 내용을 생성한다.
def _api_contract_content(context: DevRunnerContext, method: str, path: str) -> str:
    return "\n".join(
        [
            f"# {context.feature_name} API Contract",
            "",
            "## Endpoint",
            "",
            f"- method/path: `{method} {path}`",
            "- auth: 결정 필요",
            "",
            "## Request",
            "",
            "```json",
            "{}",
            "```",
            "",
            "## Response",
            "",
            "```json",
            "{}",
            "```",
            "",
            "## Error Policy",
            "",
            "- 사용자에게 반환되는 메시지는 한국어로 작성한다.",
            "- 내부 구현 정보나 민감정보를 사용자 응답에 노출하지 않는다.",
            "- 로그에는 who/what/requestData/reason 형식을 우선 사용한다.",
            "",
            "## Implementation Boundary",
            "",
            "- Controller는 얇게 유지한다.",
            "- Request/Response DTO는 Controller 파일에서 분리한다.",
            "- 유스케이스 흐름은 application service에서 읽히도록 유지한다.",
            "- 실제 구현 전 이 contract를 사람 또는 Plan Agent가 보강해야 한다.",
        ]
    )


# 리팩터링 요청에 controller data class 분리 의도가 있는지 판단한다.
def _requests_controller_data_class_split(markdown: str) -> bool:
    normalized = markdown.lower()
    return (
        "controller" in normalized
        or "컨트롤러" in markdown
    ) and (
        "data class" in normalized
        or "데이터클래스" in markdown
        or "dto" in normalized
    ) and (
        "분리" in markdown
        or "별도" in markdown
        or "thin" in normalized
        or "얇게" in markdown
    )


# controller 파일 안의 data class를 같은 패키지의 별도 파일로 분리한다.
def _split_controller_data_classes(context: DevRunnerContext) -> list[RefactorSplitResult]:
    source_root = (
        _bootstrap_module_root(context)
        / "src/main/kotlin"
    )
    if not source_root.exists():
        return []

    results: list[RefactorSplitResult] = []
    for controller in source_root.rglob("*Controller.kt"):
        text = controller.read_text(encoding="utf-8")
        extracted = _extract_top_level_data_classes(text)
        if not extracted:
            continue

        updated_text = text
        changed_paths = [_relative(context, controller)]
        class_names: list[str] = []
        package_name = _extract_package_name(text)
        for class_name, class_text in extracted:
            dto_path = controller.parent / f"{class_name}.kt"
            if dto_path.exists():
                updated_text = updated_text.replace(class_text, "").strip() + "\n"
                continue
            _write_text(dto_path, f"package {package_name}\n\n{class_text.strip()}\n")
            updated_text = updated_text.replace(class_text, "").strip() + "\n"
            changed_paths.append(_relative(context, dto_path))
            class_names.append(class_name)

        if updated_text != text:
            controller.write_text(updated_text, encoding="utf-8")
            results.append(
                RefactorSplitResult(
                    controller=_relative(context, controller),
                    extracted_classes=class_names,
                    changed_paths=changed_paths,
                )
            )
    return results


# Kotlin 파일에서 top-level data class 선언 블록을 추출한다.
def _extract_top_level_data_classes(text: str) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    pattern = re.compile(r"^data class\s+(\w+)\s*\(", re.MULTILINE)
    for match in pattern.finditer(text):
        start = match.start()
        end = _find_kotlin_class_end(text, match.end() - 1)
        if end <= start:
            continue
        results.append((match.group(1), text[start:end].strip()))
    return results


# Kotlin data class 선언의 끝 위치를 괄호와 중괄호 균형으로 찾는다.
def _find_kotlin_class_end(text: str, start_index: int) -> int:
    paren_depth = 0
    brace_depth = 0
    seen_paren = False
    index = start_index
    while index < len(text):
        char = text[index]
        if char == "(":
            paren_depth += 1
            seen_paren = True
        elif char == ")":
            paren_depth -= 1
            if seen_paren and paren_depth == 0 and brace_depth == 0:
                line_end = text.find("\n", index)
                return len(text) if line_end == -1 else line_end + 1
        elif char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth -= 1
            if seen_paren and paren_depth == 0 and brace_depth == 0:
                line_end = text.find("\n", index)
                return len(text) if line_end == -1 else line_end + 1
        index += 1
    return len(text)


# Kotlin package 선언을 추출한다.
def _extract_package_name(text: str) -> str:
    match = re.search(r"^package\s+([A-Za-z0-9_.]+)", text, re.MULTILINE)
    return match.group(1) if match else "com.example.server.bootstrap"


# 리팩터링 결과를 Markdown으로 변환한다.
def _format_refactor_result(result: RefactorSplitResult) -> list[str]:
    return [
        f"- controller: `{result.controller}`",
        f"- extracted_classes: `{', '.join(result.extracted_classes) if result.extracted_classes else 'none'}`",
        f"- changed_paths: `{', '.join(result.changed_paths) if result.changed_paths else 'none'}`",
    ]


# 로그인 API 연동 요청인지 title/body/API mapping을 기준으로 판단한다.
def _is_login_api_connect_request(context: DevRunnerContext) -> bool:
    haystack = f"{context.title}\n{context.body}".lower()
    return "/api/auth/login" in haystack or ("로그인" in haystack and "api" in haystack)


def _is_reissue_api_connect_request(context: DevRunnerContext) -> bool:
    haystack = f"{context.title}\n{context.body}".lower()
    return (
        "/api/auth/reissue" in haystack
        or "refresh token" in haystack
        or "리프레시 토큰" in haystack
        or "자동 재발급" in haystack
    )


# 로그인 API client와 기존 로그인 모달 submit handler를 연결한다.
def _connect_login_api(context: DevRunnerContext) -> list[str]:
    page_path = context.repo_path / "apps/web/app/page.tsx"
    if not page_path.exists():
        raise RuntimeError("apps/web/app/page.tsx 파일을 찾지 못해 로그인 API를 연동할 수 없습니다.")

    auth_api_path = context.repo_path / "apps/web/lib/auth-api.ts"
    _write_text(auth_api_path, _auth_api_ts_content())

    page_text = page_path.read_text(encoding="utf-8")
    updated = _apply_login_api_to_page(page_text)
    if updated == page_text:
        raise RuntimeError("로그인 모달 submit handler를 찾지 못해 로그인 API를 연동할 수 없습니다.")
    page_path.write_text(updated, encoding="utf-8")

    smoke_path = context.repo_path / "apps/web/scripts/verify-main-auth-screen.mjs"
    changed = [_relative(context, auth_api_path), _relative(context, page_path)]
    if smoke_path.exists():
        smoke_text = smoke_path.read_text(encoding="utf-8")
        smoke_updated = _apply_login_api_to_smoke_test(smoke_text)
        smoke_path.write_text(smoke_updated, encoding="utf-8")
        changed.append(_relative(context, smoke_path))
    return changed


# Access Token 만료 시 Refresh Token 재발급 연동이 구현되어 있는지 검증한다.
def _connect_reissue_api(context: DevRunnerContext) -> list[str]:
    auth_api_path = context.repo_path / "apps/web/lib/auth-api.ts"
    smoke_path = context.repo_path / "apps/web/scripts/verify-main-auth-screen.mjs"
    if not auth_api_path.exists():
        raise RuntimeError("apps/web/lib/auth-api.ts 파일을 찾지 못해 토큰 재발급 연동을 확인할 수 없습니다.")

    auth_api_text = auth_api_path.read_text(encoding="utf-8")
    required_snippets = [
        "/api/auth/reissue",
        "reissueToken",
        "requestWithAuth",
        "response.status !== 401",
        "storeLoginTokens(await reissueToken",
        "clearLoginTokens()",
        "retryOnUnauthorized",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in auth_api_text]
    if missing:
        raise RuntimeError(f"토큰 재발급 연동 코드가 부족합니다. missing={', '.join(missing)}")

    changed = [_relative(context, auth_api_path)]
    if smoke_path.exists():
        smoke_text = smoke_path.read_text(encoding="utf-8")
        required_smoke = ["/api/auth/reissue", "reissueToken", "clearLoginTokens()"]
        smoke_missing = [snippet for snippet in required_smoke if snippet not in smoke_text]
        if smoke_missing:
            raise RuntimeError(f"토큰 재발급 smoke test 기준이 부족합니다. missing={', '.join(smoke_missing)}")
        changed.append(_relative(context, smoke_path))
    return changed


# 로그인 API 호출용 프론트엔드 client 파일 내용을 생성한다.
def _auth_api_ts_content() -> str:
    return """export type LoginRequest = {
  identifier: string
  password: string
}

export type LoginResponse = {
  accessToken: string
  refreshToken: string
  tokenType: string
  expiresInSeconds: number
}

export class LoginApiError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'LoginApiError'
  }
}

const apiBaseUrl = process.env.NEXT_PUBLIC_TARGET_API_BASE_URL ?? 'http://localhost:3001'

export async function loginMember(request: LoginRequest): Promise<LoginResponse> {
  const response = await fetch(`${apiBaseUrl}/api/auth/login`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  })

  const body = await response.json().catch(() => null)

  if (!response.ok) {
    throw new LoginApiError(body?.message ?? '로그인 처리 중 문제가 발생했습니다.')
  }

  return body as LoginResponse
}
"""


# 기존 page.tsx의 로그인 모달을 API 호출 기반으로 변환한다.
def _apply_login_api_to_page(page_text: str) -> str:
    text = page_text
    if "loginMember" not in text:
        text = text.replace(
            "import { FormEvent, useState } from 'react'",
            "import { FormEvent, useState } from 'react'\nimport { LoginApiError, loginMember } from '@/lib/auth-api'",
        )
    if "const [isSubmitting, setIsSubmitting] = useState(false)" not in text:
        text = text.replace(
            "  const [message, setMessage] = useState('')\n  const isSignup = mode === 'signup'",
            "  const [message, setMessage] = useState('')\n  const [isSubmitting, setIsSubmitting] = useState(false)\n  const isSignup = mode === 'signup'",
        )

    old_handler = """  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setMessage(
      isSignup
        ? '회원가입 API 연동 전입니다. 입력 흐름만 안전하게 확인했습니다.'
        : '로그인 API 연동 전입니다. 입력 흐름만 안전하게 확인했습니다.',
    )
  }"""
    new_handler = """  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setMessage('')

    if (isSignup) {
      setMessage('회원가입 API 연동 전입니다. 입력 흐름만 안전하게 확인했습니다.')
      return
    }

    const formData = new FormData(event.currentTarget)
    const identifier = String(formData.get('loginId') ?? '').trim()
    const password = String(formData.get('password') ?? '')

    setIsSubmitting(true)
    try {
      const response = await loginMember({ identifier, password })
      localStorage.setItem('myMentalCare.accessToken', response.accessToken)
      localStorage.setItem('myMentalCare.refreshToken', response.refreshToken)
      setMessage('로그인이 완료되었습니다.')
    } catch (error) {
      setMessage(error instanceof LoginApiError ? error.message : '로그인 처리 중 문제가 발생했습니다.')
    } finally {
      setIsSubmitting(false)
    }
  }"""
    text = text.replace(old_handler, new_handler)
    text = text.replace(
        "              {isSignup ? '회원가입' : '로그인'}",
        "              {isSubmitting ? '처리 중...' : isSignup ? '회원가입' : '로그인'}",
    )
    return text


# 프론트 smoke test를 로그인 API 연동 확인 기준으로 보강한다.
def _apply_login_api_to_smoke_test(smoke_text: str) -> str:
    text = smoke_text
    if "const authApi =" not in text:
        text = text.replace(
            "const styles = readFileSync(resolve('app/globals.css'), 'utf8')",
            "const styles = readFileSync(resolve('app/globals.css'), 'utf8')\nconst authApi = readFileSync(resolve('lib/auth-api.ts'), 'utf8')",
        )
    text = text.replace(
        "  ['API 연동 전 안내 메시지', page.includes('API 연동 전입니다')],",
        "  ['회원가입 API 연동 전 안내 메시지', page.includes('회원가입 API 연동 전입니다')],\n  ['로그인 API 호출 함수 사용', page.includes('await loginMember')],\n  ['로그인 성공 토큰 저장', page.includes('myMentalCare.accessToken') && page.includes('myMentalCare.refreshToken')],\n  ['로그인 API endpoint 확인', authApi.includes('/api/auth/login')],\n  ['로그인 실패 오류 메시지 처리', authApi.includes('LoginApiError')],",
    )
    return text


# 이슈 타입에 맞는 테스트 명령 목록을 결정한다.
def _test_commands_for_context(context: DevRunnerContext, snapshot) -> list[list[str]]:
    if context.issue_type == "feFeature":
        return frontend_test_commands(snapshot)
    if context.issue_type == "beFeature":
        return backend_test_commands(snapshot)
    if context.issue_type in {"fullstackFeature", "apiConnect"}:
        return backend_test_commands(snapshot) + frontend_test_commands(snapshot)
    if context.issue_type in {"config", "infra", "bugfix", "hotfix"}:
        return backend_test_commands(snapshot) + frontend_test_commands(snapshot)
    return []


# 테스트 명령을 실행할 작업 디렉토리를 결정한다.
def _command_cwd(context: DevRunnerContext, command: list[str]) -> Path:
    if command and command[0] == "./gradlew":
        return context.repo_path / "apps/server"
    return context.repo_path


# 외부 명령을 실행하고 표준 출력과 오류를 반환한다.
def _run_command(command: list[str], cwd: Path, timeout_seconds: int) -> tuple[list[str], int, str, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return command, completed.returncode, completed.stdout, completed.stderr
    except FileNotFoundError as exc:
        return command, 127, "", str(exc)


# 명령 실행 결과를 Markdown 섹션으로 변환한다.
def _format_command_result(command: list[str], exit_code: int, stdout: str, stderr: str) -> list[str]:
    return [
        f"## Command: {' '.join(command)}",
        "",
        f"- exit_code: `{exit_code}`",
        "",
        "### stdout",
        "```text",
        stdout.strip() or "(비어 있음)",
        "```",
        "",
        "### stderr",
        "```text",
        stderr.strip() or "(비어 있음)",
        "```",
        "",
    ]
