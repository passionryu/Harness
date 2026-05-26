import subprocess
from pathlib import Path

from agents.base import AgentStatus, ArtifactSpec
from agents.runners.base import DevRunnerContext, DevRunnerResult


class KotlinSpringRunner:
    name = "kotlin_spring_runner"

    def can_handle(self, context: DevRunnerContext) -> bool:
        return context.issue_type in {"beFeature", "apiConnect", "bugfix", "hotfix"} and (
            context.repo_path / "apps/server/build.gradle.kts"
        ).exists()

    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        if _is_member_signup_feature(context):
            return _implement_member_signup_api(context)

        report = context.task_dir / "kotlin-spring-runner.md"
        report.write_text(
            "\n".join(
                [
                    "# Kotlin Spring Runner",
                    "",
                    f"- runner: `{self.name}`",
                    f"- issue_type: `{context.issue_type}`",
                    f"- branch: `{context.branch_name}`",
                    "",
                    "## Status",
                    "",
                    "- Kotlin/Spring Boot Runner가 선택되었습니다.",
                    "- 아직 이 백엔드 기능은 범용 Runner가 자동 구현을 지원하지 않습니다.",
                    "- 가짜 성공을 보고하지 않고 중단했습니다.",
                ]
            ),
            encoding="utf-8",
        )
        return DevRunnerResult(
            status=AgentStatus.NEEDS_HUMAN,
            summary="Kotlin/Spring Boot Runner가 선택되었지만 아직 이 백엔드 계획은 자동 구현을 지원하지 않습니다.",
            progress=[
                "- [x] Kotlin/Spring Boot Runner 선택",
                "- [ ] 이 기능에 대한 계획 기반 백엔드 구현",
            ],
            verification=[
                "## kotlin_spring_runner",
                "",
                "- status: needs_human",
                "- reason: 아직 이 백엔드 기능은 범용 Runner가 자동 구현을 지원하지 않습니다.",
            ],
            artifacts=[ArtifactSpec("kotlin-spring-runner-report", report)],
            error="아직 이 백엔드 기능은 범용 Kotlin/Spring Runner가 자동 구현을 지원하지 않습니다.",
        )


def _is_member_signup_feature(context: DevRunnerContext) -> bool:
    haystack = f"{context.title}\n{context.body}".lower()
    return context.issue_type in {"beFeature", "apiConnect"} and (
        ("회원" in haystack and "가입" in haystack)
        or "signup" in haystack
        or "sign up" in haystack
    )


def _server_root(context: DevRunnerContext) -> Path:
    return context.repo_path / "apps/server"


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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


