"""The README and the scripts read as public documentation and stay consistent.

* Every ``aac …`` command in a shell fence parses with the published CLI.
* No project-internal vocabulary (work-item ids, agent names, review shorthand).
* Test dependencies match the installation commands in the README and Dockerfile.
"""

from __future__ import annotations

import re
import shlex

import pytest
from aac_cli.cli import build_parser

from conftest import AGENT_DIR, COMPOSE_FILE, README, REPO, STARTER

SHELL_FENCES = {"bash", "console", "sh"}
ENVIRONMENT_ASSIGNMENT = re.compile(r"^[A-Z_][A-Z0-9_]*=")

# Vocabulary that belongs to the project's own process, never to a reader.
INTERNAL_LANGUAGE = re.compile(
    r"\b(?:[AB][0-9]+|PR[ #.-]*[0-9]+|Phase[ -]+[0-9]+|Nelson|Claude|Codex|Milestone|rehearsal)\b"
    r"|Eng Spec|PARITY\.md|aac-prototype|owner authorization|source-free|private Go repository"
    r"|Python reference|the release process|§|\bSpec\b|\bkickoff\b|\bruling\b|\bratified\b"
    r"|\bamendment\b|\bbacklog\b|\bowner\b|\breview [A-Z][0-9]+\b|\bround[ -][0-9]+\b"
    r"|\bWeek[ -]+[0-9]+\b|\bStage[ -]+[0-9]+\b|\bDecision [0-9]+\b|\bD[0-9]\b",
    re.IGNORECASE,
)

# The page describes the present: no narrative about how things used to be.
HISTORY_LANGUAGE = re.compile(
    r"\bformerly\b|\bpreviously\b|\bdescoped\b|\bprototype-era\b|\btoday\b"
    r"|\bearlier (?:release|version)s?\b|\bsince (?:version|release|the [0-9]+\.[0-9])",
    re.IGNORECASE,
)

PUBLIC_TEXT_FILES = sorted(
    [README, STARTER, COMPOSE_FILE, AGENT_DIR / "agent.py", AGENT_DIR / "client.py",
     REPO / "CONTRIBUTING.md", REPO / "AGENTS.md",
     AGENT_DIR / "Dockerfile", REPO / ".github" / "workflows" / "checks.yml", REPO / "docs" / "evidence" / "README.md"]
    + [p for p in (REPO / "tests").rglob("*.py") if p.name != "test_readme.py"]  # the patterns live here
    + [REPO / "tests" / "requirements.txt"]
)


def shell_fences(markdown: str) -> list[list[str]]:
    fences, inside = [], None
    for line in markdown.splitlines():
        stripped = line.strip()
        if inside is None:
            if stripped.startswith("```") and stripped[3:].strip() in SHELL_FENCES:
                inside = []
        elif stripped.startswith("```"):
            fences.append(inside)
            inside = None
        else:
            inside.append(line)
    return fences


def commands_in(lines: list[str]) -> list[str]:
    commands, pending = [], ""
    for raw in lines:
        line = (pending + " " + raw.strip()).strip() if pending else raw.strip()
        pending = ""
        if not line or line.startswith("#"):
            continue
        if line.endswith("\\"):
            pending = line[:-1].rstrip()
            continue
        commands.append(line.removeprefix("$ "))
    return commands


def aac_argv(command: str) -> list[str] | None:
    words = shlex.split(command, comments=True)
    while words and ENVIRONMENT_ASSIGNMENT.match(words[0]):
        words.pop(0)
    if not words or words[0] != "aac":
        return None
    # The network table uses an explicit ellipsis for the reader's identity.
    # Substitute only that value; the verb and option still have to parse.
    if "--spiffe-id" in words:
        index = words.index("--spiffe-id") + 1
        if words[index] == "…":
            words[index] = "spiffe://example.com/demo/agent"
    return words[1:]


def readme_aac_commands() -> list[str]:
    """Every ``aac …`` command line in a shell fence, plus every inline `aac …` span."""
    text = README.read_text()
    fenced = [c for fence in shell_fences(text) for c in commands_in(fence)]
    inline = re.findall(r"`(aac [^`]+)`", text)
    return [c for c in fenced + inline if aac_argv(c) is not None]


@pytest.mark.parametrize("command", readme_aac_commands())
def test_every_readme_aac_command_parses(command: str):
    try:
        build_parser().parse_args(aac_argv(command))
    except SystemExit as exit:
        if exit.code not in (0, None):
            pytest.fail(f"{command!r} exits {exit.code}")


def test_readme_names_aac_commands_at_all():
    assert len(readme_aac_commands()) >= 3


def test_starter_commands_in_readme_exist_in_the_script():
    script = STARTER.read_text()
    for name in re.findall(r"`\./starter ([a-z]+)", README.read_text()):
        assert f"  {name})" in script or f"{name}|" in script, name


@pytest.mark.parametrize("path", PUBLIC_TEXT_FILES, ids=lambda p: p.name)
def test_public_files_contain_no_internal_language(path):
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        match = INTERNAL_LANGUAGE.search(line)
        assert match is None, f"{path.name}:{number}: {match.group(0)!r} in {line.strip()!r}"


def test_readme_describes_the_present():
    for number, line in enumerate(README.read_text().splitlines(), start=1):
        match = HISTORY_LANGUAGE.search(line)
        assert match is None, f"README.md:{number}: {match.group(0)!r} in {line.strip()!r}"


def test_dependencies_match_installation_commands():
    readme = README.read_text()
    requirements = (REPO / "tests" / "requirements.txt").read_text()
    invoke_auth = re.search(r"aac-invoke-auth\[fastapi\]==([0-9.]+)", (AGENT_DIR / "Dockerfile").read_text()).group(1)
    cli = re.search(r"aac-cli==([0-9.]+)", requirements).group(1)
    assert f"aac-invoke-auth[fastapi]=={invoke_auth}" in requirements
    assert f"pip install 'aac-cli=={cli}'" in readme


def test_material_cases_match_the_pinned_cli():
    from importlib.metadata import version
    from aac_cli.material_cases import MATERIAL_CASES_START, MATERIAL_CASES_END, material_cases_markdown

    assert version("aac-cli") == "0.2.0"
    text = README.read_text()
    assert text.count(MATERIAL_CASES_START) == text.count(MATERIAL_CASES_END) == 1
    start = text.index(MATERIAL_CASES_START)
    end = text.index(MATERIAL_CASES_END) + len(MATERIAL_CASES_END)
    assert text[start:end] == material_cases_markdown(level=3).rstrip("\n")


def test_platform_guidance_and_network_section_position():
    text = README.read_text()
    assert "Ubuntu 24.04 or newer virtual machine" in text
    assert "Native Windows is not supported" in text
    assert "Multipass" in text and "WSL2 with Ubuntu" in text
    assert "has not been tested with this starter" in text
    after_leaves_out = text.split("## What this example leaves out", 1)[1]
    assert after_leaves_out.split("\n## ", 1)[1].startswith("From this example to a network of agents")
