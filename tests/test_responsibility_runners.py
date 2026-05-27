from pathlib import Path
from uuid import uuid4

from git import Repo

from agents.base import AgentStatus
from agents.runners.base import DevRunnerContext
from agents.runners.codebase_inspector import extract_frontend_route, inspect_codebase
from agents.runners.responsibility_runners import DBMigrationRunner


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
