---
name: documentation
version: 1
summary: 구현/QA 결과를 사람이 빠르게 이해할 수 있는 문서로 Codex가 정리한다.
triggers:
  - "harness document"
  - "Notion 문서화"
  - "작업 기록"
inputs:
  - github_issue
  - design_artifacts
  - dev_artifacts
  - qa_artifacts
outputs:
  - notion-ready-summary
  - implementation-history
  - decision-log
---
# Mission
작업 이력을 길게 복붙하지 않고 사람이 바로 회고할 수 있는 문서로 압축한다.
기능 목적, 실제 변경, 검증 결과, 남은 위험, 연결 링크를 분리해 기록한다.

# Call Conditions
- Human QA 이후 구현 이력을 Notion 또는 문서 저장소에 남길 때 사용한다.
- 하네스 세팅 변경도 동일하게 배경, 변경, 영향, 사용 방법으로 정리한다.
- 코드나 테스트를 다시 수행하는 단계가 아니다.

# Codex Execution Steps
1. 이슈, design, dev, QA 산출물에서 핵심 사실만 추출한다.
2. 긴 로그, request/response 전문, 반복 checklist는 부록이나 링크로 보낸다.
3. 사용자가 나중에 찾을 키워드를 제목과 요약에 포함한다.
4. 변경 전 문제, 변경 후 동작, 검증 근거를 분리한다.
5. Notion 업로드가 필요한 경우 지정된 데이터베이스 schema에 맞춰 작성한다.

# Evidence
- 참조한 이슈와 artifact 경로
- 문서화한 Notion URL 또는 로컬 문서 경로
- 생략한 상세 로그의 위치

# Handoff
- 문서 제목과 저장 위치를 남긴다.
- 후속 작업자가 바로 볼 핵심 쟁점을 3개 이하로 남긴다.
- 문서화하지 않은 범위가 있으면 이유를 적는다.

# Decision Rules
- 사람의 첫 화면 이해를 우선한다.
- 같은 말을 반복하는 긴 QA/Dev 로그는 요약한다.
- 결정 근거와 실행 결과를 섞지 않는다.
- 추후 작업 후보는 실행 완료처럼 쓰지 않는다.

# Hard Rules
- 전체 로그를 Notion 본문에 그대로 붙이지 않는다.
- 검증하지 않은 내용을 완료된 사실로 쓰지 않는다.
- 링크 없는 산출물 경로만 남기지 않는다.
- 사용자가 지정한 하네스 Notion 페이지가 있으면 임의 새 위치를 만들지 않는다.

# Ask User When
- 문서 저장 위치가 지정되지 않았고 기존 규칙으로 찾을 수 없을 때
- 외부 공유 가능한 표현과 개인 작업 기록 표현이 충돌할 때
