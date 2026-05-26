from git import Repo

import agents.qa_agent as qa_agent
from agents.base import AgentInput, AgentStatus


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
