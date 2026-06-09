import subprocess
from pathlib import Path

from agents.base import AgentStatus, ArtifactSpec
from agents.runners.base import DevRunnerContext, DevRunnerResult


class InfraRunner:
    name = "infra_runner"

    def can_handle(self, context: DevRunnerContext) -> bool:
        return context.issue_type in {"infra", "config"} and (context.repo_path / "apps/server").exists()

    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        if _is_security_jwt_redis_config(context):
            return _implement_security_jwt_redis_config(context)
        if _is_grafana_error_dashboard_and_alerting(context):
            return _implement_grafana_error_dashboard_and_alerting(context)
        if _is_backend_logging_policy(context):
            return _implement_backend_logging_policy(context)
        if _is_loki_grafana_alloy_monitoring(context):
            return _implement_loki_grafana_alloy_monitoring(context)

        report = context.task_dir / "infra-runner.md"
        report.write_text(
            "\n".join(
                [
                    "# Infra Runner",
                    "",
                    f"- runner: `{self.name}`",
                    f"- issue_type: `{context.issue_type}`",
                    f"- branch: `{context.branch_name}`",
                    "",
                    "## Status",
                    "",
                    "- Infra Runner가 선택되었습니다.",
                    "- 이 infra/config 계획은 현재 자동 구현 지원 목록에 없습니다.",
                    "- 가짜 성공을 보고하지 않고 중단했습니다.",
                    "",
                    "## 현재 자동 구현 지원 범위",
                    "",
                    "- Spring Security + JWT/토큰 + Redis 인증 기반 설정",
                    "",
                    "## 아직 수동 확인이 필요한 infra/config 예시",
                    "",
                    "- CI/CD workflow 설정",
                    "- 배포 환경 설정",
                    "- 신규 데이터베이스/메시지 브로커 구성",
                    "- nginx/reverse proxy 설정",
                    "- 모니터링/로그 수집 설정",
                    "- profile/secret 정책 변경",
                    "",
                    "## 다음 선택지",
                    "",
                    "1. 이 작업이 Spring Security + JWT + Redis 설정이라면 이슈 본문에 `Spring Security`, `JWT` 또는 `토큰`, `Redis`를 명확히 적은 뒤 다시 `@ai-harness develop`을 실행하세요.",
                    "2. 새로운 infra/config 패턴이라면 먼저 해당 패턴을 Infra Runner에 추가한 뒤 다시 실행하세요.",
                    "3. 자동화가 위험한 설정이라면 사람이 직접 구현하고 `@ai-harness qa` 또는 `@ai-harness status`로 상태를 확인하세요.",
                ]
            ),
            encoding="utf-8",
        )
        return DevRunnerResult(
            status=AgentStatus.NEEDS_HUMAN,
            summary="Infra Runner가 선택되었지만 이 infra/config 계획은 현재 자동 구현 지원 목록에 없습니다.",
            progress=[
                "- [x] Infra Runner 선택",
                "- [x] 지원 범위 확인",
                "- [ ] 자동 구현 지원 패턴 매칭",
            ],
            verification=[
                "## infra_runner",
                "",
                "- status: needs_human",
                "- reason: 이 infra/config 계획은 현재 자동 구현 지원 목록에 없습니다.",
                "",
                "## 현재 지원 범위",
                "",
                "- Spring Security + JWT/토큰 + Redis 인증 기반 설정",
                "- 백엔드 로그 파일 출력 및 민감정보 로깅 정책",
                "- Loki-Grafana-Alloy 로컬 로그 모니터링 스택",
                "- Grafana 에러 로그 대시보드 및 알림 provisioning",
                "",
                "## 다음 선택지",
                "",
                "1. 이슈 본문에 지원 패턴 키워드를 명확히 적고 다시 실행",
                "2. 필요한 infra/config 패턴을 runner에 먼저 추가",
                "3. 사람이 직접 구현 후 QA 실행",
            ],
            artifacts=[ArtifactSpec("infra-runner-report", report)],
            error="이 infra/config 작업은 현재 Infra Runner 자동 구현 지원 목록에 없습니다. 상세 지원 범위는 infra-runner.md를 확인하세요.",
        )


def _is_security_jwt_redis_config(context: DevRunnerContext) -> bool:
    haystack = f"{context.title}\n{context.body}".lower()
    has_security = "security" in haystack or "시큐리티" in haystack or "인증" in haystack
    has_token = "jwt" in haystack or "토큰" in haystack or "token" in haystack
    return context.issue_type == "config" and has_security and "redis" in haystack and has_token


# 백엔드 로그 파일 출력과 민감정보 로깅 정책 작업인지 판단한다.
def _is_backend_logging_policy(context: DevRunnerContext) -> bool:
    haystack = f"{context.title}\n{context.body}".lower()
    has_logging = "로그" in haystack or "logging" in haystack or "logback" in haystack
    has_policy = "민감정보" in haystack or "request-id" in haystack or "request id" in haystack or "traceid" in haystack
    return context.issue_type == "infra" and has_logging and has_policy


# Loki/Grafana/Alloy 로컬 모니터링 스택 작업인지 판단한다.
def _is_loki_grafana_alloy_monitoring(context: DevRunnerContext) -> bool:
    haystack = f"{context.title}\n{context.body}".lower()
    return (
        context.issue_type == "infra"
        and "loki" in haystack
        and "grafana" in haystack
        and "alloy" in haystack
    )


# Grafana 에러 로그 대시보드와 알림 구성 작업인지 판단한다.
def _is_grafana_error_dashboard_and_alerting(context: DevRunnerContext) -> bool:
    haystack = f"{context.title}\n{context.body}".lower()
    has_dashboard = "dashboard" in haystack or "대시보드" in haystack
    has_alert = "alert" in haystack or "알림" in haystack
    has_error_log = "error" in haystack or "exception" in haystack or "에러" in haystack
    return context.issue_type == "infra" and "grafana" in haystack and has_dashboard and has_alert and has_error_log


def _server_root(context: DevRunnerContext) -> Path:
    return context.repo_path / "apps/server"


# 현재 서버의 실행 bootstrap 모듈 경로를 찾는다.
def _bootstrap_module_root(context: DevRunnerContext) -> Path:
    bootstrap_root = context.repo_path / "apps/server/modules/bootstrap"
    candidates = [path for path in bootstrap_root.iterdir() if path.is_dir() and (path / "build.gradle.kts").exists()]
    if not candidates:
        raise FileNotFoundError(f"bootstrap module을 찾을 수 없습니다: {bootstrap_root}")
    return sorted(candidates)[0]


# Gradle에서 사용할 bootstrap 모듈 task path를 반환한다.
def _bootstrap_gradle_path(context: DevRunnerContext) -> str:
    module = _bootstrap_module_root(context).name
    return f":modules:bootstrap:{module}"


# bootstrap application class에서 Kotlin package 이름을 추출한다.
def _bootstrap_package(context: DevRunnerContext) -> str:
    module_root = _bootstrap_module_root(context)
    kotlin_files = sorted((module_root / "src/main/kotlin").rglob("*.kt"))
    for kotlin_file in kotlin_files:
        for line in kotlin_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("package "):
                return line.removeprefix("package ").strip()
    raise ValueError(f"bootstrap package를 찾을 수 없습니다: {module_root}")