def _implement_member_signup_api(context: DevRunnerContext) -> DevRunnerResult:
    commits: list[str] = []
    progress: list[str] = []
    verification: list[str] = []
    server_root = _server_root(context)

    domain_paths = _write_member_domain_files(context)
    application_paths = _write_member_application_files(context)
    commit_hash = _stage_and_commit(
        context,
        domain_paths + application_paths,
        f"[{context.feature_name}] : 도메인과 application 흐름 추가",
    )
    commits.append(f"1. {commit_hash} [{context.feature_name}] : 도메인과 application 흐름 추가")
    progress.append("- [x] step 1: 도메인/UseCase 구현")

    persistence_paths = _write_member_persistence_files(context)
    bootstrap_paths = _write_member_bootstrap_files(context)
    commit_hash = _stage_and_commit(
        context,
        persistence_paths + bootstrap_paths,
        f"[{context.feature_name}] : controller, DTO, persistence 연결",
    )
    commits.append(f"2. {commit_hash} [{context.feature_name}] : controller, DTO, persistence 연결")
    progress.append("- [x] step 2: API/인프라 연결")

    test_paths = _write_member_test_files(context)
    commit_hash = _stage_and_commit(
        context,
        test_paths,
        f"[{context.feature_name}] : 단위/통합 테스트 코드 추가",
    )
    commits.append(f"3. {commit_hash} [{context.feature_name}] : 단위/통합 테스트 코드 추가")
    progress.append("- [x] step 3: 테스트 추가")

    exit_code, stdout, stderr = _run_command(
        ["./gradlew", "test"],
        server_root,
        context.timeout_seconds,
    )
    verification.extend(
        [
            "## ./gradlew test",
            "",
            f"- exit_code: {exit_code}",
            "",
            "### stdout",
            "```text",
            stdout.strip() or "(empty)",
            "```",
            "",
            "### stderr",
            "```text",
            stderr.strip() or "(empty)",
            "```",
        ]
    )
    progress.append("- [x] step 4: 검증 정리" if exit_code == 0 else "- [ ] step 4: 검증 정리")
    commits.append("4. no commit [검증 정리] : ./gradlew test 실행")

    report = context.task_dir / "kotlin-spring-runner.md"
    report.write_text(
        "\n".join(
            [
                "# Kotlin Spring Runner",
                "",
                f"- runner: `{KotlinSpringRunner.name}`",
                f"- branch: `{context.branch_name}`",
                "- feature: 회원가입 API",
                "- service_layer_skill: `/Users/rsy/.codex/skills/usecase-orchestration-style/SKILL.md`",
                "- backend_runner_rules: `rules/backend-runner.md`",
                "- localization_rules: `rules/localization.md`",
                "",
                "## Generated Scope",
                "",
                "- 회원 도메인 모델",
                "- 회원가입 application usecase와 port",
                "- JPA persistence adapter",
                "- REST 회원가입 endpoint",
                "- 단위 테스트",
                "",
                "## Verification",
                "",
                "- command: `./gradlew test`",
                f"- exit_code: `{exit_code}`",
            ]
        ),
        encoding="utf-8",
    )

    return DevRunnerResult(
        status=AgentStatus.SUCCESS if exit_code == 0 else AgentStatus.FAILED,
        summary=f"Kotlin/Spring 회원가입 API 구현이 {context.branch_name}에서 완료되었습니다.",
        commits=commits,
        progress=progress,
        verification=verification,
        artifacts=[ArtifactSpec("kotlin-spring-runner-report", report)],
        error=None if exit_code == 0 else "Kotlin/Spring 구현 후 Gradle 테스트가 실패했습니다.",
    )


def _write_member_domain_files(context: DevRunnerContext) -> list[str]:
    base = context.repo_path / "apps/server/modules/domain/src/main/kotlin/com/studyhub/server/domain/member"
    member_path = base / "Member.kt"
    _write_text(
        member_path,
        """package com.studyhub.server.domain.member

data class Member(
    val id: Long? = null,
    val name: String,
    val email: String,
    val encodedPassword: String,
    val phone: String?,
    val interests: List<String>,
)
""",
    )
    return [_relative(context, member_path)]


