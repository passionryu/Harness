# AI Harness Organization

## 목적

이 하네스는 완전 자율 개발자가 아니라 사람이 통제하는 Codex 실행 조직이다.
에이전트는 직접 앱 코드를 수정하지 않고, Codex가 읽을 수 있는 설계·구현·검증 artifact를 만든다.
실제 구현, 테스트, QA, 문서화는 Codex가 Markdown spec/playbook을 기준으로 수행한다.

## 에이전트 목록

| Agent | 역할 | 주요 산출물 |
| --- | --- | --- |
| Planning Assistant Agent | 확정 전 기획 대화와 요구사항 정리 | 기획 질문, 후보 기능, 사용자 문제 |
| Design Agent | GitHub Issue를 개발 가능한 설계로 변환 | architecture, API/화면 흐름, QA 기준 |
| UI/UX Designer Agent | UI/UX 방향성, 화면 흐름, 개선안 정리 | UI/UX 설계 handoff |
| Dev Agent | Codex 구현 요청과 커밋 계획 생성 | `codex-implementation-request.md`, `commit-plan.md` |
| Review Agent | 코드 품질 관점의 검토 기준 제공 | review checklist |
| QA Agent | 기획/설계 기반 QA 계획과 보고서 초안 생성 | `codex-qa-handoff.md`, `qa-checklist.md`, `qa-report.md` |
| Documentation Agent | 구현 이력을 Notion에 정리 | 하네스/서비스 기록 |
| Domain Knowledge Agent | 서비스 정책과 도메인 지식을 Obsidian에 정리 | 도메인 지식 노트 |

## Development Agent 운영

Dev Agent는 작업 타입과 이슈 내용을 읽고 필요한 playbook을 선택한다.

- FE 화면/폼/상태: `agents/playbooks/frontend-implementation.md`
- Kotlin Spring BE: `agents/playbooks/backend-kotlin-spring.md`
- FE/BE 연동: `agents/playbooks/api-connect.md`
- infra/config: `agents/playbooks/infra-config.md`
- 문서화: `agents/playbooks/documentation.md`

Dev Agent가 생성한 artifact는 Codex 실행 요청이다.
Codex는 artifact와 playbook을 읽고 target repo에서 브랜치 생성, 파일 수정, 테스트, 커밋, 푸시를 직접 수행한다.

## QA Agent 운영

QA Agent는 고정 smoke checklist를 재사용하지 않는다.
기획/설계안, 이슈 본문, 변경 diff를 기준으로 QA Plan을 새로 작성한다.

QA Plan은 다음을 포함해야 한다.

- 이 작업에서 실제로 검증해야 하는 핵심 기능
- 성공 케이스
- 실패 또는 엣지 케이스
- 회귀 위험
- 사람이 확인해야 하는 UI/문구/운영 항목
- 보고서에 들어갈 의미 있는 스크린샷 기준

자동으로 확인하지 않은 항목은 pass로 표시하지 않는다.

## Human QA Support

Human QA는 사람이 직접 수행한다.
하네스는 사람이 검증하기 쉽게 다음 정보만 제공한다.

- 확인해야 할 URL 또는 명령
- 기능 흐름 기준 체크리스트
- 성공/실패 케이스 설명
- 스크린샷 제목과 1~3줄 설명
- 사람 QA 승인 명령어

Discord 알림은 QA 단계 완료 시점에만 보낸다.

## 운영 원칙

- Markdown spec/playbook이 에이전트 행동의 원본이다.
- Python은 도구 호출기와 artifact 생성기로 제한한다.
- 앱 코드 구현은 Codex가 직접 수행한다.
- 불확실한 작업은 성공한 척하지 않고 artifact에 남은 위험을 기록한다.
- `harness status`는 DB가 아니라 artifact 디렉토리를 기준으로 현재 상태를 보여준다.
- `harness fix-develop`은 새 복구를 수행하지 않는 deprecated 안내 명령으로만 유지한다.
