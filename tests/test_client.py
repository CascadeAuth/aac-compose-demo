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
    monkeypatch.setenv("AAC_STARTER_CA_FILE", str(tmp_path / "ca.crt"))
    monkeypatch.setenv("AAC_STARTER_EVIDENCE_FILE", str(tmp_path / "telemetry.jsonl"))
    monkeypatch.syspath_prepend(str(AGENT_DIR))
    sys.modules.pop("client", None)
    module = importlib.import_module("client")
    monkeypatch.setattr(module.ssl, "create_default_context", lambda **_: None)  # no real TLS here
    yield module
    sys.modules.pop("client", None)


FORWARD = {"action": "forward", "destination": "self_receive", "payload": {"step": "settle"}}
REFUSE = {"action": "refuse", "reason": "The starter agent has no other business policy."}


class StandIn:
    """Answers like the sidecar and the agent, and writes the sidecar's records.

    ``agent_answer`` is the agent's first decision as the sidecar returns it;
    only a delivered ``forward`` goes on to the dispatch, receive and respond
    records, as with the real sidecar. ``delivery_status="failed"`` stands for
    a first answer the sidecar could not accept (HTTP 207).
    """

    def __init__(self, events_file: Path, agent_answer: dict = FORWARD, delivery_status: str = "delivered") -> None:
        self.events_file = events_file
        self.agent_answer = agent_answer
        self.delivery_status = delivery_status

    def record(self, **event) -> None:
        with self.events_file.open("a") as sink:
            sink.write(json.dumps({"root_token_id": ROOT_TOKEN_ID, "result": "success", **event}) + "\n")

    def post(self, url: str, **request) -> httpx.Response:
        if url.endswith("/v1/agent/mint-root"):
            assert request["json"]["class_of_action"] == "demo_verify"
            task = request["json"]["task_ref"]
            self.record(event_type="mint", caveat_predicates="action:dev_noop,valid_until:2000")
            if self.delivery_status == "delivered" and self.agent_answer["action"] == "forward":
                self.record(event_type="receive", presenter_spiffe_id=AGENT_SPIFFE_ID)
                self.record(event_type="respond", agent_decision_action="settle",
                            terminal_attestation="eyJhbGciOiJFZERTQSJ9.x.y")
                self.record(event_type="dispatch", agent_decision_action="forward", destination="self_receive",
                            caveat_predicates=f"action:dev_noop,task_ref:{task},valid_until:1900")
            answer = httpx.Response(207 if self.delivery_status == "failed" else 200, json={
                "root_token_id": ROOT_TOKEN_ID, "applied_predicates": {"action": "dev_noop", "valid_until": 2000},
                "agent_response": self.agent_answer, "delivery_status": self.delivery_status})
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


def exercise_lines(client_module, monkeypatch, capsys, stand_in: StandIn) -> list[str]:
    monkeypatch.setattr(client_module.httpx, "post", stand_in.post)
    client_module.exercise()
    return capsys.readouterr().out.splitlines()


def test_exercise_prints_each_hand_off_from_the_sidecar_records(client_module, monkeypatch, capsys, tmp_path):
    lines = exercise_lines(client_module, monkeypatch, capsys, StandIn(tmp_path / "telemetry.jsonl"))
    assert [line.split()[0] for line in lines] == ["mint", "agent", "dispatch", "receive", "respond", "a2a", "refused"]
    assert 'restricted to {"action": "dev_noop", "valid_until": 2000}' in lines[0]
    assert "(delivered)" in lines[1] and '"action": "forward"' in lines[1]
    assert "to self_receive" in lines[2] and ",task_ref:starter-" in lines[2]
    assert lines[3].endswith(AGENT_SPIFFE_ID)
    assert "decided settle" in lines[4] and "eyJhbGciOiJFZERTQSJ9" in lines[4]
    assert lines[5].endswith("self_a2a: dispatched")
    assert lines[6].endswith("HTTP 401")


@pytest.mark.parametrize("answer,status", [(REFUSE, "delivered"), ({"delivery_error": "ERR_INVALID_AGENT_DECISION: settle is not valid here"}, "failed")],
                         ids=["agent-refuses", "delivery-failed"])
def test_exercise_shows_only_what_happened_when_nothing_is_forwarded(client_module, monkeypatch, capsys, tmp_path,
                                                                     answer, status):
    lines = exercise_lines(client_module, monkeypatch, capsys, StandIn(tmp_path / "telemetry.jsonl", answer, status))
    assert [line.split()[0] for line in lines] == ["mint", "agent", "a2a", "refused"]
    assert f"({status})" in lines[1] and json.dumps(answer) in lines[1]
    assert not any("verified" in line or "signed" in line for line in lines)


def test_wait_returns_once_the_sidecar_is_ready(client_module, monkeypatch, capsys):
    answers = iter([503, 503, 200])
    monkeypatch.setattr(client_module.httpx, "get", lambda url: httpx.Response(next(answers)))
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: None)
    client_module.wait_until_ready()
    assert capsys.readouterr().out.strip() == "The sidecar is ready."
