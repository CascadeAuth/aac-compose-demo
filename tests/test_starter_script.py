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
    for command in ("setup", "up", "exercise", "down"):
        assert f"./starter {command}" in result.stdout, command


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck is not installed")
def test_shellcheck():
    subprocess.run(["shellcheck", str(STARTER)], check=True)


def test_script_is_executable_and_bash_3_compatible():
    assert STARTER.stat().st_mode & 0o111
    text = STARTER.read_text()
    for construct in ("mapfile", "readarray", "declare -A", ",,}", "^^}"):  # bash 4 only
        assert construct not in text, construct