def _write_member_application_files(context: DevRunnerContext) -> list[str]:
    base = context.repo_path / "apps/server/modules/application/src/main/kotlin/com/studyhub/server/application/member"
    port_base = base / "port"
    paths = {
        base / "RegisterMemberCommand.kt": """package com.studyhub.server.application.member

data class RegisterMemberCommand(
    val name: String,
    val email: String,
    val password: String,
    val phone: String?,
    val interests: List<String>,
)
""",
        base / "RegisterMemberResult.kt": """package com.studyhub.server.application.member

data class RegisterMemberResult(
    val memberId: Long,
    val name: String,
    val email: String,
)
""",
        base / "DuplicateMemberEmailException.kt": """package com.studyhub.server.application.member

class DuplicateMemberEmailException(
    val email: String,
) : RuntimeException("이미 가입된 이메일입니다.")
""",
        port_base / "MemberRepository.kt": """package com.studyhub.server.application.member.port

import com.studyhub.server.domain.member.Member

interface MemberRepository {
    fun existsByEmail(email: String): Boolean

    fun save(member: Member): Member
}
""",
        port_base / "MemberPasswordHasher.kt": """package com.studyhub.server.application.member.port

interface MemberPasswordHasher {
    fun hashMemberPassword(rawPassword: String): String
}
""",
        base / "MemberEmailDuplicateChecker.kt": """package com.studyhub.server.application.member

import com.studyhub.server.application.member.port.MemberRepository
import org.springframework.stereotype.Component

@Component
class MemberEmailDuplicateChecker(
    private val memberRepository: MemberRepository,
) {
    // 이미 가입된 이메일로는 새 회원을 등록할 수 없으므로 중복 여부를 검증한다.
    fun validateEmailCanBeUsed(email: String) {
        if (memberRepository.existsByEmail(email.trim().lowercase())) {
            throw DuplicateMemberEmailException(email)
        }
    }
}
""",
        base / "MemberRegistrationFactory.kt": """package com.studyhub.server.application.member

import com.studyhub.server.domain.member.Member
import org.springframework.stereotype.Component

@Component
class MemberRegistrationFactory {
    // 회원 가입 입력값을 정규화한 뒤 신규 회원 도메인 객체를 생성한다.
    fun createRegisteringMember(
        name: String,
        email: String,
        encodedPassword: String,
        phone: String?,
        interests: List<String>,
    ): Member {
        require(name.isNotBlank()) { "회원 이름은 비어 있을 수 없습니다." }
        require(email.isNotBlank()) { "회원 이메일은 비어 있을 수 없습니다." }
        require(encodedPassword.isNotBlank()) { "회원 비밀번호 해시값은 비어 있을 수 없습니다." }

        return Member(
            name = name.trim(),
            email = email.trim().lowercase(),
            encodedPassword = encodedPassword,
            phone = phone?.trim()?.takeIf { it.isNotBlank() },
            interests = interests.map { it.trim() }.filter { it.isNotBlank() }.distinct(),
        )
    }
}
""",
        base / "RegisterMemberResultMapper.kt": """package com.studyhub.server.application.member

import com.studyhub.server.domain.member.Member
import org.springframework.stereotype.Component

@Component
class RegisterMemberResultMapper {
    // 등록된 회원 도메인 객체를 application 결과 모델로 변환한다.
    fun mapRegisteredMember(member: Member): RegisterMemberResult =
        RegisterMemberResult(
            memberId = requireNotNull(member.id),
            name = member.name,
            email = member.email,
        )
}
""",
        base / "Sha256MemberPasswordHasher.kt": """package com.studyhub.server.application.member

import com.studyhub.server.application.member.port.MemberPasswordHasher
import org.springframework.stereotype.Component
import java.security.MessageDigest
import java.util.Base64

@Component
class Sha256MemberPasswordHasher : MemberPasswordHasher {
    // 평문 비밀번호를 그대로 저장하지 않기 위해 해시 문자열로 변환한다.
    override fun hashMemberPassword(rawPassword: String): String {
        require(rawPassword.length >= 8) { "비밀번호는 8자 이상이어야 합니다." }

        val digest = MessageDigest.getInstance("SHA-256")
            .digest(rawPassword.toByteArray(Charsets.UTF_8))

        return Base64.getEncoder().encodeToString(digest)
    }
}
""",
        base / "RegisterMemberService.kt": """package com.studyhub.server.application.member

import com.studyhub.server.application.member.port.MemberPasswordHasher
import com.studyhub.server.application.member.port.MemberRepository
import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional

@Service
class RegisterMemberService(
    private val memberEmailDuplicateChecker: MemberEmailDuplicateChecker,
    private val memberRegistrationFactory: MemberRegistrationFactory,
    private val memberPasswordHasher: MemberPasswordHasher,
    private val memberRepository: MemberRepository,
    private val registerMemberResultMapper: RegisterMemberResultMapper,
) {
    @Transactional
    fun registerMember(command: RegisterMemberCommand): RegisterMemberResult {
        memberEmailDuplicateChecker.validateEmailCanBeUsed(command.email)

        val encodedPassword = memberPasswordHasher.hashMemberPassword(command.password)

        val member = memberRegistrationFactory.createRegisteringMember(
            name = command.name,
            email = command.email,
            encodedPassword = encodedPassword,
            phone = command.phone,
            interests = command.interests,
        )

        val registeredMember = memberRepository.save(member)

        return registerMemberResultMapper.mapRegisteredMember(registeredMember)
    }
}
""",
    }
    for path, content in paths.items():
        _write_text(path, content)
    return [_relative(context, path) for path in paths]


