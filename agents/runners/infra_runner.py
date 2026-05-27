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


def _server_root(context: DevRunnerContext) -> Path:
    return context.repo_path / "apps/server"


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

    exit_code, stdout, stderr = _run_command(
        ["./gradlew", ":modules:bootstrap:studyhub:test", "--tests", "*SecurityConfigurationTest"],
        _server_root(context),
        context.timeout_seconds,
    )
    verification.extend(
        [
            "## :modules:bootstrap:studyhub:test --tests *SecurityConfigurationTest",
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
                "- command: `./gradlew :modules:bootstrap:studyhub:test --tests '*SecurityConfigurationTest'`",
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


def _write_security_dependency_files(context: DevRunnerContext) -> list[str]:
    paths: list[str] = []
    bootstrap_gradle = context.repo_path / "apps/server/modules/bootstrap/studyhub/build.gradle.kts"
    text = bootstrap_gradle.read_text(encoding="utf-8")
    anchor = '    implementation("org.springframework.boot:spring-boot-starter-actuator")'
    text = _ensure_lines_after_anchor(
        text,
        anchor,
        [
            '    implementation("org.springframework.boot:spring-boot-starter-security")',
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
        compose_text = compose_text.rstrip() + "\n  redis:\n    image: redis:7-alpine\n    ports:\n      - \"6379:6379\"\n    healthcheck:\n      test: [\"CMD\", \"redis-cli\", \"ping\"]\n      interval: 10s\n      timeout: 5s\n      retries: 10\n"
    compose.write_text(compose_text, encoding="utf-8")
    paths.append(_relative(context, compose))
    return paths


def _write_security_config_files(context: DevRunnerContext) -> list[str]:
    paths: list[str] = []
    resources = context.repo_path / "apps/server/modules/bootstrap/studyhub/src/main/resources"
    application_yml = resources / "application.yml"
    yml = application_yml.read_text(encoding="utf-8")
    if "data:\n    redis:" not in yml:
        yml = _replace_once(
            yml,
            "  application:\n    name: studyhub-server\n",
            "  application:\n    name: studyhub-server\n  data:\n    redis:\n      host: ${STUDYHUB_REDIS_HOST:localhost}\n      port: ${STUDYHUB_REDIS_PORT:6379}\n",
        )
    if "studyhub:\n  security:" not in yml:
        yml = yml.rstrip() + "\n\nstudyhub:\n  security:\n    jwt:\n      secret: ${STUDYHUB_JWT_SECRET:local-studyhub-jwt-secret-must-be-changed}\n      access-token-expiration: ${STUDYHUB_ACCESS_TOKEN_EXPIRATION:1h}\n      refresh-token-expiration: ${STUDYHUB_REFRESH_TOKEN_EXPIRATION:7d}\n"
    application_yml.write_text(yml, encoding="utf-8")
    paths.append(_relative(context, application_yml))

    config_base = context.repo_path / "apps/server/modules/bootstrap/studyhub/src/main/kotlin/com/studyhub/server/bootstrap/config"
    jwt_properties = config_base / "JwtProperties.kt"
    _write_text(jwt_properties, _jwt_properties_content())
    paths.append(_relative(context, jwt_properties))

    cors_config = config_base / "WebCorsConfiguration.kt"
    _write_text(cors_config, _web_cors_configuration_content())
    paths.append(_relative(context, cors_config))

    security_config = config_base / "SecurityConfiguration.kt"
    _write_text(security_config, _security_configuration_content())
    paths.append(_relative(context, security_config))

    return paths


def _write_security_test_files(context: DevRunnerContext) -> list[str]:
    test_base = context.repo_path / "apps/server/modules/bootstrap/studyhub/src/test/kotlin/com/studyhub/server/bootstrap/config"
    test_file = test_base / "SecurityConfigurationTest.kt"
    _write_text(test_file, _security_configuration_test_content())
    return [_relative(context, test_file)]


def _jwt_properties_content() -> str:
    return """package com.studyhub.server.bootstrap.config

import org.springframework.boot.context.properties.ConfigurationProperties
import java.time.Duration

@ConfigurationProperties(prefix = "studyhub.security.jwt")
data class JwtProperties(
    val secret: String,
    val accessTokenExpiration: Duration,
    val refreshTokenExpiration: Duration,
)
"""


def _security_configuration_content() -> str:
    return """package com.studyhub.server.bootstrap.config

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
"""


def _web_cors_configuration_content() -> str:
    return """package com.studyhub.server.bootstrap.config

import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.web.servlet.config.annotation.CorsRegistry
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer

@Configuration
class WebCorsConfiguration {
    @Bean
    fun studyHubWebCorsConfigurer(): WebMvcConfigurer =
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
"""


def _security_configuration_test_content() -> str:
    return """package com.studyhub.server.bootstrap.config

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
        "studyhub.security.jwt.secret=test-secret",
        "studyhub.security.jwt.access-token-expiration=1h",
        "studyhub.security.jwt.refresh-token-expiration=7d",
    ],
)
class SecurityConfigurationTest {
    @Autowired
    private lateinit var mockMvc: MockMvc

    @Test
    fun `signup endpoint is permitted without authentication`() {
        mockMvc.perform(post("/api/members/signup"))
            .andExpect(status().isOk)
    }

    @Test
    fun `protected api requires authentication`() {
        mockMvc.perform(get("/api/protected-resource"))
            .andExpect(status().isUnauthorized)
    }

    @Test
    fun `localhost web origin can send cors preflight request`() {
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
"""
