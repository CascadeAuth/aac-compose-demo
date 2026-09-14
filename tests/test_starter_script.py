"""The shell entry point: syntax, static analysis when shellcheck is present, help."""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from conftest import STARTER, docker_available


def test_bash_syntax():
    subprocess.run(["bash", "-n", str(STARTER)], check=True)


def test_help_lists_every_command():
    result = subprocess.run([str(STARTER), "help"], capture_output=True, text=True)
    assert result.returncode == 0
    for command in ("setup", "up", "exercise", "check", "status", "retry", "build", "logs", "down", "clean"):
        assert f"./starter {command}" in result.stderr, command


def test_unknown_command_is_a_usage_error():
    result = subprocess.run([str(STARTER), "bogus"], capture_output=True, text=True)
    assert result.returncode == 2
    assert "unknown command" in result.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck is not installed")
def test_shellcheck():
    subprocess.run(["shellcheck", str(STARTER)], check=True)


def test_script_is_executable_and_bash_3_compatible():
    assert STARTER.stat().st_mode & 0o111
    text = STARTER.read_text()
    for construct in ("mapfile", "readarray", "declare -A", ",,}", "^^}"):  # bash 4 only
        assert construct not in text, construct


@pytest.mark.skipif(not docker_available() or shutil.which("aac") is None, reason="needs docker and the aac CLI")
def test_setup_refuses_a_workspace_that_belongs_to_another_profile(synthetic_home, monkeypatch):
    # The synthetic workspace was created under profile `stage`; asking for it
    # under another profile must stop before `aac init` creates a profile section.
    env = {**os.environ, "AAC_CLI_HOME": str(synthetic_home), "AAC_STARTER_PROFILE": "team-two",
           "AAC_STARTER_WORKSPACE": "starter"}
    result = subprocess.run([str(STARTER), "setup", "--yes"], capture_output=True, text=True, env=env)
    assert result.returncode == 1
    assert "belongs to profile 'stage', not 'team-two'" in result.stderr
    assert "[team-two]" not in (synthetic_home / "config").read_text() if (synthetic_home / "config").exists() else True


def test_setup_option_without_a_value_is_refused():
    result = subprocess.run([str(STARTER), "setup", "--display-name"], capture_output=True, text=True,
                            env={**os.environ, "AAC_CLI_HOME": "/nonexistent-for-this-test"})
    assert result.returncode == 1
    assert "--display-name needs a value" in result.stderr