# 설정 파일에서 spring.application.name 값을 가져온다.
def _application_name(context: DevRunnerContext) -> str:
    application_yml = _bootstrap_module_root(context) / "src/main/resources/application.yml"
    if not application_yml.exists():
        return _bootstrap_module_root(context).name
    lines = application_yml.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "application:":
            continue
        for nested in lines[index + 1 : index + 5]:
            if nested.strip().startswith("name:"):
                return nested.split(":", 1)[1].strip()
    return _bootstrap_module_root(context).name


# 프로젝트 이름을 환경변수 prefix로 사용할 수 있는 대문자 snake case로 변환한다.
def _env_prefix(context: DevRunnerContext) -> str:
    return _application_name(context).replace("-", "_").replace(".", "_").upper()


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _relative(context: DevRunnerContext, path: Path) -> str:
    return str(path.relative_to(context.repo_path))


def _stage_and_commit(context: DevRunnerContext, paths: list[str], message: str) -> str:
    existing_paths = [path for path in paths if (context.repo_path / path).exists()]
    context.repo.index.add(existing_paths)
    if not context.repo.index.diff("HEAD"):
        return "스킵: 스테이징된 변경사항 없음"
    commit = context.repo.index.commit(message)
    return commit.hexsha[:12]


def _run_command(command: list[str], cwd: Path, timeout_seconds: int) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return completed.returncode, completed.stdout, completed.stderr
    except FileNotFoundError as exc:
        return 127, "", str(exc)


def _replace_once(text: str, old: str, new: str) -> str:
    if old not in text:
        return text
    return text.replace(old, new, 1)


def _ensure_lines_after_anchor(text: str, anchor: str, lines: list[str]) -> str:
    missing = [line for line in lines if line not in text]
    if not missing:
        return text
    if anchor not in text:
        return text.rstrip() + "\n" + "\n".join(missing) + "\n"
    return _replace_once(text, anchor, anchor + "\n" + "\n".join(missing))


def _implement_security_jwt_redis_config(context: DevRunnerContext) -> DevRunnerResult:
    commits: list[str] = []
    progress: list[str] = []
    verification: list[str] = []

    dependency_paths = _write_security_dependency_files(context)
    commit_hash = _stage_and_commit(
        context,
        dependency_paths,
        f"[{context.feature_name}] : Security JWT Redis 의존성 추가",
    )
    commits.append(f"1. {commit_hash} [{context.feature_name}] : Security JWT Redis 의존성 추가")
    progress.append("- [x] step 1: Security/JWT/Redis 의존성 추가")

    config_paths = _write_security_config_files(context)
    commit_hash = _stage_and_commit(
        context,
        config_paths,
        f"[{context.feature_name}] : Security JWT Redis 설정 추가",
    )
    commits.append(f"2. {commit_hash} [{context.feature_name}] : Security JWT Redis 설정 추가")
    progress.append("- [x] step 2: Security/JWT/Redis 설정 추가")

    test_paths = _write_security_test_files(context)
    commit_hash = _stage_and_commit(
        context,
        test_paths,
        f"[{context.feature_name}] : Security 설정 테스트 추가",
    )
    commits.append(f"3. {commit_hash} [{context.feature_name}] : Security 설정 테스트 추가")
    progress.append("- [x] step 3: Security 설정 테스트 추가")

    gradle_module = _bootstrap_gradle_path(context)
    exit_code, stdout, stderr = _run_command(
        ["./gradlew", f"{gradle_module}:test", "--tests", "*SecurityConfigurationTest"],
        _server_root(context),
        context.timeout_seconds,
    )
    verification.extend(
        [
            f"## {gradle_module}:test --tests *SecurityConfigurationTest",
            "",
            f"- exit_code: {exit_code}",
            "",
            "### stdout",
            "```text",
            stdout.strip() or "(비어 있음)",
            "```",
            "",
            "### stderr",
            "```text",
            stderr.strip() or "(비어 있음)",
            "```",
        ]
    )
    progress.append("- [x] step 4: 검증 정리" if exit_code == 0 else "- [ ] step 4: 검증 정리")
    commits.append("4. no commit [검증 정리] : Security 설정 테스트 실행")

    report = context.task_dir / "infra-runner.md"
    report.write_text(
        "\n".join(
            [
                "# Infra Runner",
                "",
                f"- runner: `{InfraRunner.name}`",
                f"- branch: `{context.branch_name}`",
                "- feature: Spring Security + JWT + Redis 인증 기반 설정",
                "",
                "## Generated Scope",
                "",
                "- Spring Security 의존성",
                "- JWT 의존성",
                "- Redis 의존성",
                "- Redis local docker compose service",
                "- JWT TTL 설정: access token 1시간, refresh token 7일",
                "- 인증 없이 허용할 endpoint 정책",
                "- Security 설정 테스트",
                "",
                "## Verification",
                "",
                f"- command: `./gradlew {gradle_module}:test --tests '*SecurityConfigurationTest'`",
                f"- exit_code: `{exit_code}`",
            ]
        ),
        encoding="utf-8",
    )

    return DevRunnerResult(
        status=AgentStatus.SUCCESS if exit_code == 0 else AgentStatus.FAILED,
        summary=f"Spring Security/JWT/Redis 설정이 {context.branch_name}에서 완료되었습니다.",
        commits=commits,
        progress=progress,
        verification=verification,
        artifacts=[ArtifactSpec("infra-runner-report", report)],
        error=None if exit_code == 0 else "Spring Security/JWT/Redis 설정 테스트가 실패했습니다.",
    )


