from agents.base import AgentStatus
from agents.runners.base import DevRunnerContext, DevRunnerResult


class NextJsRunner:
    name = "nextjs_runner"

    def can_handle(self, context: DevRunnerContext) -> bool:
        return context.issue_type in {"feFeature", "apiConnect"} and (
            context.repo_path / "apps/web/package.json"
        ).exists()

    def run(self, context: DevRunnerContext) -> DevRunnerResult:
        from agents.dev_agent import _implement_signup_feature, _is_signup_feature

        if context.issue_type == "apiConnect" and _is_signup_api_connect(context):
            return _implement_signup_api_connect(context)

        if not _is_signup_feature(context.issue_type, context.title, context.body):
            return DevRunnerResult(
                status=AgentStatus.NEEDS_HUMAN,
                summary="Next.js Runner가 선택되었지만 아직 이 프론트엔드/API 연동 계획은 자동 구현을 지원하지 않습니다.",
                progress=[
                    "- [x] Next.js Runner 선택",
                    "- [ ] 계획 기반 범용 프론트엔드/API 연동 구현",
                ],
                verification=[
                    "## nextjs_runner",
                    "",
                    "- status: needs_human",
                    "- reason: 현재는 회원가입 화면 생성과 회원가입 API 연동 자동화만 지원합니다.",
                ],
                error="현재는 회원가입 화면 생성과 회원가입 API 연동 자동화만 지원합니다.",
            )

        commits, progress, verification = _implement_signup_feature(
            repo=context.repo,
            repo_path=context.repo_path,
            feature_name=context.feature_name,
            timeout_seconds=context.timeout_seconds,
        )
        return DevRunnerResult(
            status=AgentStatus.SUCCESS,
            summary=(
                f"{self.name}가 {context.branch_name}에서 구현을 완료했습니다. "
                f"커밋 기록 {len(commits)}개가 생성되었습니다."
            ),
            commits=commits,
            progress=progress,
            verification=verification,
        )


def _is_signup_api_connect(context: DevRunnerContext) -> bool:
    haystack = f"{context.title}\n{context.body}".lower()
    return ("회원" in haystack and "가입" in haystack) or "signup" in haystack or "sign up" in haystack


