"""Business policy and the actual pairing middleware."""
import importlib
import json
import sys

import pytest
from aac_invoke_auth import sign_invoke_request
from fastapi.testclient import TestClient
from conftest import AGENT_DIR

SECRET = b"synthetic-pairing-secret-0000000000"


@pytest.fixture
def module(tmp_path, monkeypatch):
    secret = tmp_path / "pairing.secret"
    secret.write_bytes(SECRET)
    monkeypatch.setenv("AAC_INVOKE_AUTH_SECRET_FILE", str(secret))
    monkeypatch.setenv("AAC_DEMO_ROLE", "booking")
    monkeypatch.setenv("AAC_DEMO_ACTIONS", str(tmp_path / "actions.jsonl"))
    monkeypatch.syspath_prepend(str(AGENT_DIR))
    sys.modules.pop("agent", None)
    return importlib.import_module("agent")


def body(module, **extra):
    return {"task_ref": "po4143-test", "current_arrival": {"payload": {**module.ORDER, "offer": 8000, **extra}}}


@pytest.mark.parametrize("mode", ["absent", "wrong-pair", "altered"])
def test_unauthenticated_callback_never_invokes_application(module, mode, tmp_path):
    raw = json.dumps(body(module)).encode()
    headers = {"Content-Type": "application/json"}
    if mode != "absent":
        headers.update(sign_invoke_request(secret=SECRET if mode == "altered" else b"wrong",
                                           method="POST", path="/invoke", headers=headers, body=raw))
    if mode == "altered":
        raw += b" "
    with TestClient(module.app) as client:
        assert client.post("/invoke", headers=headers, content=raw).status_code == 401
    assert not (tmp_path / "actions.jsonl").exists()


def test_narrowing_and_terminal_unpaid_reservation(module):
    request = body(module)
    forward = module.decide("trip-planner", request)
    assert forward["destination"] == "tourfedia"
    assert forward["additional_predicates"]["amount_max"] == 8000
    assert "valid_until" not in forward["additional_predicates"]
    settled = module.decide("booking", request)
    result = json.loads(settled["action_summary"])
    assert settled["action"] == "settle" and result["payment_status"] == "unpaid"
    assert result["synthetic"] and result["amount"] == 8000
    assert result["reservation_id"] == settled["settlement_id"]


def test_changed_fare_is_business_refusal_and_fresh_authority_can_book(module):
    assert module.decide("booking", body(module, scenario="fare-change"))["action"] == "refuse"
    result = module.decide("booking", body(module, scenario="fresh-authority", offer=9500))
    assert json.loads(result["action_summary"])["amount"] == 9500


def test_reverse_route_requires_explicit_test_mode(module):
    request = body(module, scenario="local-widening")
    assert module.decide("booking", request)["action"] == "refuse"
    decision = module.decide("booking", request, test_mode=True)
    assert decision["destination"] == "test_vantis"
    assert decision["additional_predicates"] == {"amount_max": 9500}


def test_application_checks_order_context(module):
    assert module.decide("booking", body(module, order="PO #9999"))["action"] == "refuse"


def test_callback_records_authenticated_root_and_token(module, tmp_path):
    raw = json.dumps(body(module)).encode()
    headers = {"Content-Type": "application/json", "X-AAC-Root-Token-Id": "a"*64,
               "X-AAC-Presenter-Token-Id": "b"*64}
    headers.update(sign_invoke_request(secret=SECRET, method="POST", path="/invoke", headers=headers, body=raw))
    with TestClient(module.app) as client:
        assert client.post("/invoke", headers=headers, content=raw).status_code == 200
    record = json.loads((tmp_path / "actions.jsonl").read_text())
    assert record["root_token_id"] == "a"*64 and record["token_id"] == "b"*64
    assert record["decision"]["action"] == "settle"