# 백엔드 로그 파일 출력과 요청 ID 기반 추적 설정을 생성한다.
def _implement_backend_logging_policy(context: DevRunnerContext) -> DevRunnerResult:
    paths = _write_backend_logging_policy_files(context)
    commit_hash = _stage_and_commit(
        context,
        paths,
        f"[{context.feature_name}] : 로그 파일 출력과 요청 ID 로깅 추가",
    )

    gradle_module = _bootstrap_gradle_path(context)
    exit_code, stdout, stderr = _run_command(
        ["./gradlew", f"{gradle_module}:test", "--tests", "*RequestIdLoggingFilterTest"],
        _server_root(context),
        context.timeout_seconds,
    )

    verification = [
        f"## {gradle_module}:test --tests *RequestIdLoggingFilterTest",
        "",
        f"- exit_code: {exit_code}",
        "",
        "### stdout",
        "```text",
        stdout.strip() or "(비어 있음)",
        "```",
        "",
        "### stderr",
        "```text",
        stderr.strip() or "(비어 있음)",
        "```",
    ]

    report = context.task_dir / "infra-runner.md"
    report.write_text(
        "\n".join(
            [
                "# Infra Runner",
                "",
                f"- runner: `{InfraRunner.name}`",
                f"- branch: `{context.branch_name}`",
                "- feature: 백엔드 로그 파일 출력 및 민감정보 로깅 정책",
                "",
                "## Generated Scope",
                "",
                "- `logs/mymentalcare-api.log` 파일 로그 출력",
                "- 일 단위 + 크기 단위 rolling 정책",
                "- `X-Request-Id` 기반 requestId/traceId MDC 기록",
                "- 민감정보 로깅 금지 정책 문서",
                "- 요청 ID 필터 단위 테스트",
                "",
                "## Verification",
                "",
                f"- command: `./gradlew {gradle_module}:test --tests '*RequestIdLoggingFilterTest'`",
                f"- exit_code: `{exit_code}`",
            ]
        ),
        encoding="utf-8",
    )

    return DevRunnerResult(
        status=AgentStatus.SUCCESS if exit_code == 0 else AgentStatus.FAILED,
        summary=f"백엔드 로그 파일 출력 및 민감정보 로깅 정책이 {context.branch_name}에서 완료되었습니다.",
        commits=[f"1. {commit_hash} [{context.feature_name}] : 로그 파일 출력과 요청 ID 로깅 추가"],
        progress=[
            "- [x] step 1: 로그 파일 출력 설정",
            "- [x] step 2: 요청 ID 로깅 필터 추가",
            "- [x] step 3: 민감정보 로깅 정책 문서화",
            "- [x] step 4: 요청 ID 필터 테스트 실행" if exit_code == 0 else "- [ ] step 4: 요청 ID 필터 테스트 실행",
        ],
        verification=verification,
        artifacts=[ArtifactSpec("infra-runner-report", report)],
        error=None if exit_code == 0 else "백엔드 로그 파일 출력 설정 테스트가 실패했습니다.",
    )


# Loki, Grafana, Alloy 로컬 로그 모니터링 스택 파일을 생성한다.
def _implement_loki_grafana_alloy_monitoring(context: DevRunnerContext) -> DevRunnerResult:
    paths = _write_loki_grafana_alloy_files(context)
    commit_hash = _stage_and_commit(
        context,
        paths,
        f"[{context.feature_name}] : 모니터링 compose와 provisioning 추가",
    )

    exit_code, stdout, stderr = _run_command(
        ["docker", "compose", "-f", "docker-compose.monitoring.yml", "config"],
        _server_root(context),
        context.timeout_seconds,
    )

    verification = [
        "## docker compose -f docker-compose.monitoring.yml config",
        "",
        f"- exit_code: {exit_code}",
        "",
        "### stdout",
        "```text",
        stdout.strip()[-3000:] or "(비어 있음)",
        "```",
        "",
        "### stderr",
        "```text",
        stderr.strip()[-3000:] or "(비어 있음)",
        "```",
    ]

    report = context.task_dir / "infra-runner.md"
    report.write_text(
        "\n".join(
            [
                "# Infra Runner",
                "",
                f"- runner: `{InfraRunner.name}`",
                f"- branch: `{context.branch_name}`",
                "- feature: Loki-Grafana-Alloy 로컬 로그 모니터링 스택",
                "",
                "## Generated Scope",
                "",
                "- Loki container",
                "- Grafana container",
                "- Grafana Loki datasource provisioning",
                "- Alloy file log collection",
                "- LogQL 예시와 실행 문서",
                "",
                "## Verification",
                "",
                "- command: `docker compose -f docker-compose.monitoring.yml config`",
                f"- exit_code: `{exit_code}`",
            ]
        ),
        encoding="utf-8",
    )

    return DevRunnerResult(
        status=AgentStatus.SUCCESS if exit_code == 0 else AgentStatus.FAILED,
        summary=f"Loki/Grafana/Alloy 로컬 모니터링 스택이 {context.branch_name}에서 완료되었습니다.",
        commits=[f"1. {commit_hash} [{context.feature_name}] : 모니터링 compose와 provisioning 추가"],
        progress=[
            "- [x] step 1: Loki/Grafana/Alloy compose 추가",
            "- [x] step 2: Grafana Loki datasource provisioning 추가",
            "- [x] step 3: Alloy 로그 파일 수집 설정 추가",
            "- [x] step 4: 모니터링 실행 문서 추가",
            "- [x] step 5: compose config 검증" if exit_code == 0 else "- [ ] step 5: compose config 검증",
        ],
        verification=verification,
        artifacts=[ArtifactSpec("infra-runner-report", report)],
        error=None if exit_code == 0 else "Loki/Grafana/Alloy compose 설정 검증이 실패했습니다.",
    )


# Grafana 에러 로그 대시보드와 알림 provisioning 파일을 생성한다.
def _implement_grafana_error_dashboard_and_alerting(context: DevRunnerContext) -> DevRunnerResult:
    paths = _write_grafana_error_dashboard_and_alerting_files(context)
    commit_hash = _stage_and_commit(
        context,
        paths,
        f"[{context.feature_name}] : Grafana 에러 로그 대시보드와 알림 구성 추가",
    )

    exit_code, stdout, stderr = _run_command(
        ["docker", "compose", "-f", "docker-compose.monitoring.yml", "config"],
        _server_root(context),
        context.timeout_seconds,
    )

    verification = [
        "## docker compose -f docker-compose.monitoring.yml config",
        "",
        f"- exit_code: {exit_code}",
        "",
        "## Grafana provisioning",
        "",
        "- dashboards: `monitoring/grafana/provisioning/dashboards/mymentalcare-logs.yml`",
        "- dashboard json: `monitoring/grafana/provisioning/dashboards/json/mymentalcare-error-logs.json`",
        "- alerting: `monitoring/grafana/provisioning/alerting/mymentalcare-log-alerts.yml`",
        "",
        "## stdout",
        "```text",
        stdout.strip()[-3000:] or "(비어 있음)",
        "```",
        "",
        "## stderr",
        "```text",
        stderr.strip()[-3000:] or "(비어 있음)",
        "```",
    ]

    report = context.task_dir / "infra-runner.md"
    report.write_text(
        "\n".join(
            [
                "# Infra Runner",
                "",
                f"- runner: `{InfraRunner.name}`",
                f"- branch: `{context.branch_name}`",
                "- feature: Grafana 에러 로그 대시보드 및 알림 구성",
                "",
                "## Generated Scope",
                "",
                "- Grafana dashboard provider",
                "- myMentalCare 에러 로그 dashboard JSON",
                "- Grafana alerting provisioning",
                "- Discord webhook 환경변수 연결 문서",
                "- 운영자가 자주 쓰는 LogQL 쿼리 문서",
                "",
                "## Verification",
                "",
                "- command: `docker compose -f docker-compose.monitoring.yml config`",
                f"- exit_code: `{exit_code}`",
            ]
        ),
        encoding="utf-8",
    )

    return DevRunnerResult(
        status=AgentStatus.SUCCESS if exit_code == 0 else AgentStatus.FAILED,
        summary=f"Grafana 에러 로그 대시보드와 알림 구성이 {context.branch_name}에서 완료되었습니다.",
        commits=[f"1. {commit_hash} [{context.feature_name}] : Grafana 에러 로그 대시보드와 알림 구성 추가"],
        progress=[
            "- [x] step 1: Grafana dashboard provider 추가",
            "- [x] step 2: 에러 로그 dashboard JSON 추가",
            "- [x] step 3: Grafana alerting provisioning 추가",
            "- [x] step 4: Discord webhook 연동 문서 추가",
            "- [x] step 5: compose config 검증" if exit_code == 0 else "- [ ] step 5: compose config 검증",
        ],
        verification=verification,
        artifacts=[ArtifactSpec("infra-runner-report", report)],
        error=None if exit_code == 0 else "Grafana 대시보드/알림 provisioning compose 검증이 실패했습니다.",
    )


