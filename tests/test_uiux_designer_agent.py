from agents import uiux_designer_agent
from agents.base import AgentInput, AgentStatus
from agents.uiux_designer_agent import UIUXDesignerAgent


def test_uiux_designer_agent_writes_brief_and_planning_handoff(tmp_path, monkeypatch):
    target_repo = tmp_path / "target-app"
    web = target_repo / "apps" / "web"
    (web / "app").mkdir(parents=True)
    (web / "components").mkdir()
    (web / "package.json").write_text('{"dependencies":{"lucide-react":"latest"}}', encoding="utf-8")
    (web / "app" / "page.tsx").write_text("export default function Page(){return <main />}", encoding="utf-8")
    (web / "app" / "globals.css").write_text("body { margin: 0; }", encoding="utf-8")
    artifacts_root = tmp_path / "artifacts"

    monkeypatch.setattr(uiux_designer_agent.settings, "target_repo_path", target_repo)
    monkeypatch.setattr(uiux_designer_agent.settings, "qa_browser_enabled", False)
    monkeypatch.setattr(uiux_designer_agent.settings, "obsidian_vault_path", tmp_path / "missing-vault")

    result = UIUXDesignerAgent().run(
        AgentInput(
            task_id="uiux-task",
            title="메인 화면 온보딩 개선",
            body="\n".join(
                [
                    "topic: 메인 화면 온보딩 개선",
                    "target_user: 신규 사용자",
                    "routes:",
                    "- /",
                    "",
                    "## 요청 메모",
                    "첫 화면에서 다음 행동을 더 명확히 만들고 싶다.",
                ]
            ),
            state="UIUX Planning",
            artifacts_root=artifacts_root,
            timeout_seconds=60,
            retry_count=0,
            retry_limit=1,
        )
    )

    assert result.status == AgentStatus.SUCCESS
    brief = artifacts_root / "uiux-task" / "uiux-designer" / "uiux-design-brief.md"
    handoff = artifacts_root / "uiux-task" / "uiux-designer" / "planning-handoff.md"
    guide = artifacts_root / "uiux-task" / "uiux-designer" / "conversation-guide.md"
    assert brief.exists()
    assert handoff.exists()
    assert guide.exists()
    assert "UI/UX Design Brief" in brief.read_text(encoding="utf-8")
    handoff_text = handoff.read_text(encoding="utf-8")
    assert "## 목표" in handoff_text
    assert "## 디자인 방향" in handoff_text
    assert "## 완료 기준" in handoff_text
    assert "lucide-react" in handoff_text
