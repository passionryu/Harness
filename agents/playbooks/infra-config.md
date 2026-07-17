---
name: infra-config
version: 1
summary: 인프라와 설정 변경을 Codex가 범위 제한과 회귀 위험 중심으로 처리한다.
triggers:
  - "type: infra"
  - "type: config"
  - "환경 설정"
inputs:
  - approved_design
  - target_repository
  - runtime_environment
outputs:
  - implementation.patch
  - config-verification.md
  - rollback-notes.md
---
# Mission
환경 변수, 빌드 설정, 배포 설정, 보안 설정 변경을 최소 범위로 구현한다.
기능 구현과 분리된 설정 변경 playbook으로 처리해 FE/BE 구현 작업 오분류를 막는다.

# Call Conditions
- 작업이 Gradle, package script, Docker, Railway, GitHub Actions, env, security config에 해당할 때 사용한다.
- 화면 구현이나 도메인 정책 변경이 핵심이면 다른 playbook을 먼저 선택한다.
- 외부 서비스 secret이 필요한 경우 값을 추측하지 않는다.

# Codex Execution Steps
1. 변경 대상 환경과 실행 경로를 확인한다.
2. 현재 설정 파일과 문서를 읽어 중복 설정을 찾는다.
3. 최소 파일만 수정하고, secret 값은 템플릿 또는 문서에만 남긴다.
4. 로컬에서 검증 가능한 build, lint, health check를 실행한다.
5. 배포 환경에서만 확인 가능한 항목은 Human QA 체크리스트로 분리한다.
6. rollback 또는 되돌릴 설정을 짧게 기록한다.

# Evidence
- 변경한 설정 파일
- 실행한 명령과 결과
- 배포 환경에서 확인할 항목
- rollback notes

# Handoff
- 어떤 환경에서 어떤 값이 필요한지 명시한다.
- 사람이 확인해야 할 배포/헬스체크 URL을 적는다.
- 실패 시 되돌릴 커밋 또는 설정 키를 남긴다.

# Decision Rules
- secret은 코드에 쓰지 않는다.
- config 변경은 기능 구현과 분리한다.
- local, staging, production 차이를 명시한다.
- 빠른 검증보다 재현 가능한 검증 명령을 우선한다.

# Hard Rules
- infra/config 작업을 DDD 구현 작업으로 오분류하지 않는다.
- 실제 secret 값을 커밋하지 않는다.
- 배포 미검증 항목을 자동 PASS로 표시하지 않는다.
- 설정 변경 이유 없이 의존성을 올리지 않는다.

# Ask User When
- 외부 서비스 키, 도메인, 배포 권한이 필요할 때
- production에 영향을 주는 변경인지 불분명할 때