# Loki/Grafana/Alloy 모니터링 스택에 필요한 파일을 작성한다.
def _write_loki_grafana_alloy_files(context: DevRunnerContext) -> list[str]:
    paths: list[str] = []

    compose = _server_root(context) / "docker-compose.monitoring.yml"
    _write_text(compose, _monitoring_compose_content())
    paths.append(_relative(context, compose))

    loki_config = _server_root(context) / "monitoring/loki/loki-config.yml"
    _write_text(loki_config, _loki_config_content())
    paths.append(_relative(context, loki_config))

    datasource = _server_root(context) / "monitoring/grafana/provisioning/datasources/loki.yml"
    _write_text(datasource, _grafana_loki_datasource_content())
    paths.append(_relative(context, datasource))

    alloy_config = _server_root(context) / "monitoring/alloy/config.alloy"
    _write_text(alloy_config, _alloy_config_content())
    paths.append(_relative(context, alloy_config))

    docs = context.repo_path / "docs/observability/loki-grafana-alloy-local.md"
    _write_text(docs, _monitoring_docs_content())
    paths.append(_relative(context, docs))
    return paths


# Grafana 에러 로그 대시보드와 알림 구성 파일을 작성한다.
def _write_grafana_error_dashboard_and_alerting_files(context: DevRunnerContext) -> list[str]:
    paths: list[str] = []

    datasource = _server_root(context) / "monitoring/grafana/provisioning/datasources/loki.yml"
    _write_text(datasource, _grafana_loki_datasource_content())
    paths.append(_relative(context, datasource))

    provider = _server_root(context) / "monitoring/grafana/provisioning/dashboards/mymentalcare-logs.yml"
    _write_text(provider, _grafana_dashboard_provider_content())
    paths.append(_relative(context, provider))

    dashboard = _server_root(context) / "monitoring/grafana/provisioning/dashboards/json/mymentalcare-error-logs.json"
    _write_text(dashboard, _grafana_error_log_dashboard_content())
    paths.append(_relative(context, dashboard))

    alerting = _server_root(context) / "monitoring/grafana/provisioning/alerting/mymentalcare-log-alerts.yml"
    _write_text(alerting, _grafana_log_alerting_content())
    paths.append(_relative(context, alerting))

    docs = context.repo_path / "docs/observability/grafana-error-dashboard-alerting.md"
    _write_text(docs, _grafana_error_dashboard_docs_content())
    paths.append(_relative(context, docs))
    return paths


# Grafana dashboard provider 내용을 반환한다.
def _grafana_dashboard_provider_content() -> str:
    return """apiVersion: 1

providers:
  - name: mymentalcare-log-dashboards
    orgId: 1
    folder: myMentalCare Observability
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    allowUiUpdates: true
    options:
      path: /etc/grafana/provisioning/dashboards/json
"""


# myMentalCare 로그 대시보드 JSON 내용을 반환한다.
def _grafana_error_log_dashboard_content() -> str:
    return r"""{
  "uid": "mymentalcare-error-logs",
  "title": "myMentalCare 에러 로그 모니터링",
  "tags": ["myMentalCare", "logs", "local"],
  "timezone": "browser",
  "schemaVersion": 39,
  "version": 1,
  "refresh": "30s",
  "time": {
    "from": "now-1h",
    "to": "now"
  },
  "panels": [
    {
      "id": 1,
      "type": "logs",
      "title": "전체 백엔드 로그",
      "datasource": {"type": "loki", "uid": "mymentalcare-loki"},
      "gridPos": {"h": 8, "w": 24, "x": 0, "y": 0},
      "targets": [
        {
          "refId": "A",
          "expr": "{service=\"mymentalcare-api\"}",
          "queryType": "range"
        }
      ],
      "options": {
        "showTime": true,
        "showLabels": false,
        "wrapLogMessage": true,
        "dedupStrategy": "none",
        "sortOrder": "Descending"
      }
    },
    {
      "id": 2,
      "type": "logs",
      "title": "ERROR / Exception 로그",
      "datasource": {"type": "loki", "uid": "mymentalcare-loki"},
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
      "targets": [
        {
          "refId": "A",
          "expr": "{service=\"mymentalcare-api\"} |~ \"ERROR|Exception\"",
          "queryType": "range"
        }
      ],
      "options": {"showTime": true, "showLabels": false, "wrapLogMessage": true, "sortOrder": "Descending"}
    },
    {
      "id": 3,
      "type": "logs",
      "title": "로그인 실패 로그",
      "datasource": {"type": "loki", "uid": "mymentalcare-loki"},
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
      "targets": [
        {
          "refId": "A",
          "expr": "{service=\"mymentalcare-api\"} |= \"[로그인]\" |= \"실패\"",
          "queryType": "range"
        }
      ],
      "options": {"showTime": true, "showLabels": false, "wrapLogMessage": true, "sortOrder": "Descending"}
    },
    {
      "id": 4,
      "type": "logs",
      "title": "OpenAI 호출 실패 로그",
      "datasource": {"type": "loki", "uid": "mymentalcare-loki"},
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 16},
      "targets": [
        {
          "refId": "A",
          "expr": "{service=\"mymentalcare-api\"} |~ \"OpenAI|AI 마음 대화\" |~ \"실패|ERROR|Exception\"",
          "queryType": "range"
        }
      ],
      "options": {"showTime": true, "showLabels": false, "wrapLogMessage": true, "sortOrder": "Descending"}
    },
    {
      "id": 5,
      "type": "logs",
      "title": "Redis / DB 연결 실패 로그",
      "datasource": {"type": "loki", "uid": "mymentalcare-loki"},
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 16},
      "targets": [
        {
          "refId": "A",
          "expr": "{service=\"mymentalcare-api\"} |~ \"Redis|Hikari|MariaDB|JDBC|database|Connection\" |~ \"ERROR|Exception|failed|실패\"",
          "queryType": "range"
        }
      ],
      "options": {"showTime": true, "showLabels": false, "wrapLogMessage": true, "sortOrder": "Descending"}
    },
    {
      "id": 6,
      "type": "logs",
      "title": "위기 감지 운영 로그",
      "datasource": {"type": "loki", "uid": "mymentalcare-loki"},
      "gridPos": {"h": 8, "w": 24, "x": 0, "y": 24},
      "targets": [
        {
          "refId": "A",
          "expr": "{service=\"mymentalcare-api\"} |~ \"위기|crisis|Crisis\"",
          "queryType": "range"
        }
      ],
      "options": {"showTime": true, "showLabels": false, "wrapLogMessage": true, "sortOrder": "Descending"}
    }
  ]
}
"""


