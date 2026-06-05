from agents.base import AgentInput, AgentStatus
from agents import domain_knowledge_agent
from agents.domain_knowledge_agent import DomainKnowledgeAgent


# Domain Knowledge Agent가 Human QA 이후 Obsidian 지식 파일을 갱신하는지 검증한다.
def test_domain_knowledge_agent_writes_obsidian_context(tmp_path, monkeypatch):
    vault_path = tmp_path / "vault"
    artifacts_root = tmp_path / "artifacts"
    task_id = "task-1"
    (vault_path / "agent-context").mkdir(parents=True)
    (vault_path / "planning").mkdir(parents=True)
    (artifacts_root / task_id / "plans").mkdir(parents=True)
    (artifacts_root / task_id / "dev").mkdir(parents=True)
    (artifacts_root / task_id / "qa").mkdir(parents=True)

    (artifacts_root / task_id / "plans" / "architecture.md").write_text("사용자는 로그인 후 프로필을 확인한다.", encoding="utf-8")
    (artifacts_root / task_id / "dev" / "dev-status.md").write_text("프로필 모달 구현 완료", encoding="utf-8")
    (artifacts_root / task_id / "qa" / "qa-report.md").write_text("프로필 조회 QA 통과", encoding="utf-8")

    monkeypatch.setattr(domain_knowledge_agent.settings, "obsidian_vault_path", vault_path)
    monkeypatch.setattr(domain_knowledge_agent.settings, "github_owner", "passionryu")
    monkeypatch.setattr(domain_knowledge_agent.settings, "github_repo", "myMentalCare")

    result = DomainKnowledgeAgent().run(
        AgentInput(
            task_id=task_id,
            title="[FS] 프로필 조회 모달 구현",
            body="## Harness Metadata\n- issue_number: 5\n- labels: type: fullstackFeature",
            state="Ready To Deploy",
            artifacts_root=artifacts_root,
            timeout_seconds=60,
            retry_count=0,
            retry_limit=1,
        )
    )

    assert result.status == AgentStatus.SUCCESS
    assert (vault_path / "agent-context" / "implemented-features.md").exists()
    assert (vault_path / "planning" / "domain-decisions.md").exists()
    assert "프로필 조회 모달 구현" in (vault_path / "agent-context" / "planning-assistant-context.md").read_text(encoding="utf-8")
    assert "[#5](https://github.com/passionryu/myMentalCare/issues/5)" in (
        vault_path / "agent-context" / "implemented-features.md"
    ).read_text(encoding="utf-8")
