"""The documented flow against the real AAC stage service. Opt in with AAC_STARTER_LIVE=1.

Run it once `./starter setup` has created your tenant; with the tenant in
place it registers nothing:

    AAC_STARTER_LIVE=1 AAC_STARTER_PROFILE=stage python -m pytest tests/live -q

It runs `./starter` as a reader would, checks what each command prints, and
writes durations to a dated, commit-attributed file under docs/evidence/.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from pathlib import Path

import pytest

from conftest import REPO, STARTER

pytestmark = pytest.mark.skipif(os.environ.get("AAC_STARTER_LIVE") != "1", reason="set AAC_STARTER_LIVE=1")

AGENT = os.environ.get("AAC_STARTER_AGENT", "starter")
CLI_HOME = Path(os.environ.get("AAC_CLI_HOME", Path.home() / ".aac"))
HAND_OFFS = ["mint", "agent", "dispatch", "receive", "respond", "a2a", "refused"]


def output_of(*command: str) -> str:
    return subprocess.run(list(command), capture_output=True, text=True, cwd=REPO).stdout.strip()


def starter(evidence: dict, command: str, label: str | None = None) -> str:
    """Run one ./starter command, record how long it took, and return what it printed."""
    started = time.monotonic()
    result = subprocess.run([str(STARTER), command], capture_output=True, text=True, cwd=REPO)
    evidence["seconds"][label or command] = round(time.monotonic() - started, 1)
    assert result.returncode == 0, f"./starter {command} exited {result.returncode}\n{result.stdout}\n{result.stderr}"
    assert_secret_free(result.stdout + result.stderr)
    return result.stdout


def assert_secret_free(text: str) -> None:
    secrets = [(CLI_HOME / "agents" / AGENT / "agent" / "pairing.secret").read_bytes().strip()]
    secrets += [key.read_bytes().strip() for key in (CLI_HOME / "credentials").glob("tnt-*") if key.suffix != ".session"]
    leaked = any(secret and secret.decode(errors="ignore") in text for secret in secrets)
    assert not leaked, "a secret value appears in the starter's output"  # the value itself is never printed


def hand_offs(stdout: str) -> dict:
    """The exercise's lines, keyed by their first word."""
    return {line.split()[0]: line.split(maxsplit=1)[1] for line in stdout.splitlines() if line.split()[:1]}


def identity() -> dict:
    status = json.loads(output_of("aac", "agent", "status", "--agent", AGENT, "--output", "json"))
    return {key: status[key] for key in ("tenant_id", "hosted_trust_domain", "workload_spiffe_id", "root_key_id")}


@pytest.fixture(scope="module")
def evidence():
    record: dict = {
        "platform": {"system": platform.system(), "machine": platform.machine(), "release": platform.release()},
        "docker": output_of("docker", "version", "--format", "{{.Server.Version}}"),
        "compose": output_of("docker", "compose", "version", "--short"),
        "aac_cli": output_of("aac", "--version"),
        "starter_commit": output_of("git", "rev-parse", "HEAD"),
        "starter_tracked_files_modified": bool(output_of("git", "status", "--porcelain", "--untracked-files=no")),
        "measured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seconds": {},
    }
    yield record
    starter(record, "down")
    record["completed_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    stamp = record["measured_utc"].replace("-", "").replace(":", "")
    name = f"{platform.system().lower()}-{platform.machine().lower()}-{stamp}-{record['starter_commit'][:7]}.json"
    (REPO / "docs" / "evidence" / name).write_text(json.dumps(record, indent=2) + "\n")


def test_01_setup_with_an_existing_tenant(evidence):
    starter(evidence, "setup")


def test_02_up(evidence):
    assert "Running. Next: ./starter exercise" in starter(evidence, "up")


def test_03_exercise_shows_every_hand_off(evidence):
    lines = hand_offs(starter(evidence, "exercise"))
    evidence["exercise"] = lines
    assert list(lines) == HAND_OFFS
    assert "(delivered)" in lines["agent"] and '"action": "forward"' in lines["agent"]
    assert "self_receive" in lines["dispatch"] and "task_ref:" in lines["dispatch"]
    assert lines["receive"].endswith(identity()["workload_spiffe_id"])
    assert "decided settle" in lines["respond"]
    assert lines["a2a"].endswith("dispatched")
    assert lines["refused"].endswith("HTTP 401")


def test_04_nothing_is_published_and_containers_run_as_you():
    names = output_of("docker", "ps", "--filter", "label=com.docker.compose.project=aac-starter",
                      "--format", "{{.Names}}").split()
    assert len(names) == 3, names
    for name in names:
        assert output_of("docker", "inspect", "-f", "{{json .HostConfig.PortBindings}}", name) in ("{}", "null"), name
        assert output_of("docker", "inspect", "-f", "{{.Config.User}}", name) == f"{os.getuid()}:{os.getgid()}", name


def test_05_down_and_up_keep_the_same_identity(evidence):
    before = identity()
    starter(evidence, "down")
    starter(evidence, "up", "up_again")
    assert "(delivered)" in hand_offs(starter(evidence, "exercise", "exercise_again"))["agent"]
    assert identity() == before
    evidence["identity"] = before