# Grafana alerting provisioning 내용을 반환한다.
def _grafana_log_alerting_content() -> str:
    return r"""apiVersion: 1

contactPoints:
  - orgId: 1
    name: mymentalcare-discord
    receivers:
      - uid: mymentalcare-discord-webhook
        type: discord
        settings:
          url: ${GRAFANA_DISCORD_WEBHOOK_URL}
          title: "[myMentalCare 로그 알림] {{ template \"default.title\" . }}"
          message: |
            Grafana가 myMentalCare 백엔드 로그 이상 징후를 감지했습니다.
            Grafana 대시보드에서 세부 로그를 확인하세요.

policies:
  - orgId: 1
    receiver: mymentalcare-discord
    group_by:
      - grafana_folder
      - alertname

groups:
  - orgId: 1
    name: mymentalcare-log-alerts
    folder: myMentalCare Observability
    interval: 1m
    rules:
      - uid: mymentalcare-error-log-detected
        title: myMentalCare ERROR 로그 감지
        condition: C
        for: 0m
        noDataState: OK
        execErrState: Error
        annotations:
          summary: myMentalCare 백엔드 ERROR 로그가 감지되었습니다.
          description: 최근 5분 동안 myMentalCare API 로그에서 ERROR 문자열이 감지되었습니다.
        labels:
          service: mymentalcare-api
          severity: warning
        data:
          - refId: A
            datasourceUid: mymentalcare-loki
            relativeTimeRange:
              from: 300
              to: 0
            model:
              refId: A
              expr: sum(count_over_time({service="mymentalcare-api"} |= "ERROR" [5m]))
              queryType: instant
          - refId: C
            datasourceUid: __expr__
            relativeTimeRange:
              from: 0
              to: 0
            model:
              refId: C
              type: threshold
              expression: A
              conditions:
                - evaluator:
                    params:
                      - 0
                    type: gt
                  operator:
                    type: and
                  query:
                    params:
                      - C
                  reducer:
                    type: last
                  type: query
      - uid: mymentalcare-openai-failure-detected
        title: myMentalCare OpenAI 호출 실패 감지
        condition: C
        for: 0m
        noDataState: OK
        execErrState: Error
        annotations:
          summary: myMentalCare OpenAI 호출 실패 로그가 감지되었습니다.
          description: 최근 5분 동안 AI 마음 대화 또는 OpenAI 실패 로그가 감지되었습니다.
        labels:
          service: mymentalcare-api
          severity: warning
        data:
          - refId: A
            datasourceUid: mymentalcare-loki
            relativeTimeRange:
              from: 300
              to: 0
            model:
              refId: A
              expr: sum(count_over_time({service="mymentalcare-api"} |~ "OpenAI|AI 마음 대화" |~ "실패|ERROR|Exception" [5m]))
              queryType: instant
          - refId: C
            datasourceUid: __expr__
            relativeTimeRange:
              from: 0
              to: 0
            model:
              refId: C
              type: threshold
              expression: A
              conditions:
                - evaluator:
                    params:
                      - 0
                    type: gt
                  operator:
                    type: and
                  query:
                    params:
                      - C
                  reducer:
                    type: last
                  type: query
"""


# Grafana 에러 대시보드와 알림 문서 내용을 반환한다.
def _grafana_error_dashboard_docs_content() -> str:
    return """# Grafana 에러 로그 대시보드 및 알림 구성

## 목적

myMentalCare 백엔드의 장애 징후를 Grafana에서 빠르게 확인한다.
운영자는 전체 로그, ERROR/Exception, 로그인 실패, OpenAI 호출 실패, Redis/DB 연결 실패, 위기 감지 로그를 한 화면에서 확인한다.

## 사전 조건

- Loki/Grafana/Alloy 로컬 스택이 실행되어 있어야 한다.
- API 서버는 `LOG_PATH=/Users/rsy/Desktop/myPlayGround/myMentalCare/apps/server/logs`로 실행되어야 한다.
- Discord 알림을 쓰려면 로컬 환경변수 `GRAFANA_DISCORD_WEBHOOK_URL`을 설정한다.

## 실행

```bash
cd /Users/rsy/Desktop/myPlayGround/myMentalCare/apps/server
docker compose -f docker-compose.monitoring.yml up -d
```

## 접속

- Grafana: http://localhost:3002
- Dashboard: `myMentalCare Observability / myMentalCare 에러 로그 모니터링`

## 주요 LogQL

전체 백엔드 로그를 본다.

```logql
{service="mymentalcare-api"}
```

ERROR 로그를 본다.

```logql
{service="mymentalcare-api"} |= "ERROR"
```

예외 로그를 본다.

```logql
{service="mymentalcare-api"} |= "Exception"
```

로그인 실패 로그를 본다.

```logql
{service="mymentalcare-api"} |= "[로그인]" |= "실패"
```

OpenAI 호출 실패 로그를 본다.

```logql
{service="mymentalcare-api"} |~ "OpenAI|AI 마음 대화" |~ "실패|ERROR|Exception"
```

Redis/DB 연결 실패 로그를 본다.

```logql
{service="mymentalcare-api"} |~ "Redis|Hikari|MariaDB|JDBC|database|Connection" |~ "ERROR|Exception|failed|실패"
```

위기 감지 운영 로그를 본다.

```logql
{service="mymentalcare-api"} |~ "위기|crisis|Crisis"
```

## Discord 알림

Grafana alerting provisioning은 `GRAFANA_DISCORD_WEBHOOK_URL`을 참조한다.
이 값은 코드에 커밋하지 않는다.

```bash
export GRAFANA_DISCORD_WEBHOOK_URL="Discord Webhook URL"
docker compose -f docker-compose.monitoring.yml up -d
```

## 민감정보 정책

대시보드와 알림은 로그 원문을 기반으로 동작한다.
따라서 애플리케이션 로그에는 사용자 채팅 원문, 감정 기록 원문, 토큰, 비밀번호, OpenAI API Key, Discord Webhook URL을 남기지 않는다.

## 검증 방법

1. API 서버를 실행한다.
2. `GET /actuator/health`, 로그인 실패 요청 등 예시 요청을 만든다.
3. Grafana 대시보드에서 로그가 조회되는지 확인한다.
4. ERROR 테스트 로그를 남긴 뒤 alert rule이 평가되는지 확인한다.
"""


# 모니터링 docker compose 내용을 반환한다.
def _monitoring_compose_content() -> str:
    return """services:
  loki:
    image: grafana/loki:3.4.2
    command: -config.file=/etc/loki/local-config.yml
    ports:
      - "3100:3100"
    volumes:
      - ./monitoring/loki/loki-config.yml:/etc/loki/local-config.yml:ro
      - loki-data:/loki
    restart: unless-stopped

  grafana:
    image: grafana/grafana:11.5.2
    ports:
      - "3002:3000"
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: admin
      GF_USERS_ALLOW_SIGN_UP: "false"
      GRAFANA_DISCORD_WEBHOOK_URL: ${GRAFANA_DISCORD_WEBHOOK_URL:-}
    volumes:
      - grafana-data:/var/lib/grafana
      - ./monitoring/grafana/provisioning:/etc/grafana/provisioning:ro
    depends_on:
      - loki
    restart: unless-stopped

  alloy:
    image: grafana/alloy:v1.6.1
    command:
      - run
      - --server.http.listen-addr=0.0.0.0:12345
      - /etc/alloy/config.alloy
    ports:
      - "12345:12345"
    volumes:
      - ./monitoring/alloy/config.alloy:/etc/alloy/config.alloy:ro
      - ./logs:/var/log/mymentalcare:ro
    depends_on:
      - loki
    restart: unless-stopped

volumes:
  loki-data:
  grafana-data:
"""


