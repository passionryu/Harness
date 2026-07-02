from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class AgentSpecError(ValueError):
    """Raised when an agent Markdown spec is missing required structure."""


@dataclass(frozen=True)
class AgentSpec:
    name: str
    version: int
    summary: str
    triggers: list[str]
    inputs: list[str]
    outputs: list[str]
    body: str
    sections: dict[str, str]
    path: Path

    def section(self, title: str) -> str:
        return self.sections.get(title, "")


DEFAULT_SPEC_DIR = Path(__file__).resolve().parent / "specs"
DEFAULT_PLAYBOOK_DIR = Path(__file__).resolve().parent / "playbooks"
REQUIRED_SECTIONS = ["Mission", "Decision Rules", "Hard Rules"]


def load_agent_spec(name: str, spec_dir: Path = DEFAULT_SPEC_DIR) -> AgentSpec:
    path = spec_dir / f"{name}.md"
    if not path.exists():
        raise AgentSpecError(f"Agent spec 파일이 없습니다: {path}")
    return parse_agent_spec(path.read_text(encoding="utf-8"), path=path)


def load_agent_playbook(name: str) -> AgentSpec:
    return load_agent_spec(name, DEFAULT_PLAYBOOK_DIR)


def list_markdown_specs(spec_dir: Path = DEFAULT_SPEC_DIR) -> list[AgentSpec]:
    specs: list[AgentSpec] = []
    for path in sorted(spec_dir.glob("*.md")):
        if path.name.upper() == "README.MD":
            continue
        specs.append(load_agent_spec(path.stem, spec_dir))
    return specs


def parse_agent_spec(markdown: str, path: Path | None = None) -> AgentSpec:
    metadata, body = _split_frontmatter(markdown)
    spec_path = path or Path("<memory>")
    name = _required_str(metadata, "name", spec_path)
    version = _required_int(metadata, "version", spec_path)
    summary = _required_str(metadata, "summary", spec_path)
    triggers = _required_list(metadata, "triggers", spec_path)
    inputs = _required_list(metadata, "inputs", spec_path)
    outputs = _required_list(metadata, "outputs", spec_path)
    sections = _extract_sections(body)
    missing_sections = [section for section in REQUIRED_SECTIONS if not sections.get(section)]
    if missing_sections:
        raise AgentSpecError(f"{spec_path}에 필수 섹션이 없습니다: {', '.join(missing_sections)}")
    return AgentSpec(
        name=name,
        version=version,
        summary=summary,
        triggers=triggers,
        inputs=inputs,
        outputs=outputs,
        body=body.strip(),
        sections=sections,
        path=spec_path,
    )


def render_agent_spec_context(spec: AgentSpec) -> list[str]:
    lines = [
        f"## Agent Markdown Spec: {spec.name}",
        "",
        f"- version: `{spec.version}`",
        f"- summary: {spec.summary}",
        f"- triggers: {', '.join(spec.triggers)}",
        f"- inputs: {', '.join(spec.inputs)}",
        f"- outputs: {', '.join(spec.outputs)}",
        "",
    ]
    for title in REQUIRED_SECTIONS:
        lines.extend([f"### {title}", spec.section(title).strip(), ""])
    return lines


def _split_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    if not markdown.startswith("---\n"):
        raise AgentSpecError("Agent spec은 YAML-like frontmatter로 시작해야 합니다.")
    try:
        _, frontmatter, body = markdown.split("---", 2)
    except ValueError as exc:
        raise AgentSpecError("Agent spec frontmatter 종료 구분자(---)가 없습니다.") from exc
    return _parse_frontmatter(frontmatter), body


def _parse_frontmatter(frontmatter: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in frontmatter.splitlines():
        if not raw_line.strip():
            continue
        if raw_line.startswith("  - ") and current_key:
            value = raw_line.removeprefix("  - ").strip()
            current_value = metadata.setdefault(current_key, [])
            if not isinstance(current_value, list):
                raise AgentSpecError(f"{current_key}는 list와 scalar를 동시에 사용할 수 없습니다.")
            current_value.append(_strip_quotes(value))
            continue

        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", raw_line)
        if not match:
            raise AgentSpecError(f"지원하지 않는 frontmatter 라인입니다: {raw_line}")
        key, value = match.group(1), match.group(2).strip()
        current_key = key
        if value == "":
            metadata[key] = []
        elif value.startswith("[") and value.endswith("]"):
            metadata[key] = [_strip_quotes(item.strip()) for item in value[1:-1].split(",") if item.strip()]
        else:
            metadata[key] = _strip_quotes(value)
    return metadata


def _extract_sections(body: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current_title: str | None = None
    for line in body.splitlines():
        if line.startswith("# "):
            current_title = line.removeprefix("# ").strip()
            sections.setdefault(current_title, [])
            continue
        if current_title:
            sections[current_title].append(line)
    return {title: "\n".join(lines).strip() for title, lines in sections.items()}


def _required_str(metadata: dict[str, Any], key: str, path: Path) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AgentSpecError(f"{path} frontmatter에 `{key}` 문자열이 필요합니다.")
    return value.strip()


def _required_int(metadata: dict[str, Any], key: str, path: Path) -> int:
    value = metadata.get(key)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise AgentSpecError(f"{path} frontmatter에 `{key}` 정수가 필요합니다.") from exc


def _required_list(metadata: dict[str, Any], key: str, path: Path) -> list[str]:
    value = metadata.get(key)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
        raise AgentSpecError(f"{path} frontmatter에 `{key}` list가 필요합니다.")
    return [item.strip() for item in value]


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
