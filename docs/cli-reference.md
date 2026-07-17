# CLI Reference

권장 운영 흐름은 [`cli-usage-guide.md`](cli-usage-guide.md)를 본다.

## Metadata

```bash
harness agent-specs [--name qa]
harness playbooks [--name frontend-implementation]
```

Markdown Agent spec과 Codex playbook을 조회한다.

## Issue Context

```bash
harness sync --issue 13
harness sync --all
harness status --issue 13
```

GitHub issue context를 artifact로 저장하거나 artifact 기준 상태를 조회한다.

## Planning And Design

```bash
harness design --issue 13
harness redesign --issue 13 --note "수정 요청"
```

`plan`과 `replan`은 호환 alias이며 새 작업에서는 사용하지 않는다.

## Development Handoff

```bash
harness develop --issue 13
harness refactor --issue 13 --note "리팩터링 요청"
```

Codex가 직접 구현할 요청 artifact와 커밋 계획을 만든다.
이 명령은 target repo 파일을 수정하지 않는다.

## QA Handoff

```bash
harness qa --issue 13
harness re-qa --issue 13 --note "재검증 요청"
```

기획/설계안 기반 QA Plan, 체크리스트, 보고서 초안을 만든다.
자동 검증하지 않은 항목은 pass로 표시하지 않는다.

## Approval Record

```bash
harness approve --issue 13 --stage qa --approved-by rsy --notes "확인 완료"
harness manual-complete --issue 13 --stage dev --completed-by rsy
```

승인과 수동 완료 기록을 artifact로 남긴다.
`GITHUB_PROJECT_NUMBER`가 설정되어 있으면 승인 stage에 맞춰 GitHub Project Status도 이동한다.

## Documentation

```bash
harness document --issue 13
harness domain-knowledge --issue 13
harness document-harness \
  --title "하네스 변경" \
  --category "하네스 강화" \
  --feature "변경 내용" \
  --usage "운영 기준"
```

Notion 또는 Obsidian 정리용 artifact와 외부 기록을 생성한다.

## Automation Helper

```bash
harness auto-run --issue 13 --until qa
```

design/develop/qa artifact를 순차 생성한다.
실제 구현과 검증은 Codex가 수행한다.

## Project Status Mapping

| Command | Project Status |
| --- | --- |
| `create-issue` | `Backlog` |
| `design` | `Plan Review` |
| `approve --stage plan` | `Dev Ready` |
| `develop` | `Dev Review` |
| `approve --stage dev` | `QA Ready` |
| `qa` | `QA Review` |
| `approve --stage qa` | `Ready To Deploy` |
| `approve --stage deploy` | `Done` |
