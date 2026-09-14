"""The documented flow against the real AAC stage service — opt-in.

Run with an already set-up workspace (``./starter setup`` done, sign-in
completed) and ``AAC_STARTER_LIVE=1``::

    AAC_STARTER_LIVE=1 AAC_STARTER_PROFILE=stage python -m pytest tests/live -q -s

It drives ``./starter`` exactly as a reader would, checks each result, and
writes the measured timings to ``docs/evidence/<platform>.json``. It never
registers a tenant, never touches private material, and leaves the stack
stopped. The missing-credential check moves the tenant API key aside for a
few seconds and restores it; skip it with ``AAC_STARTER_LIVE_SKIP_CREDENTIAL_CHECK=1``.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import time
from pathlib import Path

import pytest

from conftest import REPO, STARTER

pytestmark = pytest.mark.skipif(os.environ.get("AAC_STARTER_LIVE") != "1", reason="set AAC_STARTER_LIVE=1")

EVIDENCE_DIR = REPO / "docs" / "evidence"
WORKSPACE = os.environ.get("AAC_STARTER_WORKSPACE", "starter")
CLI_HOME = Path(os.environ.get("AAC_CLI_HOME", Path.home() / ".aac"))


def starter(*args: str, expect: int = 0) -> subprocess.CompletedProcess:
    started = time.monotonic()
    result = subprocess.run([str(STARTER), *args], capture_output=True, text=True, cwd=REPO)
    result.elapsed = round(time.monotonic() - started, 1)  # type: ignore[attr-defined]
    assert result.returncode == expect, f"./starter {' '.join(args)} exited {result.returncode}\n{result.stdout}\n{result.stderr}"
    return result


def json_documents(text: str) -> list[dict]:
    """Every top-level JSON object printed on stdout, in order (the client's summaries)."""
    decoder, documents, position = json.JSONDecoder(), [], 0
    while True:
        start = text.find("\n{", position)
        if start < 0 and position == 0 and text.startswith("{"):
            start = -1
        elif start < 0:
            return documents
        try:
            document, end = decoder.raw_decode(text, start + 1)
        except json.JSONDecodeError:
            position = start + 2
            continue
        documents.append(document)
        position = end


def last_json(text: str) -> dict:
    documents = json_documents(text)
    assert documents, text
    return documents[-1]


@pytest.fixture(scope="module")
def evidence():
    record: dict = {
        "platform": {"system": platform.system(), "machine": platform.machine(), "release": platform.release()},
        "docker": subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True).stdout.strip(),
        "compose": subprocess.run(["docker", "compose", "version", "--short"], capture_output=True, text=True).stdout.strip(),
        "aac_cli": subprocess.run(["aac", "--version"], capture_output=True, text=True).stdout.strip(),
        "measured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "steps": {},
    }
    yield record
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{platform.system().lower()}-{platform.machine().lower()}.json"
    (EVIDENCE_DIR / name).write_text(json.dumps(record, indent=2) + "\n")
    starter("down")


def secret_bytes() -> list[bytes]:
    pair = CLI_HOME / "workspaces" / WORKSPACE / "pair" / "pairing.secret"
    values = [pair.read_bytes().strip()]
    for key in (CLI_HOME / "credentials").glob("tnt-*"):
        if key.suffix != ".session":
            values.append(key.read_bytes().strip())
    return [v for v in values if v]


def assert_secret_free(*texts: str):
    # Computed first so a failure never prints the secret itself.
    leaked = any(value.decode(errors="ignore") in text for text in texts for value in secret_bytes())
    assert not leaked, "a secret value appears in the starter's output"


def test_01_setup_is_idempotent(evidence):
    result = starter("setup")
    evidence["steps"]["setup_repeat_s"] = result.elapsed
    assert "Setup complete" in result.stderr
    assert_secret_free(result.stdout, result.stderr)


def test_02_up_reports_ready_and_trusted(evidence):
    result = starter("up")
    evidence["steps"]["up_s"] = result.elapsed
    assert "Running. Next: ./starter exercise" in result.stderr
    measured = dict(re.findall(r"measured: (.+?) took (\d+)s", result.stderr))
    evidence["steps"]["up_measured"] = measured
    assert set(measured) == {"start until the sidecar is ready", "trust publication visible"}
    assert_secret_free(result.stdout, result.stderr)


