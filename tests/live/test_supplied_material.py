"""Supplied-material acceptance reuses booking's registered workload identity.

The original CLI-issued booking files act as the TEST issuer. A second local
CLI slot imports them via supported supplied-certificate flags; it has no CA
private key. The two slots never run simultaneously and are not two agents in
the business story. No test code generates or hand-copies private material.
"""
import json
import os
from pathlib import Path

import pytest
import yaml
from test_live_demo import CONFIG, HOME, run

pytestmark = pytest.mark.skipif(
    os.environ.get("AAC_DEMO_LIVE") != "1" or os.environ.get("AAC_DEMO_LIFECYCLE") != "1",
    reason="explicit live lifecycle opt-in required")


def material_flags():
    pki = HOME / "agents/booking/sidecar"
    return [argument for flag, filename in (
        ("--workload-cert-file", "workload.crt"), ("--workload-key-file", "workload.key"),
        ("--terminal-cert-file", "terminal.crt"), ("--terminal-key-file", "terminal.key"),
        ("--tls-cert-file", "server.crt"), ("--tls-key-file", "server.key"), ("--ca-cert-file", "ca.crt"))
        for argument in (flag, str(pki / filename))]


def test_supplied_certificate_replacement(monkeypatch):
    supplied = yaml.safe_load((CONFIG / "booking.yaml").read_text())
    supplied["agent_name"] = "book-supplied"
    supplied_file = CONFIG / "booking-supplied.yaml"
    supplied_file.write_text(yaml.safe_dump(supplied))
    original = json.loads(run("aac", "agent", "status", "--agent", "booking", "--output", "json"))
    run("./demo", "compose", "booking", "stop", "sidecar", "agent")
    run("aac", "init", "--profile", "tourfedia", "--agent", "book-supplied",
        "--agent-config", str(supplied_file), "--layout", "container",
        "--trust-url", "https://trust.stage.cascadeauth.dev", "--idp", "github", *material_flags())
    status = json.loads(run("aac", "agent", "status", "--agent", "book-supplied", "--output", "json"))
    assert status["workload_spiffe_id"] == original["workload_spiffe_id"]
    assert not (HOME / "agents/book-supplied/keep").exists()
    before = yaml.safe_load((HOME / "agents/book-supplied/sidecar-config.yaml").read_text())
    monkeypatch.setenv("AAC_TEST_BOOKING_AGENT", "book-supplied")
    try:
        run("./demo", "up")
        run("./demo", "run")
        run("./demo", "check")
        for ca in (False, True):
            run("./demo", "compose", "booking", "stop", "sidecar", "agent")
            # CLI-issued TEST issuer; production issuer/private CA stays elsewhere.
            run("aac", "agent", "renew", "--agent", "booking", *(["--ca"] if ca else []))
            run("aac", "agent", "renew", "--agent", "book-supplied", *material_flags())
            assert yaml.safe_load((HOME / "agents/book-supplied/sidecar-config.yaml").read_text()) == before
            assert not (HOME / "agents/book-supplied/keep").exists()
            if ca:
                run("./demo", "compose", "booking", "up", "-d", "--force-recreate", "publisher")
                run("aac", "init", "--profile", "vantis", "--agent", "trip-planner",
                    "--agent-config", str(CONFIG / "trip-planner.yaml"))
            run("./demo", "up")
            run("./demo", "run")
            run("./demo", "check")
    finally:
        run("./demo", "compose", "booking", "stop", "sidecar", "agent")
        monkeypatch.delenv("AAC_TEST_BOOKING_AGENT")
        run("./demo", "up")
