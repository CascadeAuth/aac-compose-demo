"""Run against the two already-authorized stage tenants. No tenant creation.

AAC_DEMO_LIVE=1 enables business and adversarial cases. Also set
AAC_DEMO_LIFECYCLE=1 to apply/refresh configuration and renew test certificates.
AAC_DEMO_CONFIG_DIR points at the operator-authored input copies.
"""
import json
import os
import subprocess
import time
from pathlib import Path

import pytest
import yaml
from conftest import REPO

pytestmark = pytest.mark.skipif(os.environ.get("AAC_DEMO_LIVE") != "1", reason="set AAC_DEMO_LIVE=1")
HOME = Path(os.environ.get("AAC_CLI_HOME", Path.home() / ".aac"))
CONFIG = Path(os.environ.get("AAC_DEMO_CONFIG_DIR", REPO / ".local"))


def run(*args):
    began = time.monotonic()
    result = subprocess.run(args, cwd=REPO, capture_output=True, text=True, timeout=600)
    if os.environ.get("AAC_DEMO_EVIDENCE"):
        with Path(os.environ["AAC_DEMO_EVIDENCE"]).open("a") as output:
            output.write(json.dumps({"argv": args, "exit_code": result.returncode,
                "seconds": round(time.monotonic() - began, 3), "stdout": result.stdout,
                "stderr": result.stderr}) + "\n")
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def json_rows(output):
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


def test_positive_fare_change_and_fresh_authority():
    successful = []
    for scenario in ("reservation", "fare-change", "fresh-authority"):
        rows = json_rows(run("./demo", "run", scenario))
        if scenario == "fare-change":
            assert rows[-1]["application_decline"]["decision"]["action"] == "refuse"
        else:
            assert rows[-1]["terminal_attestation_verification"] == "verified"
            assert rows[-1]["reservation"]["amount"] == (9500 if scenario == "fresh-authority" else 8000)
            successful.append(rows[-1])
    assert successful[0]["task_ref"] != successful[1]["task_ref"]
    assert successful[0]["dispatch"]["token_id"] != successful[1]["dispatch"]["token_id"]


def test_adversarial_controls():
    report = json_rows(run("./demo", "check"))[-1]
    assert len(report["chain_start"]) == 6 and len(report["receiver"]) == 4
    for case in report["chain_start"]:
        assert case["successful_mints"] == case["application_invocations"] == 0


@pytest.mark.skipif(os.environ.get("AAC_DEMO_LIFECYCLE") != "1", reason="explicit lifecycle opt-in required")
def test_local_refusal_refresh_and_ca_renewal():
    statuses = {agent: json.loads(run("aac", "agent", "status", "--agent", agent, "--output", "json"))
                for agent in ("trip-planner", "booking")}
    assert statuses["trip-planner"]["tenant_id"] != statuses["booking"]["tenant_id"]
    before = {agent: yaml.safe_load((HOME / "agents" / agent / "sidecar-config.yaml").read_text())
              for agent in statuses}
    booking_test = yaml.safe_load((CONFIG / "booking.yaml").read_text())
    booking_test["destinations"] = {"test_vantis": {"url": "https://trip-planner:9443/v1/agent/receive",
        "audience_pattern": statuses["trip-planner"]["workload_spiffe_id"], "valid_for": "+5m", "timeout_ms": 10000}}
    test_file = CONFIG / "booking-test.yaml"
    test_file.write_text(yaml.safe_dump(booking_test))
    try:
        run("aac", "init", "--profile", "tourfedia", "--agent", "booking", "--agent-config", str(test_file))
        run("env", "AAC_DEMO_TEST_MODE=1", "./demo", "up")
        record = json_rows(run("./demo", "run", "local-widening"))[-1]
        assert record["local_refusal"]["failure_code"] == "ERR_CHAIN_INVALID"
    finally:
        run("aac", "init", "--profile", "tourfedia", "--agent", "booking", "--agent-config", str(CONFIG / "booking.yaml"))
        run("./demo", "up")
    for profile, agent in (("vantis", "trip-planner"), ("tourfedia", "booking")):
        run("aac", "init", "--profile", profile, "--agent", agent)
        assert yaml.safe_load((HOME / "agents" / agent / "sidecar-config.yaml").read_text()) == before[agent]
    run("./demo", "up")
    run("./demo", "run")
    run("./demo", "check")
    for agent, peer, peer_profile in (("booking", "trip-planner", "vantis"), ("trip-planner", "booking", "tourfedia")):
        for ca in (False, True):
            run("./demo", "compose", agent, "stop", "sidecar", "agent")
            run("aac", "agent", "renew", "--agent", agent, *(["--ca"] if ca else []))
            if ca:
                run("./demo", "compose", agent, "up", "-d", "--force-recreate", "publisher")
                run("aac", "init", "--profile", peer_profile, "--agent", peer,
                    "--agent-config", str(CONFIG / (peer + ".yaml")))
            for name in statuses:
                assert yaml.safe_load((HOME / "agents" / name / "sidecar-config.yaml").read_text()) == before[name]
            run("./demo", "up")
            run("./demo", "run")
            run("./demo", "check")