def _write_member_persistence_files(context: DevRunnerContext) -> list[str]:
    base = context.repo_path / (
        "apps/server/modules/infrastructure/persistence/src/main/kotlin/"
        "com/studyhub/server/infrastructure/persistence/member"
    )
    paths = {
        base / "MemberJpaEntity.kt": """package com.studyhub.server.infrastructure.persistence.member

import com.studyhub.server.domain.member.Member
import jakarta.persistence.CollectionTable
import jakarta.persistence.Column
import jakarta.persistence.ElementCollection
import jakarta.persistence.Entity
import jakarta.persistence.FetchType
import jakarta.persistence.GeneratedValue
import jakarta.persistence.GenerationType
import jakarta.persistence.Id
import jakarta.persistence.JoinColumn
import jakarta.persistence.Table
import jakarta.persistence.UniqueConstraint

@Entity
@Table(
    name = "members",
    uniqueConstraints = [
        UniqueConstraint(name = "uk_members_email", columnNames = ["email"]),
    ],
)
class MemberJpaEntity(
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    val id: Long? = null,

    @Column(nullable = false)
    val name: String,

    @Column(nullable = false)
    val email: String,

    @Column(nullable = false)
    val encodedPassword: String,

    @Column
    val phone: String?,

    @ElementCollection(fetch = FetchType.EAGER)
    @CollectionTable(
        name = "member_interests",
        joinColumns = [JoinColumn(name = "member_id")],
    )
    @Column(name = "interest", nullable = false)
    val interests: MutableList<String> = mutableListOf(),
) {
    fun toDomain(): Member =
        Member(
            id = id,
            name = name,
            email = email,
            encodedPassword = encodedPassword,
            phone = phone,
            interests = interests.toList(),
        )
}
""",
        base / "MemberJpaRepository.kt": """package com.studyhub.server.infrastructure.persistence.member

import org.springframework.data.jpa.repository.JpaRepository

interface MemberJpaRepository : JpaRepository<MemberJpaEntity, Long> {
    fun existsByEmail(email: String): Boolean
}
""",
        base / "MemberRepositoryAdapter.kt": """package com.studyhub.server.infrastructure.persistence.member

import com.studyhub.server.application.member.port.MemberRepository
import com.studyhub.server.domain.member.Member
import org.springframework.stereotype.Repository

@Repository
class MemberRepositoryAdapter(
    private val memberJpaRepository: MemberJpaRepository,
) : MemberRepository {
    override fun existsByEmail(email: String): Boolean =
        memberJpaRepository.existsByEmail(email)

    override fun save(member: Member): Member =
        memberJpaRepository.save(member.toJpaEntity()).toDomain()

    private fun Member.toJpaEntity(): MemberJpaEntity =
        MemberJpaEntity(
            id = id,
            name = name,
            email = email,
            encodedPassword = encodedPassword,
            phone = phone,
            interests = interests.toMutableList(),
        )
}
""",
    }
    for path, content in paths.items():
        _write_text(path, content)
    return [_relative(context, path) for path in paths]


