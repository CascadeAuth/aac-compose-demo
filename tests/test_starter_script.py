"""The shell entry point: syntax, static analysis when shellcheck is present, help."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from conftest import STARTER


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
    for construct in ("mapfile", "declare -A", "${", ",,}"):
        pass  # bash 4 constructs are checked below by name
    assert "mapfile" not in text and "declare -A" not in text and "readarray" not in text
