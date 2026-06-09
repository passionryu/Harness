from git import Repo

import agents.qa_agent as qa_agent
import orchestrator.services.orchestration as orchestration
from agents.base import AgentInput, AgentStatus
from agents.runners.playwright_browser_runner import (
    BrowserQaCheck,
    PlaywrightBrowserQaResult,
    format_playwright_report_section,
)
from orchestrator.services.qa_pdf import _markdown_to_html


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
    target_repo = tmp_path / "targetApp"
    target_repo.mkdir()
    repo = Repo.init(target_repo)
    (target_repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    controller = (
        target_repo
        / "apps/server/modules/bootstrap/app/src/main/kotlin/com/example/server/bootstrap/presentation/SignupController.kt"
    )
    controller.parent.mkdir(parents=True, exist_ok=True)
    controller.write_text(
        "\n".join(
            [
                "package com.example.server.bootstrap.presentation",
                "",
                "import org.springframework.web.bind.annotation.PostMapping",
                "import org.springframework.web.bind.annotation.RestController",
                "",
                "@RestController",
                "class SignupController {",
                "    @PostMapping(\"/api/members/signup\")",
                "    fun signup() {}",
                "}",
            ]
        ),
        encoding="utf-8",
    )
    repo.index.add(
        [
            "README.md",
            "apps/server/modules/bootstrap/app/src/main/kotlin/com/example/server/bootstrap/presentation/SignupController.kt",
        ]
    )
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
    monkeypatch.setattr(qa_agent.settings, "target_api_base_url", "http://localhost:18080")
    monkeypatch.setattr(
        qa_agent.settings,
        "target_swagger_url",
        "http://localhost:18080/swagger-ui/index.html",
    )
    monkeypatch.setattr(
        qa_agent,
        "_start_target_api_if_needed",
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
    assert "Swagger UI에서 대상 API의 summary와 description이 한국어로 보이는가" in content


def test_be_qa_agent_uses_dev_test_report_for_ai_chat_instead_of_signup_smoke(tmp_path, monkeypatch):
    target_repo = tmp_path / "myMentalCare"
    target_repo.mkdir()
    repo = Repo.init(target_repo)
    (target_repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    server_root = target_repo / "apps/server"
    server_root.mkdir(parents=True)
    (server_root / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")
    repo.index.add(["README.md", "apps/server/gradlew"])
    repo.index.commit("Initial commit")
    repo.git.checkout("-b", "feature(BE)-18")

    artifact_root = tmp_path / "artifacts"
    task_id = "task-ai-chat"
    test_report = artifact_root / task_id / "dev" / "test-report.md"
    test_report.parent.mkdir(parents=True, exist_ok=True)
    test_report.write_text(
        "\n".join(
            [
                "# Test Report",
                "",
                "## 실행 명령",
                "",
                "```bash",
                "./gradlew :modules:application:test --tests 'com.mymentalcare.server.application.aichat.*'",
                "./gradlew :modules:bootstrap:mymentalcare:test --tests 'com.mymentalcare.server.bootstrap.aichat.adapter.*'",
                "```",
            ]
        ),
        encoding="utf-8",
    )
    for path in [
        artifact_root / task_id / "plans" / "architecture.md",
        artifact_root / task_id / "plans" / "edge-case-checklist.md",
        artifact_root / task_id / "dev" / "commit-plan.md",
        artifact_root / task_id / "dev" / "dev-status.md",
        artifact_root / task_id / "dev" / "implementation.patch",
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n", encoding="utf-8")

    executed: list[tuple[list[str], str]] = []

    def fake_run_command(command, cwd, timeout_seconds):
        executed.append((command, str(cwd)))
        return 0, "BUILD SUCCESSFUL", ""

    monkeypatch.setattr(qa_agent.settings, "target_repo_path", target_repo)
    monkeypatch.setattr(qa_agent, "_run_command", fake_run_command)
    monkeypatch.setattr(qa_agent, "_start_target_api_if_needed", lambda repo_path, timeout_seconds: (None, "unexpected"))

    result = qa_agent.QAAgent().run(
        AgentInput(
            task_id=task_id,
            title="[BE] AI 대화 컨텍스트 최적화",
            body="\n".join(
                [
                    "AI 대화에서 일 단위 요약 메모리와 Redis 최근 메시지 캐시를 사용한다.",
                    "",
                    "## Harness Metadata",
                    "- issue_number: 18",
                    "- labels: type: beFeature",
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
    assert len(executed) == 2
    assert all(cwd.endswith("apps/server") for _, cwd in executed)
    report = artifact_root / task_id / "qa" / "qa-report.md"
    content = report.read_text(encoding="utf-8")
    assert "백엔드 Dev 테스트 명령 재실행 통과" in content
    assert "com.mymentalcare.server.application.aichat.*" in content
    assert "Dev test-report 명령 재실행으로 검증했습니다." in content
    assert "Redis 최근 메시지 캐시 hit 시 RDB 전체 대화 조회 없이 응답 컨텍스트가 구성되는가" in content
    assert "회원가입 해피케이스" not in content
    assert "/api/members/signup" not in content


def test_be_qa_agent_fails_unknown_backend_without_dev_test_commands(tmp_path, monkeypatch):
    target_repo = tmp_path / "targetApp"
    target_repo.mkdir()
    repo = Repo.init(target_repo)
    (target_repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    repo.index.add(["README.md"])
    repo.index.commit("Initial commit")
    repo.git.checkout("-b", "feature(BE)-19")

    artifact_root = tmp_path / "artifacts"
    task_id = "task-unknown-be"
    monkeypatch.setattr(qa_agent.settings, "target_repo_path", target_repo)

    result = qa_agent.QAAgent().run(
        AgentInput(
            task_id=task_id,
            title="[BE] 알 수 없는 백엔드 기능",
            body="\n".join(
                [
                    "하네스가 아직 모르는 백엔드 기능이다.",
                    "",
                    "## Harness Metadata",
                    "- issue_number: 19",
                    "- labels: type: beFeature",
                ]
            ),
            state="In Progress",
            artifacts_root=artifact_root,
            timeout_seconds=30,
            retry_count=0,
            retry_limit=2,
        )
    )

    assert result.status == AgentStatus.FAILED
    content = (artifact_root / task_id / "qa" / "qa-report.md").read_text(encoding="utf-8")
    assert "백엔드 System QA 지원 대상" in content
    assert "회원가입 해피케이스" not in content
    assert "기능별 QA Runner를 추가해야 합니다." in content


def test_config_qa_agent_runs_security_runtime_checks(tmp_path, monkeypatch):
    target_repo = tmp_path / "targetApp"
    target_repo.mkdir()
    repo = Repo.init(target_repo)
    (target_repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    (target_repo / "apps/server").mkdir(parents=True)
    controller = (
        target_repo
        / "apps/server/modules/bootstrap/app/src/main/kotlin/com/example/server/bootstrap/presentation/TestController.kt"
    )
    controller.parent.mkdir(parents=True, exist_ok=True)
    controller.write_text(
        "\n".join(
            [
                "package com.example.server.bootstrap.presentation",
                "",
                "import org.springframework.web.bind.annotation.GetMapping",
                "import org.springframework.web.bind.annotation.PostMapping",
                "import org.springframework.web.bind.annotation.RestController",
                "",
                "@RestController",
                "class TestController {",
                "    @PostMapping(\"/api/members/signup\")",
                "    fun signup() {}",
                "",
                "    @GetMapping(\"/api/protected-resource\")",
                "    fun protectedResource() {}",
                "}",
            ]
        ),
        encoding="utf-8",
    )
    (target_repo / "apps/server/docker-compose.infra.local.yml").write_text(
        "services:\n  redis:\n    image: redis:7-alpine\n",
        encoding="utf-8",
    )
    repo.index.add(
        [
            "README.md",
            "apps/server/docker-compose.infra.local.yml",
            "apps/server/modules/bootstrap/app/src/main/kotlin/com/example/server/bootstrap/presentation/TestController.kt",
        ]
    )
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
    monkeypatch.setattr(qa_agent.settings, "target_api_base_url", "http://localhost:3001")
    monkeypatch.setattr(
        qa_agent.settings,
        "target_swagger_url",
        "http://localhost:3001/swagger-ui/index.html",
    )
    monkeypatch.setattr(
        qa_agent,
        "_start_target_api_if_needed",
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
                "- [V] 백엔드 해피케이스 smoke test 통과",
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
    assert "- [V] 백엔드 해피케이스 smoke test 통과" in rendered

    assert rendered.count("```json") == 12
    assert rendered.count("```") % 2 == 0
    assert "* 테스트 명: 케이스 5" in rendered


def test_playwright_report_uses_v_marker_for_passed_checks(tmp_path):
    result = PlaywrightBrowserQaResult(
        should_run=True,
        passed=False,
        report_path=tmp_path / "playwright-report.md",
        screenshot_dir=tmp_path / "screenshots",
        checks=[
            BrowserQaCheck("홈 화면 스크린샷 저장", True, "01-home.png"),
            BrowserQaCheck("AI 채팅 화면 검증", False, "timeout"),
        ],
    )

    rendered = "\n".join(format_playwright_report_section(result))

    assert "- [V] 홈 화면 스크린샷 저장" in rendered
    assert "- [x]" not in rendered


def test_qa_pdf_markdown_normalizes_legacy_x_marker_to_v():
    html = _markdown_to_html("- [x] 프론트엔드 첫 화면 접근\n- [ ] AI 채팅 화면 검증")

    assert "[V] 프론트엔드 첫 화면 접근" in html
    assert "[x]" not in html