# Loki 로컬 설정 내용을 반환한다.
def _loki_config_content() -> str:
    return """auth_enabled: false

server:
  http_listen_port: 3100

common:
  path_prefix: /loki
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules

schema_config:
  configs:
    - from: 2024-01-01
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

limits_config:
  retention_period: 336h

compactor:
  working_directory: /loki/compactor
  retention_enabled: true
  delete_request_store: filesystem
"""


# Grafana Loki datasource provisioning 내용을 반환한다.
def _grafana_loki_datasource_content() -> str:
    return """apiVersion: 1

datasources:
  - name: Loki
    type: loki
    uid: mymentalcare-loki
    access: proxy
    url: http://loki:3100
    isDefault: true
    editable: true
    jsonData:
      maxLines: 1000
"""


# Alloy 로그 파일 수집 설정 내용을 반환한다.
def _alloy_config_content() -> str:
    return """local.file_match "mymentalcare_api" {
  path_targets = [
    {
      "__path__" = "/var/log/mymentalcare/mymentalcare-api.log",
      "service"  = "mymentalcare-api",
      "env"      = "local",
    },
  ]
}

loki.source.file "mymentalcare_api" {
  targets    = local.file_match.mymentalcare_api.targets
  forward_to = [loki.write.local.receiver]
}

loki.write "local" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}
"""


# Loki/Grafana/Alloy 로컬 실행 문서를 반환한다.
def _monitoring_docs_content() -> str:
    return """# Loki-Grafana-Alloy 로컬 로그 모니터링

## 목적

로컬 개발 중 myMentalCare API 서버 로그를 파일로 남기고, Alloy가 해당 파일을 읽어 Loki로 전송한다.
개발자는 Grafana Explore에서 로그를 검색해 장애 원인과 요청 흐름을 확인한다.

## 실행

```bash
cd /Users/rsy/Desktop/myPlayGround/myMentalCare/apps/server
mkdir -p logs
docker compose -f docker-compose.monitoring.yml up -d
```

## 종료

```bash
cd /Users/rsy/Desktop/myPlayGround/myMentalCare/apps/server
docker compose -f docker-compose.monitoring.yml down
```

## 접속 정보

- Grafana: http://localhost:3002
- ID: `admin`
- Password: `admin`
- Loki API: http://localhost:3100
- Alloy UI: http://localhost:12345

## 로그 흐름

```text
myMentalCare API
-> logs/mymentalcare-api.log
-> Alloy
-> Loki
-> Grafana Explore
```

## LogQL 예시

전체 API 로그를 확인한다.

```logql
{service="mymentalcare-api"}
```

에러 로그를 확인한다.

```logql
{service="mymentalcare-api"} |= "ERROR"
```

예외 로그를 확인한다.

```logql
{service="mymentalcare-api"} |= "Exception"
```

특정 요청 ID를 확인한다.

```logql
{service="mymentalcare-api"} |= "requestId="
```

## 주의

- 모니터링 스택은 API/Web/MariaDB/Redis 실행과 분리된다.
- 모니터링 스택이 실패해도 애플리케이션 실행을 막지 않는다.
- `logs/*.log`는 Git에 올리지 않는다.
- 비밀번호, 토큰, OpenAI API Key, Discord Webhook URL, 사용자 채팅 원문은 로그에 남기지 않는다.
"""


# 백엔드 로그 파일 출력과 민감정보 로깅 정책에 필요한 파일을 작성한다.
def _write_backend_logging_policy_files(context: DevRunnerContext) -> list[str]:
    paths: list[str] = []
    module_root = _bootstrap_module_root(context)
    package_name = _bootstrap_package(context)

    logback = module_root / "src/main/resources/logback-spring.xml"
    _write_text(logback, _logback_spring_content())
    paths.append(_relative(context, logback))

    filter_file = module_root / "src/main/kotlin" / Path(*package_name.split(".")) / "config" / "RequestIdLoggingFilter.kt"
    _write_text(filter_file, _request_id_logging_filter_content(package_name))
    paths.append(_relative(context, filter_file))

    test_file = module_root / "src/test/kotlin" / Path(*package_name.split(".")) / "config" / "RequestIdLoggingFilterTest.kt"
    _write_text(test_file, _request_id_logging_filter_test_content(package_name))
    paths.append(_relative(context, test_file))

    policy = context.repo_path / "docs/observability/logging-policy.md"
    _write_text(policy, _logging_policy_content())
    paths.append(_relative(context, policy))
    return paths


# Spring Boot logback 파일 로그 설정 내용을 반환한다.
def _logback_spring_content() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<configuration>
    <springProperty scope="context" name="applicationName" source="spring.application.name" defaultValue="my-mental-care"/>
    <property name="LOG_PATH" value="${LOG_PATH:-logs}"/>
    <property name="LOG_PATTERN" value="%d{yyyy-MM-dd HH:mm:ss.SSS} %-5level [%thread] traceId=%X{traceId:-none} requestId=%X{requestId:-none} %logger{36} - %msg%n"/>

    <appender name="CONSOLE" class="ch.qos.logback.core.ConsoleAppender">
        <encoder>
            <charset>UTF-8</charset>
            <pattern>${LOG_PATTERN}</pattern>
        </encoder>
    </appender>

    <appender name="ROLLING_FILE" class="ch.qos.logback.core.rolling.RollingFileAppender">
        <file>${LOG_PATH}/mymentalcare-api.log</file>
        <encoder>
            <charset>UTF-8</charset>
            <pattern>${LOG_PATTERN}</pattern>
        </encoder>
        <rollingPolicy class="ch.qos.logback.core.rolling.SizeAndTimeBasedRollingPolicy">
            <fileNamePattern>${LOG_PATH}/mymentalcare-api.%d{yyyy-MM-dd}.%i.log.gz</fileNamePattern>
            <maxFileSize>20MB</maxFileSize>
            <maxHistory>14</maxHistory>
            <totalSizeCap>1GB</totalSizeCap>
        </rollingPolicy>
    </appender>

    <logger name="org.springframework.web" level="INFO"/>
    <logger name="org.hibernate.SQL" level="WARN"/>

    <root level="INFO">
        <appender-ref ref="CONSOLE"/>
        <appender-ref ref="ROLLING_FILE"/>
    </root>
</configuration>
"""


# 요청 ID를 MDC에 넣는 Kotlin 필터 코드를 반환한다.
def _request_id_logging_filter_content(package_name: str) -> str:
    return f"""package {package_name}.config