def _write_member_bootstrap_files(context: DevRunnerContext) -> list[str]:
    base = context.repo_path / (
        "apps/server/modules/bootstrap/studyhub/src/main/kotlin/"
        "com/studyhub/server/bootstrap/presentation/member"
    )
    resources_base = context.repo_path / "apps/server/modules/bootstrap/studyhub/src/main/resources"
    build_gradle = context.repo_path / "apps/server/modules/bootstrap/studyhub/build.gradle.kts"
    paths = {
        base / "MemberSignupController.kt": """package com.studyhub.server.bootstrap.presentation.member

import com.studyhub.server.application.member.RegisterMemberService
import jakarta.validation.Valid
import org.springframework.http.HttpStatus
import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/members")
class MemberSignupController(
    private val registerMemberService: RegisterMemberService,
) {
    @PostMapping("/signup")
    fun signUp(
        @Valid @RequestBody request: MemberSignupRequest,
    ): ResponseEntity<MemberSignupResponse> {
        val result = registerMemberService.registerMember(request.toCommand())

        return ResponseEntity
            .status(HttpStatus.CREATED)
            .body(
                MemberSignupResponse(
                    memberId = result.memberId,
                    name = result.name,
                    email = result.email,
                ),
            )
    }
}
""",
        base / "MemberSignupRequest.kt": """package com.studyhub.server.bootstrap.presentation.member

import com.studyhub.server.application.member.RegisterMemberCommand
import jakarta.validation.constraints.Email
import jakarta.validation.constraints.NotBlank
import jakarta.validation.constraints.Size

data class MemberSignupRequest(
    @field:NotBlank
    val name: String,

    @field:Email
    @field:NotBlank
    val email: String,

    @field:Size(min = 8)
    val password: String,

    val phone: String? = null,

    val interests: List<String> = emptyList(),
) {
    fun toCommand(): RegisterMemberCommand =
        RegisterMemberCommand(
            name = name,
            email = email,
            password = password,
            phone = phone,
            interests = interests,
        )
}
""",
        base / "MemberSignupResponse.kt": """package com.studyhub.server.bootstrap.presentation.member

data class MemberSignupResponse(
    val memberId: Long,
    val name: String,
    val email: String,
)
""",
        base / "ApiExceptionHandler.kt": """package com.studyhub.server.bootstrap.presentation.member

import com.studyhub.server.application.member.DuplicateMemberEmailException
import org.slf4j.LoggerFactory
import org.springframework.http.HttpStatus
import org.springframework.http.ResponseEntity
import org.springframework.web.bind.MethodArgumentNotValidException
import org.springframework.web.bind.annotation.ExceptionHandler
import org.springframework.web.bind.annotation.RestControllerAdvice

@RestControllerAdvice
class ApiExceptionHandler {
    private val logger = LoggerFactory.getLogger(javaClass)

    @ExceptionHandler(DuplicateMemberEmailException::class)
    fun handleDuplicateMemberEmail(exception: DuplicateMemberEmailException): ResponseEntity<ApiErrorResponse> {
        logger.warn(
            "[회원 가입] 회원 가입 이메일 중복 검증 실패. " +
                "who=email:${exception.email.toMaskedEmail()}, " +
                "what=POST /api/members/signup, " +
                "requestData=email:${exception.email.toMaskedEmail()}, " +
                "reason=message:${exception.message}"
        )

        return ResponseEntity.status(HttpStatus.CONFLICT)
            .body(ApiErrorResponse(message = "이미 가입된 이메일입니다. 다른 이메일로 가입해주세요."))
    }

    @ExceptionHandler(MethodArgumentNotValidException::class)
    fun handleInvalidRequest(exception: MethodArgumentNotValidException): ResponseEntity<ApiErrorResponse> {
        logger.warn(
            "[회원 가입] 회원 가입 요청 값 검증 실패. " +
                "who=anonymous, " +
                "what=POST /api/members/signup, " +
                "requestData=validationFields:${exception.bindingResult.fieldErrors.map { it.field }.distinct()}, " +
                "reason=message:요청 값 검증 실패"
        )

        return ResponseEntity.badRequest()
            .body(ApiErrorResponse(message = "입력한 회원가입 정보를 다시 확인해주세요."))
    }

    @ExceptionHandler(IllegalArgumentException::class)
    fun handleIllegalArgument(exception: IllegalArgumentException): ResponseEntity<ApiErrorResponse> {
        logger.warn(
            "[회원 가입] 회원 가입 정책 검증 실패. " +
                "who=anonymous, " +
                "what=POST /api/members/signup, " +
                "requestData=omitted, " +
                "reason=message:${exception.message}"
        )

        return ResponseEntity.badRequest()
            .body(ApiErrorResponse(message = "입력한 회원가입 정보를 다시 확인해주세요."))
    }

    private fun String.toMaskedEmail(): String {
        val parts = split("@", limit = 2)
        if (parts.size != 2) {
            return "***"
        }
        val local = parts[0]
        val domain = parts[1]
        val visible = local.take(2)
        return "$visible***@$domain"
    }
}
""",
        base / "ApiErrorResponse.kt": """package com.studyhub.server.bootstrap.presentation.member

data class ApiErrorResponse(
    val message: String,
)
""",
        resources_base / "db/migration/V1__create_member_tables.sql": """CREATE TABLE members (
    id BIGINT NOT NULL AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL,
    encoded_password VARCHAR(255) NOT NULL,
    phone VARCHAR(30) NULL,
    PRIMARY KEY (id),
    CONSTRAINT uk_members_email UNIQUE (email)
);

CREATE TABLE member_interests (
    member_id BIGINT NOT NULL,
    interest VARCHAR(100) NOT NULL,
    CONSTRAINT fk_member_interests_member_id FOREIGN KEY (member_id) REFERENCES members (id)
);
""",
    }
    for path, content in paths.items():
        _write_text(path, content)
    _ensure_flyway_dependencies(build_gradle)
    return [_relative(context, path) for path in paths] + [_relative(context, build_gradle)]


