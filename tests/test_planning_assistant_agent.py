from agents.base import AgentInput, AgentStatus
from agents import planning_assistant_agent
from agents.planning_assistant_agent import PlanningAssistantAgent


# Planning Assistant Agent가 Obsidian 맥락을 읽고 기획 보고서를 생성하는지 검증한다.
def test_planning_assistant_agent_writes_report_and_suggestion(tmp_path, monkeypatch):
    vault_path = tmp_path / "vault"
    artifacts_root = tmp_path / "artifacts"
    (vault_path / "agent-context").mkdir(parents=True)
    (vault_path / "planning").mkdir(parents=True)
    (vault_path / "references").mkdir(parents=True)
    (vault_path / "research").mkdir(parents=True)

    (vault_path / "agent-context" / "planning-assistant-context.md").write_text("myMentalCare는 따뜻한 감정 관리 서비스다.", encoding="utf-8")
    (vault_path / "agent-context" / "implemented-features.md").write_text("로그인과 프로필 조회가 구현되었다.", encoding="utf-8")
    (vault_path / "planning" / "user-problems.md").write_text("사용자는 자신의 감정을 꾸준히 기록하기 어렵다.", encoding="utf-8")
    (vault_path / "planning" / "feature-ideas.md").write_text("감정 기록, 알림, 채팅 도움", encoding="utf-8")
    (vault_path / "planning" / "roadmap-notes.md").write_text("감정 기록을 먼저 만든다.", encoding="utf-8")
    (vault_path / "planning" / "domain-decisions.md").write_text("사용자 메시지는 한국어로 제공한다.", encoding="utf-8")
    (vault_path / "references" / "product-examples.md").write_text("참고 제품 사례", encoding="utf-8")
    (vault_path / "research" / "mental-care-apps.md").write_text("마음 돌봄 앱 사례", encoding="utf-8")

    monkeypatch.setattr(planning_assistant_agent.settings, "obsidian_vault_path", vault_path)

    result = PlanningAssistantAgent().run(
        AgentInput(
            task_id="planning-task",
            title="감정 기록 기능",
            body="topic: 감정 기록 기능\n\n## 요청 메모\n부담 없는 기록 흐름을 기획한다.",
            state="Planning",
            artifacts_root=artifacts_root,
            timeout_seconds=60,
            retry_count=0,
            retry_limit=1,
        )
    )

    assert result.status == AgentStatus.SUCCESS
    assert (artifacts_root / "planning-task" / "planning-assistant" / "planning-assistant-report.md").exists()
    assert (artifacts_root / "planning-task" / "planning-assistant" / "issue-draft.md").exists()
    suggestion = (vault_path / "planning" / "planning-assistant-suggestions.md").read_text(encoding="utf-8")
    assert "감정 기록 기능" in suggestion
    assert "GitHub Issue 초안" in suggestion