def test_03_exercise_completes_the_workflow(evidence):
    result = starter("exercise")
    evidence["steps"]["exercise_s"] = result.elapsed
    summary = last_json(result.stdout)
    evidence["steps"]["exercise"] = summary
    assert summary["native_delivery"] == "delivered"
    assert summary["a2a_retry"] == "same response bytes"
    assert summary["local_evidence"]["terminal_attestation_present"] is True
    assert {"mint:success", "receive:success", "respond:success"} <= set(summary["local_evidence"]["events_for_root"])
    assert re.fullmatch(r"[0-9a-f]{64}", summary["root_token_id"])
    assert_secret_free(result.stdout, result.stderr)


def test_04_check_probes_refusals(evidence):
    result = starter("check")
    probe = json_documents(result.stdout)[0]  # the probe summary; the CLI's table follows it
    evidence["steps"]["check"] = probe
    assert probe["replay_profile"] == "basic"
    assert "HTTP 401" in probe["unsigned_and_wrongly_signed_calls"]
    assert "refused" in probe["unknown_class_of_action"]
    assert "contains_root_key_id': True" in result.stdout
    assert "contains_ca_anchor_id': True" in result.stdout
    assert_secret_free(result.stdout, result.stderr)


def test_05_no_ports_are_published_and_loopback_stays_private():
    names = subprocess.run(["docker", "ps", "--filter", f"name=aac-{WORKSPACE}-", "--format", "{{.Names}}"],
                           capture_output=True, text=True).stdout.split()
    assert len(names) == 3, names
    for name in names:
        ports = subprocess.run(["docker", "inspect", "-f", "{{json .HostConfig.PortBindings}}", name],
                               capture_output=True, text=True).stdout.strip()
        assert ports in ("{}", "null"), (name, ports)
        user = subprocess.run(["docker", "inspect", "-f", "{{.Config.User}}", name], capture_output=True, text=True).stdout.strip()
        assert user == f"{os.getuid()}:{os.getgid()}", (name, user)


def test_06_recreate_keeps_identity_and_retained_results(evidence):
    starter("down")
    assert not subprocess.run(["docker", "ps", "-q", "--filter", "name=aac-starter-"], capture_output=True, text=True).stdout.strip()
    result = starter("up")
    evidence["steps"]["up_after_recreate_s"] = result.elapsed
    retry = last_json(starter("retry").stdout)
    assert retry["retained_result"].startswith("same response bytes")
    again = last_json(starter("exercise").stdout)
    assert again["native_delivery"] == "delivered"
    status = subprocess.run(["aac", "workspace", "status", "--workspace", WORKSPACE, "--output", "json"],
                            capture_output=True, text=True).stdout
    document = json.loads(status)
    evidence["steps"]["identity_after_recreate"] = {k: document[k] for k in ("tenant_id", "hosted_trust_domain", "workload_spiffe_id", "root_key_id")}
    assert document["healthy"] is True


def test_07_rebuild_keeps_retained_results(evidence):
    starter("build")
    result = starter("up")
    evidence["steps"]["up_after_rebuild_s"] = result.elapsed
    retry = last_json(starter("retry").stdout)
    assert retry["retained_result"].startswith("same response bytes")


@pytest.mark.skipif(os.environ.get("AAC_STARTER_LIVE_SKIP_CREDENTIAL_CHECK") == "1", reason="credential check skipped")
def test_08_missing_credential_is_refused_with_the_cli_report(evidence):
    status = json.loads(subprocess.run(["aac", "workspace", "status", "--workspace", WORKSPACE, "--output", "json"],
                                       capture_output=True, text=True).stdout)
    key = CLI_HOME / "credentials" / status["tenant_id"]
    moved = key.with_name(key.name + ".moved-by-live-test")
    key.rename(moved)
    try:
        result = starter("up", expect=1)
    finally:
        moved.rename(key)
    assert "not ready to run" in result.stderr
    assert "missing_files" in result.stderr
    evidence["steps"]["missing_credential"] = "refused; the CLI report was shown"
    assert starter("up").returncode == 0
