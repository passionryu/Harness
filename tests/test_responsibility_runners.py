from pathlib import Path
from uuid import uuid4

from git import Repo

from agents.base import AgentStatus
from agents.runners.base import DevRunnerContext
from agents.runners.codebase_inspector import (
    extract_api_endpoint,
    extract_frontend_route,
    inspect_codebase,
)
from agents.runners.responsibility_runners import (
    APIImplementationRunner,
    DBMigrationRunner,
    DDDModelingRunner,
    RefactoringRunner,
)


# 테스트용 DevRunnerContext를 최소 StudyHub 저장소 구조와 함께 만든다.
def _make_context(tmp_path: Path, body: str, issue_type: str = "beFeature") -> DevRunnerContext:
    repo_path = tmp_path / "studyHub"
    migration_dir = (
        repo_path
        / "apps/server/modules/bootstrap/studyhub/src/main/resources/db/migration"
    )
    migration_dir.mkdir(parents=True)
    (repo_path / "apps/server/build.gradle.kts").write_text("", encoding="utf-8")
    (migration_dir / "V1__init.sql").write_text("create table sample(id bigint);\n", encoding="utf-8")
    repo = Repo.init(repo_path)
    repo.index.add(["apps/server/build.gradle.kts", "apps/server/modules/bootstrap/studyhub/src/main/resources/db/migration/V1__init.sql"])
    repo.index.commit("Initial commit")
    task_dir = tmp_path / "artifacts" / str(uuid4()) / "dev"
    task_dir.mkdir(parents=True)
    return DevRunnerContext(
        task_id=task_dir.parent.name,
        title="[BE] 테스트 기능",
        body=body,
        issue_type=issue_type,
        issue_number="12",
        branch_name="feature(BE)-12",
        feature_name="테스트 기능",
        repo=repo,
        repo_path=repo_path,
        task_dir=task_dir,
        timeout_seconds=30,
    )


def test_extract_frontend_route_ignores_api_paths():
    body = "API는 `/api/members/signup`이고 화면은 `/signup`이다."

    assert extract_frontend_route(body) == "/signup"


def test_extract_api_endpoint_reads_method_and_path():
    body = "회원가입 API는 `POST /api/members/signup`으로 제공한다."

    assert extract_api_endpoint(body) == ("POST", "/api/members/signup")


def test_inspect_codebase_reads_server_migrations(tmp_path):
    context = _make_context(tmp_path, "DDL 없음")

    snapshot = inspect_codebase(context)

    assert snapshot.has_kotlin_server is True
    assert snapshot.migrations == ["V1__init.sql"]


def test_db_migration_runner_applies_explicit_sql(tmp_path):
    context = _make_context(
        tmp_path,
        "\n".join(
            [
                "## DDL",
                "```sql",
                "alter table member add column login_id varchar(20);",
                "```",
            ]
        ),
    )

    result = DBMigrationRunner().run(context)

    assert result.status == AgentStatus.SUCCESS
    migration = (
        context.repo_path
        / "apps/server/modules/bootstrap/studyhub/src/main/resources/db/migration/V2__테스트_기능.sql"
    )
    assert migration.exists()
    assert "login_id" in migration.read_text(encoding="utf-8")
    assert context.repo.head.commit.message == "[테스트 기능] : DB migration 추가"


def test_api_implementation_runner_creates_contract_draft(tmp_path):
    context = _make_context(tmp_path, "API는 `POST /api/members/signup`으로 제공한다.")

    result = APIImplementationRunner().run(context)

    assert result.status == AgentStatus.NEEDS_HUMAN
    contract = context.repo_path / "docs/api/harness-12-post-api-members-signup.md"
    assert contract.exists()
    assert "POST /api/members/signup" in contract.read_text(encoding="utf-8")
    assert context.repo.head.commit.message == "[테스트 기능] : API contract 초안 추가"


def test_ddd_modeling_runner_creates_usecase_scaffold(tmp_path):
    context = _make_context(tmp_path, "회원가입 API는 `POST /api/members/signup`으로 제공한다.")

    result = DDDModelingRunner().run(context)

    assert result.status == AgentStatus.NEEDS_HUMAN
    base_dir = (
        context.repo_path
        / "apps/server/modules/application/src/main/kotlin/com/studyhub/server/application/member"
    )
    command = base_dir / "RegisterMemberCommand.kt"
    service = base_dir / "RegisterMemberService.kt"
    policy_checker = base_dir / "MemberPolicyChecker.kt"
    assert command.exists()
    assert (base_dir / "RegisterMemberResult.kt").exists()
    assert service.exists()
    assert policy_checker.exists()
    assert "fun registerMember(command: RegisterMemberCommand)" in service.read_text(encoding="utf-8")
    assert "memberPolicyChecker.validateMemberCanRegister(command)" in service.read_text(encoding="utf-8")
    assert "// Member 유스케이스를 수행할 수 있는 도메인 정책 상태인지 검증한다." in policy_checker.read_text(encoding="utf-8")
    assert context.repo.head.commit.message == "[테스트 기능] : DDD usecase scaffold 추가"


def test_refactoring_runner_splits_controller_data_classes(tmp_path):
    context = _make_context(
        tmp_path,
        "\n".join(
            [
                "## Human Refactor Request",
                "- 컨트롤러 안의 data class를 별도 파일로 분리한다.",
            ]
        ),
    )
    controller_dir = (
        context.repo_path
        / "apps/server/modules/bootstrap/studyhub/src/main/kotlin/com/studyhub/server/bootstrap/presentation/member"
    )
    controller_dir.mkdir(parents=True)
    controller = controller_dir / "MemberController.kt"
    controller.write_text(
        "\n".join(
            [
                "package com.studyhub.server.bootstrap.presentation.member",
                "",
                "import org.springframework.web.bind.annotation.RestController",
                "",
                "@RestController",
                "class MemberController",
                "",
                "data class MemberRequest(",
                "    val name: String,",
                ")",
            ]
        ),
        encoding="utf-8",
    )
    context.repo.index.add([str(controller.relative_to(context.repo_path))])
    context.repo.index.commit("Add controller")

    result = RefactoringRunner().run(context)

    assert result.status == AgentStatus.SUCCESS
    dto = controller_dir / "MemberRequest.kt"
    assert dto.exists()
    assert "data class MemberRequest" in dto.read_text(encoding="utf-8")
    assert "data class MemberRequest" not in controller.read_text(encoding="utf-8")
    assert context.repo.head.commit.message == "[테스트 기능] : controller data class 분리"