def _ensure_flyway_dependencies(build_gradle: Path) -> None:
    content = build_gradle.read_text(encoding="utf-8")
    if "org.flywaydb:flyway-core" in content:
        return

    marker = '    implementation("org.springdoc:springdoc-openapi-starter-webmvc-ui:2.8.6")'
    replacement = "\n".join(
        [
            marker,
            '    implementation("org.flywaydb:flyway-core")',
            '    implementation("org.flywaydb:flyway-mysql")',
        ]
    )
    build_gradle.write_text(content.replace(marker, replacement), encoding="utf-8")


def _write_member_test_files(context: DevRunnerContext) -> list[str]:
    paths = {
        context.repo_path / (
            "apps/server/modules/domain/src/test/kotlin/com/studyhub/server/domain/member/MemberTest.kt"
        ): """package com.studyhub.server.domain.member

import kotlin.test.Test
import kotlin.test.assertEquals

class MemberTest {
    @Test
    fun `register member normalizes email and interests`() {
        val member = Member(
            name = "Ryu",
            email = "ryu@example.com",
            encodedPassword = "encoded",
            phone = null,
            interests = listOf("Kotlin", "Spring"),
        )

        assertEquals("ryu@example.com", member.email)
        assertEquals(listOf("Kotlin", "Spring"), member.interests)
    }
}
""",
        context.repo_path / (
            "apps/server/modules/application/src/test/kotlin/"
            "com/studyhub/server/application/member/RegisterMemberServiceTest.kt"
        ): """package com.studyhub.server.application.member

import com.studyhub.server.application.member.port.MemberPasswordHasher
import com.studyhub.server.application.member.port.MemberRepository
import com.studyhub.server.domain.member.Member
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class RegisterMemberServiceTest {
    @Test
    fun `register member stores encoded password`() {
        val repository = FakeMemberRepository()
        val service = RegisterMemberService(
            memberEmailDuplicateChecker = MemberEmailDuplicateChecker(repository),
            memberRegistrationFactory = MemberRegistrationFactory(),
            memberPasswordHasher = FixedPasswordHasher(),
            memberRepository = repository,
            registerMemberResultMapper = RegisterMemberResultMapper(),
        )

        val result = service.registerMember(
            RegisterMemberCommand(
                name = "Ryu",
                email = "ryu@example.com",
                password = "password123",
                phone = null,
                interests = listOf("Kotlin"),
            ),
        )

        assertEquals(1L, result.memberId)
        assertEquals("encoded-password", repository.savedMember?.encodedPassword)
    }

    @Test
    fun `register member rejects duplicated email`() {
        val repository = FakeMemberRepository(existingEmails = setOf("ryu@example.com"))
        val service = RegisterMemberService(
            memberEmailDuplicateChecker = MemberEmailDuplicateChecker(repository),
            memberRegistrationFactory = MemberRegistrationFactory(),
            memberPasswordHasher = FixedPasswordHasher(),
            memberRepository = repository,
            registerMemberResultMapper = RegisterMemberResultMapper(),
        )

        assertFailsWith<DuplicateMemberEmailException> {
            service.registerMember(
                RegisterMemberCommand(
                    name = "Ryu",
                    email = "ryu@example.com",
                    password = "password123",
                    phone = null,
                    interests = emptyList(),
                ),
            )
        }
    }
}

private class FixedPasswordHasher : MemberPasswordHasher {
    override fun hashMemberPassword(rawPassword: String): String = "encoded-password"
}

private class FakeMemberRepository(
    private val existingEmails: Set<String> = emptySet(),
) : MemberRepository {
    var savedMember: Member? = null

    override fun existsByEmail(email: String): Boolean = existingEmails.contains(email)

    override fun save(member: Member): Member {
        val saved = member.copy(id = 1L)
        savedMember = saved
        return saved
    }
}
""",
    }
    for path, content in paths.items():
        _write_text(path, content)
    return [_relative(context, path) for path in paths]


def _relative(context: DevRunnerContext, path: Path) -> str:
    return str(path.relative_to(context.repo_path))
