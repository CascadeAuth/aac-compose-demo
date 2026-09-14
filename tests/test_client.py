"""The example client against a stand-in for the sidecar and the agent."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import httpx
import pytest
from aac_invoke_auth import verify_invoke_request

from conftest import AGENT_DIR

SECRET = b"synthetic-starter-pairing-secret-0000"
ROOT_TOKEN_ID = "a" * 64
AGENT_SPIFFE_ID = "spiffe://tnt-550e8400-e29b-41d4-9716-446655440000.tenants.stage.cascadeauth.dev/demo/agent"


@pytest.fixture
def client_module(tmp_path: Path, monkeypatch):
    """The client module, imported with its settings pointing at test files."""
    (tmp_path / "pairing.secret").write_bytes(SECRET)
    monkeypatch.setenv("AAC_INVOKE_AUTH_SECRET_FILE", str(tmp_path / "pairing.secret"))
    monkeypatch.setenv("AAC_STARTER_CA_FILE", str(tmp_path / "dev-ca.crt"))
    monkeypatch.setenv("AAC_STARTER_EVIDENCE_FILE", str(tmp_path / "telemetry.jsonl"))
    monkeypatch.syspath_prepend(str(AGENT_DIR))
    sys.modules.pop("client", None)
    module = importlib.import_module("client")
    monkeypatch.setattr(module.ssl, "create_default_context", lambda **_: None)  # no real TLS here
    yield module
    sys.modules.pop("client", None)


class StandIn:
    """Answers like the sidecar and the agent, and writes the sidecar's records."""

    def __init__(self, events_file: Path) -> None:
        self.events_file = events_file

    def record(self, **event) -> None:
        with self.events_file.open("a") as sink:
            sink.write(json.dumps({"root_token_id": ROOT_TOKEN_ID, "result": "success", **event}) + "\n")

    def post(self, url: str, **request) -> httpx.Response:
        if url.endswith("/v1/agent/mint-root"):
            assert request["json"]["class_of_action"] == "demo_verify"
            task = request["json"]["task_ref"]
            self.record(event_type="mint", caveat_predicates="action:dev_noop,valid_until:2000")
            self.record(event_type="receive", presenter_spiffe_id=AGENT_SPIFFE_ID)
            self.record(event_type="respond", agent_decision_action="settle",
                        terminal_attestation="eyJhbGciOiJFZERTQSJ9.x.y")
            self.record(event_type="dispatch", agent_decision_action="forward", destination="self_receive",
                        caveat_predicates=f"action:dev_noop,task_ref:{task},valid_until:1900")
            answer = httpx.Response(200, json={"delivery_status": "delivered", "root_token_id": ROOT_TOKEN_ID})
        elif url.endswith("/v1/agent/a2a/dispatch"):
            # The client must sign the request with the pairing secret, as the sidecar requires.
            verify_invoke_request(secret=SECRET, method="POST", path="/v1/agent/a2a/dispatch",
                                  headers=request["headers"], body=request["content"])
            dispatch_id = json.loads(request["content"])["dispatch_id"]
            answer = httpx.Response(200, json={"dispatch_id": dispatch_id, "status": "dispatched"})
        elif url.endswith("/invoke"):
            answer = httpx.Response(401, json={"detail": "unauthenticated"})  # no pairing signature
        else:
            raise AssertionError("unexpected call to " + url)
        answer.request = httpx.Request("POST", url)
        return answer


def test_exercise_prints_each_hand_off_from_the_sidecar_records(client_module, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(client_module.httpx, "post", StandIn(tmp_path / "telemetry.jsonl").post)
    client_module.exercise()
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[0] for line in lines] == ["task", "mint", "forward", "receive", "settle", "a2a", "refused"]
    assert lines[0].endswith(": delivered")
    assert "restricted to action:dev_noop,valid_until:2000" in lines[1]
    assert "decided forward" in lines[2] and "to self_receive" in lines[2] and ",task_ref:starter-" in lines[2]
    assert lines[3].endswith(AGENT_SPIFFE_ID)
    assert "decided settle" in lines[4] and "eyJhbGciOiJFZERTQSJ9" in lines[4]
    assert lines[5].endswith("self_a2a: dispatched")
    assert lines[6].endswith("HTTP 401")


def test_wait_returns_once_the_sidecar_is_ready(client_module, monkeypatch, capsys):
    answers = iter([503, 503, 200])
    monkeypatch.setattr(client_module.httpx, "get", lambda url: httpx.Response(next(answers)))
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: None)
    client_module.wait_until_ready()
    assert capsys.readouterr().out.strip() == "The sidecar is ready."
