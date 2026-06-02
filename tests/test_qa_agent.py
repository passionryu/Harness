from git import Repo

import agents.qa_agent as qa_agent
import orchestrator.services.orchestration as orchestration
from agents.base import AgentInput, AgentStatus


def test_fe_qa_agent_requires_frontend_runtime_before_human_qa(tmp_path, monkeypatch):
    target_repo = tmp_path / "myMentalCare"
    target_repo.mkdir()
    repo = Repo.init(target_repo)
    (target_repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    (target_repo / "apps/web/app").mkdir(parents=True)
    (target_repo / "apps/web/app/page.tsx").write_text("export default function Page() { return null }\n", encoding="utf-8")
    (target_repo / "apps/web/package.json").write_text(
        '{"scripts":{"test:main-auth":"node scripts/verify-main-auth-screen.mjs","build":"next build"}}\n',
        encoding="utf-8",
    )
    repo.index.add(["README.md", "apps/web/app/page.tsx", "apps/web/package.json"])
    repo.index.commit("Initial commit")
    repo.git.checkout("-b", "feature(FE)-1")

    artifact_root = tmp_path / "artifacts"
    task_id = "task-fe"
    for path in [
        artifact_root / task_id / "plans" / "architecture.md",
        artifact_root / task_id / "plans" / "edge-case-checklist.md",
        artifact_root / task_id / "dev" / "commit-plan.md",
        artifact_root / task_id / "dev" / "dev-status.md",
        artifact_root / task_id / "dev" / "implementation.patch",
        artifact_root / task_id / "dev" / "test-report.md",
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n", encoding="utf-8")

    monkeypatch.setattr(qa_agent.settings, "target_repo_path", target_repo)
    monkeypatch.setattr(qa_agent.settings, "frontend_base_url", "http://localhost:3000")
    monkeypatch.setattr(
        qa_agent,
        "_start_frontend_if_needed",
        lambda repo_path, timeout_seconds: (None, "테스트 프론트엔드 서버 사용"),
    )
    monkeypatch.setattr(qa_agent, "_is_frontend_alive", lambda: True)
    monkeypatch.setattr(
        qa_agent,
        "_verify_frontend_page_content",
        lambda timeout_seconds, markers: (
            True,
            f"url=http://localhost:3000, required_markers={markers}, missing_markers=없음",
            "<html>myMentalCare 회원가입 로그인 AI</html>",
            0,
            "",
        ),
    )
    monkeypatch.setattr(qa_agent, "_run_command", lambda command, cwd, timeout_seconds: (0, "ok", ""))

    result = qa_agent.QAAgent().run(
        AgentInput(
            task_id=task_id,
            title="[FE] 메인 페이지와 회원가입/로그인 모달 구현",
            body="\n".join(
                [
                    "따뜻한 정신 건강 서비스 메인 화면과 AI 채팅 진입점을 구현한다.",
                    "",
                    "## Harness Metadata",
                    "- issue_number: 1",
                    "- labels: type: feFeature",
                ]
            ),
            state="In Progress",
            artifacts_root=artifact_root,
            timeout_seconds=30,
            retry_count=0,
            retry_limit=2,
        )
    )

    assert result.status == AgentStatus.SUCCESS
    report = artifact_root / task_id / "qa" / "qa-report.md"
    content = report.read_text(encoding="utf-8")
    assert "프론트엔드 dev 서버 응답" in content
    assert "프론트엔드 화면 주요 문구 확인" in content
    assert "GET http://localhost:3000" in content
    assert "확인 URL: `http://localhost:3000`" in content


def test_be_qa_agent_reports_curl_smoke_details_and_human_checklist(tmp_path, monkeypatch):
    target_repo = tmp_path / "studyHub"
    target_repo.mkdir()
    repo = Repo.init(target_repo)
    (target_repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("Initial commit")
    repo.git.checkout("-b", "feature(BE)-3")

    artifact_root = tmp_path / "artifacts"
    task_id = "task-1"
    for path in [
        artifact_root / task_id / "plans" / "architecture.md",
        artifact_root / task_id / "plans" / "edge-case-checklist.md",
        artifact_root / task_id / "dev" / "commit-plan.md",
        artifact_root / task_id / "dev" / "dev-status.md",
        artifact_root / task_id / "dev" / "implementation.patch",
        artifact_root / task_id / "dev" / "test-report.md",
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n", encoding="utf-8")

    monkeypatch.setattr(qa_agent.settings, "target_repo_path", target_repo)
    monkeypatch.setattr(qa_agent.settings, "studyhub_api_base_url", "http://localhost:18080")
    monkeypatch.setattr(
        qa_agent.settings,
        "studyhub_swagger_url",
        "http://localhost:18080/swagger-ui/index.html",
    )
    monkeypatch.setattr(
        qa_agent,
        "_start_studyhub_api_if_needed",
        lambda repo_path, timeout_seconds: (None, "테스트 서버 사용"),
    )
    monkeypatch.setattr(qa_agent, "_is_api_alive", lambda: True)

    def fake_run_api_case(case, timeout_seconds):
        return qa_agent.ApiSmokeResult(
            name=case.name,
            path=case.path,
            request_json=case.request_json,
            response_json='{"message":"ok"}',
            status_code=case.expected_status,
            curl_exit_code=0,
            passed=True,
        )

    monkeypatch.setattr(qa_agent, "_run_api_case", fake_run_api_case)

    result = qa_agent.QAAgent().run(
        AgentInput(
            task_id=task_id,
            title="[BE] 회원가입 API 구현",
            body="\n".join(
                [
                    "회원가입 API를 구현한다.",
                    "",
                    "## Harness Metadata",
                    "- issue_number: 3",
                    "- labels: type: beFeature",
                    "",
                    "## Human QA Request",
                    "커밋 내역을 참고하여 QA를 진행하라.",
                ]
            ),
            state="In Progress",
            artifacts_root=artifact_root,
            timeout_seconds=30,
            retry_count=0,
            retry_limit=2,
        )
    )

    assert result.status == AgentStatus.SUCCESS
    report = artifact_root / task_id / "qa" / "qa-report.md"
    content = report.read_text(encoding="utf-8")
    assert "커밋 내역을 참고하여 QA를 진행하라." in content
    assert "## API Smoke Test 결과" in content
    assert "* 테스트 명: 회원가입 해피케이스" in content
    assert "* 의도한 대로 성공했는지: Y" in content
    assert "* api path: /api/members/signup" in content
    assert "## Human QA 체크리스트" in content
    assert "Swagger UI에서 회원가입 API의 summary와 description이 한국어로 보이는가" in content


def test_config_qa_agent_runs_security_runtime_checks(tmp_path, monkeypatch):
    target_repo = tmp_path / "studyHub"
    target_repo.mkdir()
    repo = Repo.init(target_repo)
    (target_repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    (target_repo / "apps/server").mkdir(parents=True)
    (target_repo / "apps/server/docker-compose.infra.local.yml").write_text(
        "services:\n  redis:\n    image: redis:7-alpine\n",
        encoding="utf-8",
    )
    repo.index.add(["README.md", "apps/server/docker-compose.infra.local.yml"])
    repo.index.commit("Initial commit")
    repo.git.checkout("-b", "config-5")

    artifact_root = tmp_path / "artifacts"
    task_id = "task-config"
    for path in [
        artifact_root / task_id / "plans" / "architecture.md",
        artifact_root / task_id / "plans" / "edge-case-checklist.md",
        artifact_root / task_id / "dev" / "commit-plan.md",
        artifact_root / task_id / "dev" / "dev-status.md",
        artifact_root / task_id / "dev" / "implementation.patch",
        artifact_root / task_id / "dev" / "test-report.md",
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n", encoding="utf-8")

    monkeypatch.setattr(qa_agent.settings, "target_repo_path", target_repo)
    monkeypatch.setattr(qa_agent.settings, "studyhub_api_base_url", "http://localhost:3001")
    monkeypatch.setattr(
        qa_agent.settings,
        "studyhub_swagger_url",
        "http://localhost:3001/swagger-ui/index.html",
    )
    monkeypatch.setattr(
        qa_agent,
        "_start_studyhub_api_if_needed",
        lambda repo_path, timeout_seconds: (None, "테스트 서버 사용"),
    )
    monkeypatch.setattr(qa_agent, "_is_api_alive", lambda: True)

    def fake_run_command(command, cwd, timeout_seconds):
        command_text = " ".join(command)
        if "SecurityConfigurationTest" in command_text:
            return 0, "BUILD SUCCESSFUL", ""
        if command[:3] == ["docker", "compose", "-f"]:
            return 0, "NAME             STATUS\nserver-redis-1   running", ""
        return 0, "", ""

    def fake_curl_json(method, url, payload, timeout_seconds):
        if url.endswith("/actuator/health"):
            return 0, '{"status":"UP"}', "", 200
        if url.endswith("/swagger-ui/index.html"):
            return 0, "<html>swagger</html>", "", 200
        if url.endswith("/api/protected-resource"):
            return 0, "", "", 401
        return 0, '{"message":"ok"}', "", 200

    def fake_run_api_case(case, timeout_seconds):
        return qa_agent.ApiSmokeResult(
            name=case.name,
            path=case.path,
            request_json=case.request_json,
            response_json='{"memberId":1}',
            status_code=201,
            curl_exit_code=0,
            passed=True,
        )

    monkeypatch.setattr(qa_agent, "_run_command", fake_run_command)
    monkeypatch.setattr(qa_agent, "_curl_json", fake_curl_json)
    monkeypatch.setattr(qa_agent, "_run_api_case", fake_run_api_case)

    result = qa_agent.QAAgent().run(
        AgentInput(
            task_id=task_id,
            title="Spring Security + JWT + Redis 인증 기반 설정 추가",
            body="\n".join(
                [
                    "Spring Security, JWT, Redis 설정을 추가한다.",
                    "",
                    "## Harness Metadata",
                    "- issue_number: 5",
                    "- labels: type: config",
                ]
            ),
            state="In Progress",
            artifacts_root=artifact_root,
            timeout_seconds=30,
            retry_count=0,
            retry_limit=2,
        )
    )

    assert result.status == AgentStatus.SUCCESS
    report = artifact_root / task_id / "qa" / "qa-report.md"
    content = report.read_text(encoding="utf-8")
    assert "## Config Runtime QA 결과" in content
    assert "Security 설정 테스트" in content
    assert "백엔드 Health" in content
    assert "Swagger 접근" in content
    assert "회원가입 API 인증 예외" in content
    assert "보호 API 미인증 차단" in content
    assert "Redis 컨테이너" in content
    assert "Spring Security 설정 테스트가 실제로 통과했는가" in content
    assert "이 이슈 타입에는 실행된 명령이 없습니다." not in content


def test_qa_summary_keeps_api_smoke_code_fences_balanced(tmp_path, monkeypatch):
    task_id = "task-1"
    report = tmp_path / "artifacts" / task_id / "qa" / "qa-report.md"
    report.parent.mkdir(parents=True)
    smoke_lines = []
    for index in range(6):
        smoke_lines.extend(
            [
                f"* 테스트 명: 케이스 {index}",
                "* 의도한 대로 성공했는지: Y",
                "* api path: /api/members/signup",
                "* request json:",
                "```json",
                '{"name":"QA사용자"}',
                "```",
                "* response json:",
                "```json",
                '{"message":"ok"}',
                "```",
                "* http status: 200",
                "",
            ]
        )
    report.write_text(
        "\n".join(
            [
                "# System QA Report",
                "",
                "- result: pass",
                "- branch: `feature(BE)-3`",
                "",
                "## 검증 체크리스트",
                "- [x] 백엔드 해피케이스 smoke test 통과",
                "",
                "## API Smoke Test 결과",
                *smoke_lines,
                "",
                "## Human QA 체크리스트",
                "- [ ] Swagger 확인",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(orchestration.settings, "artifact_root", tmp_path / "artifacts")

    service = orchestration.OrchestrationService(db=None)  # type: ignore[arg-type]
    summary = service._build_qa_summary_lines(task_id)
    rendered = "\n".join(summary)

    assert rendered.count("```json") == 12
    assert rendered.count("```") % 2 == 0
    assert "* 테스트 명: 케이스 5" in rendered
