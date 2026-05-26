# Backend Runner Implementation Rules

Kotlin/Spring Boot backend runners must generate code that follows DDD and hexagonal architecture boundaries. These are baseline rules for every backend implementation.

## Controller And DTO

- Keep controllers thin.
- A controller may parse request data, call one application service/usecase, and return a response.
- Do not define request/response `data class` declarations inside controller files.
- Put presentation DTOs in separate files near the controller package.
- Convert request DTOs into application commands through explicit mapping methods.
- Do not put business rules, persistence calls, password hashing, or policy checks in controllers.

Recommended package shape:

```text
bootstrap/presentation/{domain}/
├── {Usecase}Controller.kt
├── {Usecase}Request.kt
├── {Usecase}Response.kt
├── ApiErrorResponse.kt
└── ApiExceptionHandler.kt
```

## DDD And Hexagonal Boundaries

- `domain` contains domain models and domain rules that do not depend on Spring, JPA, or web APIs.
- `application` contains usecase services, commands/results, ports, policy checkers, validators, and orchestration flow.
- `application/port` contains interfaces required by the usecase.
- `infrastructure` contains adapters implementing application ports.
- `bootstrap/presentation` contains HTTP controllers, request/response DTOs, exception handlers, and framework wiring.

Runners must not skip these boundaries for speed. If a feature cannot be implemented while preserving these boundaries, the runner must stop with `needs_human` instead of generating low-quality code.

## File Creation Rules

- One meaningful public class/data class per file by default.
- File names must match the primary class name.
- Avoid `Util`, `Helper`, `Manager`, `CommonService` unless the existing project already uses that convention and there is no better domain name.
- Avoid `companion object` in newly generated backend code unless the project already has a strong local pattern requiring it.
- Prefer explicit responsibility classes over hiding business behavior in static-like factories.

## Application Service Rules

- Application services orchestrate the usecase flow.
- The main method should make the business sequence readable.
- Do not collapse the service into one-line delegation to another private method.
- Extract policy, validation, state-change, persistence boundary, or external integration responsibilities into named collaborators.
- Responsibility object public methods should have one Korean comment explaining why the rule exists.

## Error And Logging

- User-facing API errors must be safe and actionable.
- Do not expose internal implementation details, stack traces, SQL details, class names, or raw external-system errors to the user.
- Internal logs must contain enough detail for support and debugging.
- Follow the logging policy in `usecase-orchestration-style` for failures.