import jakarta.servlet.FilterChain
import jakarta.servlet.http.HttpServletRequest
import jakarta.servlet.http.HttpServletResponse
import org.slf4j.LoggerFactory
import org.slf4j.MDC
import org.springframework.stereotype.Component
import org.springframework.web.filter.OncePerRequestFilter
import java.util.UUID

private const val REQUEST_ID_HEADER = "X-Request-Id"
private const val TRACE_ID_MDC_KEY = "traceId"
private const val REQUEST_ID_MDC_KEY = "requestId"

@Component
class RequestIdLoggingFilter : OncePerRequestFilter() {{
    private val requestLogger = LoggerFactory.getLogger(javaClass)

    // 요청 단위 식별자를 로그 MDC와 응답 헤더에 남긴다.
    override fun doFilterInternal(
        request: HttpServletRequest,
        response: HttpServletResponse,
        filterChain: FilterChain,
    ) {{
        val requestId = request.getHeader(REQUEST_ID_HEADER)?.takeIf {{ it.isNotBlank() }} ?: UUID.randomUUID().toString()
        val startedAt = System.currentTimeMillis()

        MDC.put(TRACE_ID_MDC_KEY, requestId)
        MDC.put(REQUEST_ID_MDC_KEY, requestId)
        response.setHeader(REQUEST_ID_HEADER, requestId)

        try {{
            filterChain.doFilter(request, response)
        }} finally {{
            val elapsedMs = System.currentTimeMillis() - startedAt
            requestLogger.info(
                "[HTTP 요청] API 요청 처리 완료. who=anonymous, what={{}} {{}}, requestData=requestId:{{}}, reason=status:{{}},elapsedMs:{{}}",
                request.method,
                request.requestURI,
                requestId,
                response.status,
                elapsedMs,
            )
            MDC.remove(TRACE_ID_MDC_KEY)
            MDC.remove(REQUEST_ID_MDC_KEY)
        }}
    }}
}}
"""


# 요청 ID 필터의 한국어 테스트 코드를 반환한다.
def _request_id_logging_filter_test_content(package_name: str) -> str:
    return f"""package {package_name}.config

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Test
import org.springframework.mock.web.MockFilterChain
import org.springframework.mock.web.MockHttpServletRequest
import org.springframework.mock.web.MockHttpServletResponse

class RequestIdLoggingFilterTest {{

    @Test
    fun `요청 ID가 없으면 응답 헤더에 새 요청 ID를 남긴다`() {{
        val request = MockHttpServletRequest("GET", "/actuator/health")
        val response = MockHttpServletResponse()

        RequestIdLoggingFilter().doFilter(request, response, MockFilterChain())

        assertNotNull(response.getHeader("X-Request-Id"))
    }}

    @Test
    fun `요청 ID 헤더가 있으면 같은 값을 응답 헤더에 남긴다`() {{
        val request = MockHttpServletRequest("GET", "/actuator/health")
        request.addHeader("X-Request-Id", "request-123")
        val response = MockHttpServletResponse()

        RequestIdLoggingFilter().doFilter(request, response, MockFilterChain())

        assertEquals("request-123", response.getHeader("X-Request-Id"))
    }}
}}
"""


# 민감정보 로깅 정책 문서 내용을 반환한다.
def _logging_policy_content() -> str:
    return """# 백엔드 로그 출력 및 민감정보 로깅 정책

## 목적

myMentalCare API 서버의 장애 원인을 로컬에서 빠르게 확인할 수 있도록 파일 로그를 남긴다.
로그는 운영자와 개발자가 문제를 추적하기 위한 기록이며, 사용자의 민감한 대화나 인증 정보를 노출하지 않는다.

## 로그 파일

- 기본 위치: `logs/mymentalcare-api.log`
- 롤링 정책: 일 단위 + 20MB 단위 압축
- 보관 기간: 14일
- 총 보관 용량: 1GB

## 로그 식별자

모든 HTTP 요청은 `X-Request-Id`를 가진다.
요청자가 헤더를 보내지 않으면 서버가 새 ID를 만들고 응답 헤더에도 같은 값을 반환한다.

로그 패턴에는 다음 값이 포함된다.

- `traceId`
- `requestId`
- logger
- message

## 허용하는 로그 정보

- API path
- HTTP method
- HTTP status
- 처리 시간
- 회원 ID처럼 CS 확인에 필요한 식별자
- 실패 사유를 설명하는 안전한 코드성 메시지

## 금지하는 로그 정보

- 비밀번호 원문
- Access Token / Refresh Token 원문
- OpenAI API Key / Discord Webhook URL
- 사용자의 전체 채팅 원문
- 민감한 감정 기록 전문

## 실패 로그 작성 규칙

실패 로그는 가능하면 아래 key를 유지한다.

- `who`: 행위 주체
- `what`: 수행한 API 또는 메서드
- `requestData`: 요청 정보. 민감정보는 마스킹하거나 생략한다.
- `reason`: 실패 원인