def _write_text(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _stage_and_commit(context: DevRunnerContext, paths: list[str], message: str) -> str:
    existing_paths = [path for path in paths if (context.repo_path / path).exists()]
    context.repo.index.add(existing_paths)
    if not context.repo.index.diff("HEAD"):
        return "스킵: 스테이징된 변경사항 없음"
    commit = context.repo.index.commit(message)
    return commit.hexsha[:12]


def _run_command(command: list[str], context: DevRunnerContext) -> tuple[int, str, str]:
    from agents.dev_agent import _run_command as run_command

    return run_command(command, context.repo_path, context.timeout_seconds)


def _update_package_script(package_json) -> None:
    import json

    data = json.loads(package_json.read_text(encoding="utf-8"))
    scripts = data.setdefault("scripts", {})
    scripts["test:signup-api-connect"] = "node scripts/verify-signup-api-connect.mjs"
    package_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _implement_signup_api_connect(context: DevRunnerContext) -> DevRunnerResult:
    commits: list[str] = []
    progress: list[str] = []
    verification: list[str] = []

    _write_text(context.repo_path / "apps/web/lib/signup-api.ts", _signup_api_content())
    commit_hash = _stage_and_commit(
        context,
        ["apps/web/lib/signup-api.ts"],
        f"[{context.feature_name}] : 회원가입 API client 추가",
    )
    commits.append(f"1. {commit_hash} [{context.feature_name}] : 회원가입 API client 추가")
    progress.append("- [x] step 1: API client 추가")

    _write_text(context.repo_path / "apps/web/lib/signup-validation.ts", _signup_validation_content())
    _write_text(context.repo_path / "apps/web/components/signup/signup-form.tsx", _signup_form_content())
    commit_hash = _stage_and_commit(
        context,
        [
            "apps/web/lib/signup-validation.ts",
            "apps/web/components/signup/signup-form.tsx",
        ],
        f"[{context.feature_name}] : 회원가입 폼 submit API 연동",
    )
    commits.append(f"2. {commit_hash} [{context.feature_name}] : 회원가입 폼 submit API 연동")
    progress.append("- [x] step 2: submit API 연동")

    _write_text(context.repo_path / "apps/web/scripts/verify-signup-api-connect.mjs", _signup_api_connect_test_content())
    _update_package_script(context.repo_path / "apps/web/package.json")
    commit_hash = _stage_and_commit(
        context,
        [
            "apps/web/scripts/verify-signup-api-connect.mjs",
            "apps/web/package.json",
        ],
        f"[{context.feature_name}] : API 연동 smoke test 추가",
    )
    commits.append(f"3. {commit_hash} [{context.feature_name}] : API 연동 smoke test 추가")
    progress.append("- [x] step 3: API 연동 테스트 추가")

    exit_code, stdout, stderr = _run_command(["pnpm", "--dir", "apps/web", "test:signup-api-connect"], context)
    verification.extend(
        [
            "## test:signup-api-connect",
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
    commits.append("4. no commit [검증 정리] : test:signup-api-connect 실행")

    return DevRunnerResult(
        status=AgentStatus.SUCCESS if exit_code == 0 else AgentStatus.FAILED,
        summary=f"회원가입 API 연동이 {context.branch_name}에서 완료되었습니다.",
        commits=commits,
        progress=progress,
        verification=verification,
        error=None if exit_code == 0 else "회원가입 API 연동 smoke test가 실패했습니다.",
    )


def _signup_api_content() -> str:
    return '''import type { SignupFormValues } from "@/lib/signup-validation"

export interface SignupMemberRequest {
  name: string
  email: string
  password: string
  phone: string | null
  interests: string[]
}

export interface SignupMemberResponse {
  memberId: number
  name: string
  email: string
}

export class SignupApiError extends Error {
  constructor(message: string) {
    super(message)
    this.name = "SignupApiError"
  }
}

const apiBaseUrl = process.env.NEXT_PUBLIC_STUDYHUB_API_BASE_URL ?? "http://localhost:8080"

export function toSignupMemberRequest(values: SignupFormValues): SignupMemberRequest {
  return {
    name: values.name.trim(),
    email: values.email.trim(),
    password: values.password,
    phone: values.phone.trim() || null,
    interests: values.interests
      .split(",")
      .map((interest) => interest.trim())
      .filter(Boolean),
  }
}

export async function signupMember(values: SignupFormValues): Promise<SignupMemberResponse> {
  const response = await fetch(`${apiBaseUrl}/api/members/signup`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(toSignupMemberRequest(values)),
  })

  const data = await response.json().catch(() => null)

  if (!response.ok) {
    throw new SignupApiError(data?.message ?? "회원가입 처리 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.")
  }

  return data as SignupMemberResponse
}
'''


def _signup_validation_content() -> str:
    return '''export interface SignupFormValues {
  name: string
  email: string
  password: string
  confirmPassword: string
  phone: string
  interests: string
}

export interface SignupValidationResult {
  isValid: boolean
  errors: Partial<Record<keyof SignupFormValues, string>>
}

const emailPattern = /^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/

export function validateSignup(values: SignupFormValues): SignupValidationResult {
  const errors: SignupValidationResult["errors"] = {}

  if (!values.name.trim()) {
    errors.name = "이름을 입력해주세요."
  }

  if (!emailPattern.test(values.email.trim())) {
    errors.email = "올바른 이메일 주소를 입력해주세요."
  }

  if (values.password.length < 8) {
    errors.password = "비밀번호는 8자 이상이어야 합니다."
  }

  if (values.password !== values.confirmPassword) {
    errors.confirmPassword = "비밀번호가 서로 일치하지 않습니다."
  }

  return {
    isValid: Object.keys(errors).length === 0,
    errors,
  }
}
'''


def _signup_form_content() -> str:
    return '''"use client"

import { FormEvent, useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { signupMember, SignupApiError } from "@/lib/signup-api"
import { validateSignup, type SignupFormValues } from "@/lib/signup-validation"

const initialValues: SignupFormValues = {
  name: "",
  email: "",
  password: "",
  confirmPassword: "",
  phone: "",
  interests: "",
}

export function SignupForm() {
  const [values, setValues] = useState<SignupFormValues>(initialValues)
  const [submitted, setSubmitted] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitMessage, setSubmitMessage] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const validation = useMemo(() => validateSignup(values), [values])

  const updateField = (field: keyof SignupFormValues, value: string) => {
    setValues((current) => ({ ...current, [field]: value }))
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitted(true)
    setSubmitMessage(null)
    setSubmitError(null)

    if (!validation.isValid) {
      return
    }

    setIsSubmitting(true)
    try {
      const member = await signupMember(values)
      setSubmitMessage(`${member.name}님, StudyHub 회원가입이 완료되었습니다.`)
      setValues(initialValues)
      setSubmitted(false)
    } catch (error) {
      if (error instanceof SignupApiError) {
        setSubmitError(error.message)
        return
      }
      setSubmitError("회원가입 처리 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.")
    } finally {
      setIsSubmitting(false)
    }
  }

  const errorFor = (field: keyof SignupFormValues) => submitted ? validation.errors[field] : undefined

  return (
    <form onSubmit={handleSubmit} className="grid gap-5 rounded-lg border border-border bg-card p-6 shadow-sm">
      <div className="grid gap-2">
        <Label htmlFor="name">이름</Label>
        <Input id="name" value={values.name} onChange={(event) => updateField("name", event.target.value)} />
        {errorFor("name") && <p className="text-sm text-destructive">{errorFor("name")}</p>}
      </div>

      <div className="grid gap-2">
        <Label htmlFor="email">이메일</Label>
        <Input id="email" type="email" value={values.email} onChange={(event) => updateField("email", event.target.value)} />
        {errorFor("email") && <p className="text-sm text-destructive">{errorFor("email")}</p>}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="grid gap-2">
          <Label htmlFor="password">비밀번호</Label>
          <Input id="password" type="password" value={values.password} onChange={(event) => updateField("password", event.target.value)} />
          {errorFor("password") && <p className="text-sm text-destructive">{errorFor("password")}</p>}
        </div>

        <div className="grid gap-2">
          <Label htmlFor="confirmPassword">비밀번호 확인</Label>
          <Input id="confirmPassword" type="password" value={values.confirmPassword} onChange={(event) => updateField("confirmPassword", event.target.value)} />
          {errorFor("confirmPassword") && <p className="text-sm text-destructive">{errorFor("confirmPassword")}</p>}
        </div>
      </div>

      <div className="grid gap-2">
        <Label htmlFor="phone">전화번호</Label>
        <Input id="phone" value={values.phone} onChange={(event) => updateField("phone", event.target.value)} />
        {errorFor("phone") && <p className="text-sm text-destructive">{errorFor("phone")}</p>}
      </div>

      <div className="grid gap-2">
        <Label htmlFor="interests">관심 영역</Label>
        <Textarea
          id="interests"
          value={values.interests}
          onChange={(event) => updateField("interests", event.target.value)}
          placeholder="알고리즘, Spring Boot, 시스템 설계"
        />
        {errorFor("interests") && <p className="text-sm text-destructive">{errorFor("interests")}</p>}
      </div>

      {submitMessage && <p className="text-sm text-emerald-600">{submitMessage}</p>}
      {submitError && <p className="text-sm text-destructive">{submitError}</p>}

      <Button type="submit" className="w-full sm:w-fit" disabled={isSubmitting}>
        {isSubmitting ? "가입 처리 중..." : "계정 만들기"}
      </Button>
    </form>
  )
}
'''


def _signup_api_connect_test_content() -> str:
    return '''import { readFileSync } from "node:fs"
import { join } from "node:path"

const root = process.cwd()
const files = {
  signupApi: join(root, "lib/signup-api.ts"),
  signupForm: join(root, "components/signup/signup-form.tsx"),
  validation: join(root, "lib/signup-validation.ts"),
}

const contents = Object.fromEntries(
  Object.entries(files).map(([key, path]) => [key, readFileSync(path, "utf8")]),
)

const checks = [
  [contents.signupApi.includes("/api/members/signup"), "회원가입 API endpoint 확인"],
  [contents.signupApi.includes("NEXT_PUBLIC_STUDYHUB_API_BASE_URL"), "API base URL 환경변수 확인"],
  [contents.signupApi.includes("toSignupMemberRequest"), "request 변환 함수 확인"],
  [contents.signupForm.includes("await signupMember(values)"), "회원가입 submit API 호출 확인"],
  [contents.signupForm.includes("StudyHub 회원가입이 완료되었습니다."), "성공 메시지 확인"],
  [contents.signupForm.includes("가입 처리 중..."), "제출 중 상태 확인"],
  [contents.validation.includes("비밀번호가 서로 일치하지 않습니다."), "한국어 검증 메시지 확인"],
]

const failed = checks.filter(([passed]) => !passed)
if (failed.length > 0) {
  for (const [, message] of failed) {
    console.error(`실패: ${message}`)
  }
  process.exit(1)
}

console.log("회원가입 API 연동 smoke 검증 통과")
'''
