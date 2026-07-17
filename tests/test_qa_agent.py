from agents.base import AgentInput, AgentStatus
from agents.qa_agent import QAAgent, _infra_human_qa_checklist
from agents.qa_plan import build_qa_plan


def test_qa_plan_extracts_issue_specific_items():
    plan = build_qa_plan(
        "[FE] 체크인 모달",
        "\n".join(
            [
                "## QA 기준",
                "- 체크인 버튼을 누르면 모달이 열린다.",
                "- 모바일에서 텍스트가 겹치지 않는다.",
            ]
        ),
        ["fallback"],
    )

    assert plan.has_issue_specific_items is True
    assert [item.text for item in plan.items] == [
        "체크인 버튼을 누르면 모달이 열린다.",
        "모바일에서 텍스트가 겹치지 않는다.",
    ]
    assert {item.codex_hint for item in plan.items} == {"browser scenario verification"}


def test_qa_agent_writes_codex_handoff(tmp_path):
    result = QAAgent().run(
        AgentInput(
            task_id="issue-10",
            title="[FE] 체크인 모달",
            body="\n".join(
                [
                    "## 목표",
                    "체크인 모달을 추가한다.",
                    "",
                    "## QA 기준",
                    "- 체크인 버튼을 누르면 모달이 열린다.",
                    "- 모바일에서 텍스트가 겹치지 않는다.",
                    "",
                    "## Harness Metadata",
                    "- issue_number: 10",
                    "- labels: type: feFeature",
                ]
            ),
            state="stateless",
            artifacts_root=tmp_path / "artifacts",
            timeout_seconds=60,
            retry_count=0,
            retry_limit=0,
        )
    )

    assert result.status == AgentStatus.SUCCESS
    qa_dir = tmp_path / "artifacts" / "issue-10" / "qa"
    assert (qa_dir / "codex-qa-handoff.md").exists()
    assert (qa_dir / "qa-report.md").exists()
    report = (qa_dir / "qa-report.md").read_text(encoding="utf-8")
    assert "python_implementation_layer: removed" in report
    assert "Codex가 `agents/playbooks/qa-verification.md`" in report


def test_infra_human_qa_checklist_is_config_focused():
    items = _infra_human_qa_checklist("[Infra] Grafana", "Grafana 설정을 추가한다.")

    assert "health, status, logs 명령으로 정상 상태를 확인할 수 있는가" in items