예상 가능한 검증 실패는 `warn`, 시스템 장애나 추적이 필요한 예외는 `error`로 남긴다.
"""


def _write_security_dependency_files(context: DevRunnerContext) -> list[str]:
    paths: list[str] = []
    bootstrap_gradle = _bootstrap_module_root(context) / "build.gradle.kts"
    text = bootstrap_gradle.read_text(encoding="utf-8")
    anchor = '    implementation("org.springframework.boot:spring-boot-starter-actuator")'
    text = _ensure_lines_after_anchor(
        text,
        anchor,
        [
            '    implementation("org.springframework.boot:spring-boot-starter-security")',
            '    implementation("org.springframework.boot:spring-boot-starter-data-jpa")',
            '    implementation("org.springframework.boot:spring-boot-starter-data-redis")',
            '    implementation("io.jsonwebtoken:jjwt-api:0.11.5")',
            '    runtimeOnly("io.jsonwebtoken:jjwt-impl:0.11.5")',
            '    runtimeOnly("io.jsonwebtoken:jjwt-jackson:0.11.5")',
        ],
    )
    text = _ensure_lines_after_anchor(
        text,
        '    testImplementation("com.ninja-squad:springmockk:4.0.2")',
        ['    testImplementation("org.springframework.security:spring-security-test")'],
    )
    bootstrap_gradle.write_text(text, encoding="utf-8")
    paths.append(_relative(context, bootstrap_gradle))

    compose = context.repo_path / "apps/server/docker-compose.infra.local.yml"
    compose_text = compose.read_text(encoding="utf-8")
    if "redis:" not in compose_text:
        compose_text = compose_text.rstrip() + "\n  redis:\n    image: redis:7-alpine\n    ports:\n      - \"6380:6379\"\n    healthcheck:\n      test: [\"CMD\", \"redis-cli\", \"ping\"]\n      interval: 10s\n      timeout: 5s\n      retries: 10\n"
    compose.write_text(compose_text, encoding="utf-8")
    paths.append(_relative(context, compose))
    return paths


def _write_security_config_files(context: DevRunnerContext) -> list[str]:
    paths: list[str] = []
    module_root = _bootstrap_module_root(context)
    package_name = _bootstrap_package(context)
    env_prefix = _env_prefix(context)
    property_prefix = f"{module_root.name}.security.jwt"
    resources = module_root / "src/main/resources"
    application_yml = resources / "application.yml"
    yml = application_yml.read_text(encoding="utf-8")
    if "data:\n    redis:" not in yml:
        yml = _replace_once(
            yml,
            f"  application:\n    name: {_application_name(context)}\n",
            f"  application:\n    name: {_application_name(context)}\n  data:\n    redis:\n      host: ${{{env_prefix}_REDIS_HOST:localhost}}\n      port: ${{{env_prefix}_REDIS_PORT:6380}}\n",
        )
    if f"{module_root.name}:\n  security:" not in yml:
        yml = yml.rstrip() + f"\n\n{module_root.name}:\n  security:\n    jwt:\n      secret: ${{{env_prefix}_JWT_SECRET:local-{module_root.name}-jwt-secret-must-be-changed}}\n      access-token-expiration: ${{{env_prefix}_ACCESS_TOKEN_EXPIRATION:1h}}\n      refresh-token-expiration: ${{{env_prefix}_REFRESH_TOKEN_EXPIRATION:7d}}\n"
    application_yml.write_text(yml, encoding="utf-8")
    paths.append(_relative(context, application_yml))

    config_base = module_root / "src/main/kotlin" / Path(*package_name.split(".")) / "config"
    jwt_properties = config_base / "JwtProperties.kt"
    _write_text(jwt_properties, _jwt_properties_content(package_name, property_prefix))
    paths.append(_relative(context, jwt_properties))

    cors_config = config_base / "WebCorsConfiguration.kt"
    _write_text(cors_config, _web_cors_configuration_content(package_name))
    paths.append(_relative(context, cors_config))

    security_config = config_base / "SecurityConfiguration.kt"
    _write_text(security_config, _security_configuration_content(package_name))
    paths.append(_relative(context, security_config))

    return paths


def _write_security_test_files(context: DevRunnerContext) -> list[str]:
    module_root = _bootstrap_module_root(context)
    package_name = _bootstrap_package(context)
    test_base = module_root / "src/test/kotlin" / Path(*package_name.split(".")) / "config"
    test_file = test_base / "SecurityConfigurationTest.kt"
    _write_text(test_file, _security_configuration_test_content(package_name, module_root.name))
    return [_relative(context, test_file)]


def _jwt_properties_content(package_name: str, property_prefix: str) -> str:
    return f"""package {package_name}.config

import org.springframework.boot.context.properties.ConfigurationProperties
import java.time.Duration

@ConfigurationProperties(prefix = "{property_prefix}")
data class JwtProperties(
    val secret: String,
    val accessTokenExpiration: Duration,
    val refreshTokenExpiration: Duration,
)
"""


def _security_configuration_content(package_name: str) -> str:
    return """package __PACKAGE__.config

import org.springframework.boot.context.properties.EnableConfigurationProperties
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.http.HttpMethod
import org.springframework.security.config.annotation.web.builders.HttpSecurity
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity
import org.springframework.security.config.http.SessionCreationPolicy
import org.springframework.security.web.SecurityFilterChain

@Configuration
@EnableWebSecurity
@EnableConfigurationProperties(JwtProperties::class)
class SecurityConfiguration {
    @Bean
    fun securityFilterChain(http: HttpSecurity): SecurityFilterChain =
        http
            .csrf { it.disable() }
            .cors { }
            .sessionManagement { it.sessionCreationPolicy(SessionCreationPolicy.STATELESS) }
            .authorizeHttpRequests { requests ->
                requests
                    .requestMatchers(HttpMethod.OPTIONS, "/**").permitAll()
                    .requestMatchers(HttpMethod.POST, "/api/members/signup").permitAll()
                    .requestMatchers(HttpMethod.POST, "/api/auth/login").permitAll()
                    .requestMatchers(HttpMethod.POST, "/api/auth/reissue").permitAll()
                    .requestMatchers(
                        "/swagger-ui/**",
                        "/v3/api-docs/**",
                        "/actuator/health",
                        "/actuator/info",
                    ).permitAll()
                    .anyRequest().authenticated()
            }
            .build()
}
""".replace("__PACKAGE__", package_name)


def _web_cors_configuration_content(package_name: str) -> str:
    return """package __PACKAGE__.config

import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.web.servlet.config.annotation.CorsRegistry
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer

@Configuration
class WebCorsConfiguration {
    @Bean
    fun serviceWebCorsConfigurer(): WebMvcConfigurer =
        object : WebMvcConfigurer {
            override fun addCorsMappings(registry: CorsRegistry) {
                registry
                    .addMapping("/api/**")
                    .allowedOrigins("http://localhost:3000")
                    .allowedMethods("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
                    .allowedHeaders("*")
                    .allowCredentials(false)
                    .maxAge(3600)
            }
        }
}
""".replace("__PACKAGE__", package_name)


def _security_configuration_test_content(package_name: str, property_root: str) -> str:
    return """package __PACKAGE__.config

import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.context.properties.EnableConfigurationProperties
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest
import org.springframework.context.annotation.Import
import org.springframework.http.HttpMethod
import org.springframework.test.context.TestPropertySource
import org.springframework.test.web.servlet.MockMvc
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.options
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post
import org.springframework.test.web.servlet.result.MockMvcResultMatchers.header
import org.springframework.test.web.servlet.result.MockMvcResultMatchers.status
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RestController

@WebMvcTest(controllers = [SecurityTestController::class])
@Import(SecurityConfiguration::class, WebCorsConfiguration::class)
@EnableConfigurationProperties(JwtProperties::class)
@TestPropertySource(
    properties = [
        "__PROPERTY_ROOT__.security.jwt.secret=test-secret",
        "__PROPERTY_ROOT__.security.jwt.access-token-expiration=1h",
        "__PROPERTY_ROOT__.security.jwt.refresh-token-expiration=7d",
    ],
)
class SecurityConfigurationTest {
    @Autowired
    private lateinit var mockMvc: MockMvc

    @Test
    fun `회원가입 API는 인증 없이 접근할 수 있다`() {
        mockMvc.perform(post("/api/members/signup"))
            .andExpect(status().isOk)
    }

    @Test
    fun `보호 API는 인증 없이 접근하면 차단된다`() {
        mockMvc.perform(get("/api/protected-resource"))
            .andExpect(status().isForbidden)
    }

    @Test
    fun `로컬 웹 화면은 회원가입 CORS 사전 요청을 보낼 수 있다`() {
        mockMvc.perform(
            options("/api/members/signup")
                .header("Origin", "http://localhost:3000")
                .header("Access-Control-Request-Method", HttpMethod.POST.name())
                .header("Access-Control-Request-Headers", "content-type"),
        )
            .andExpect(status().isOk)
            .andExpect(header().string("Access-Control-Allow-Origin", "http://localhost:3000"))
    }
}

@RestController
class SecurityTestController {
    @PostMapping("/api/members/signup")
    fun signup() {
    }

    @GetMapping("/api/protected-resource")
    fun protectedResource() {
    }
}
""".replace("__PACKAGE__", package_name).replace("__PROPERTY_ROOT__", property_root)
