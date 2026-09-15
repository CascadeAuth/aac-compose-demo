"""The shell entry point: syntax, static analysis when shellcheck is present, help, and `up`'s waits."""

from __future__ import annotations

import os
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


# `./starter up` with stand-ins for docker, aac, date and sleep: docker
# succeeds, the stand-in clock moves 100 seconds per reading, and the stand-in
# aac either shows both published keys or never does.
STAND_INS = {
    "docker": "#!/bin/sh\nexit 0\n",
    "sleep": "#!/bin/sh\nexit 0\n",
    "date": '#!/bin/sh\nnow=$(cat "$CLOCK" 2>/dev/null || echo 0)\necho $((now + 100)) > "$CLOCK"\necho "$now"\n',
    "aac": '#!/bin/sh\necho "$AAC_REPORT"\n',
}
PUBLISHED = '{"healthy": true, "remote": {"root_keys": {"contains_root_key_id": true}, "spiffe_bundle": {"contains_ca_anchor_id": true}}}'


def run_up(tmp_path, report: str) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, script in STAND_INS.items():
        (bin_dir / name).write_text(script)
        (bin_dir / name).chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "AAC_CLI_HOME": str(tmp_path / "aac"),
           "CLOCK": str(tmp_path / "clock"), "AAC_REPORT": report}
    return subprocess.run([str(STARTER), "up"], capture_output=True, text=True, env=env)


def test_up_says_what_it_waits_for_and_finishes_once_the_keys_are_served(tmp_path):
    result = run_up(tmp_path, PUBLISHED)
    assert result.returncode == 0, result.stderr
    steps = [line for line in result.stdout.splitlines() if line.endswith("...") or line.startswith("Running")]
    assert steps == [
        "Building the agent image and starting the agent, the sidecar and the publisher ...",
        "Waiting until the sidecar is ready ...",
        "Waiting until AAC serves your public keys at https://trust.stage.cascadeauth.dev (the publisher uploads them) ...",
        "Running. Next: ./starter exercise",
    ]


def test_up_gives_up_after_five_minutes_without_the_keys(tmp_path):
    result = run_up(tmp_path, '{"healthy": true, "remote": {}}')
    assert result.returncode == 1
    assert "still not served at https://trust.stage.cascadeauth.dev after 5 minutes" in result.stderr
    assert "docker logs aac-starter-publisher-1" in result.stderr
    assert "Running" not in result.stdout
    # The first reading (0) sets the deadline at 300; the checks read 100, 200
    # and 300 and give up at 300, leaving the stand-in clock at 400.
    assert int((tmp_path / "clock").read_text()) == 400
