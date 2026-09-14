"""The README and the scripts read as public documentation and stay consistent.

* Every ``aac …`` command in a shell fence parses with the published CLI.
* No project-internal vocabulary (work-item ids, agent names, review shorthand).
* The versions the README names are the ones compose.yaml and the Dockerfile pin.
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
    r"|Python reference|the release process|§|\bkickoff\b|\bruling\b|\bratified\b|\bbacklog\b"
    r"|\breview [A-Z][0-9]+\b|\bWeek[ -]+[0-9]+\b|\bStage[ -]+[0-9]+\b",
    re.IGNORECASE,
)

PUBLIC_TEXT_FILES = [README, STARTER, COMPOSE_FILE, AGENT_DIR / "agent.py", AGENT_DIR / "client.py",
                     AGENT_DIR / "Dockerfile", REPO / ".github" / "workflows" / "checks.yml"]


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


def compose_default(name: str) -> str:
    match = re.search(r"\$\{" + name + r":-([^}]+)\}", COMPOSE_FILE.read_text())
    assert match, name
    return match.group(1)


def test_version_pins_agree():
    readme = README.read_text()
    sidecar = compose_default("AAC_SIDECAR_VERSION")
    publisher = compose_default("AAC_PUBLISHER_VERSION")
    invoke_auth = compose_default("AAC_INVOKE_AUTH_VERSION")
    dockerfile = (AGENT_DIR / "Dockerfile").read_text()
    assert f"ARG AAC_INVOKE_AUTH_VERSION={invoke_auth}" in dockerfile
    versions_table = readme.split("## Versions")[1].split("## ")[0]
    assert f"`{sidecar}`" in versions_table and f"aac-sidecar:{sidecar}" in readme
    assert f"`{publisher}`" in versions_table and f"aac-trust-anchor-publisher:{publisher}" in readme
    assert f"`{invoke_auth}`" in versions_table
    requirements = (REPO / "tests" / "requirements.txt").read_text()
    assert f"aac-invoke-auth[fastapi]=={invoke_auth}" in requirements
    cli = re.search(r"aac-cli==([0-9.]+)", requirements).group(1)
    assert f"pip install 'aac-cli=={cli}'" in readme
    assert f"'aac-cli=={cli}'" in STARTER.read_text()
    floor = re.search(r'AAC_CLI_MINIMUM="([0-9.]+)"', STARTER.read_text()).group(1)
    assert f"({floor} or newer works)" in versions_table
