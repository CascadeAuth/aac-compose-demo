"""Acceptance never treats a successful HTTP acknowledgement as completion."""
import base64
import copy
import json
import time

import pytest


def evidence(module):
    task = "po4143-test"
    common = {"root_token_id": "a"*64, "task_ref": task, "token_id": "b"*64}
    signer = "spiffe://tourfedia.test/booking"
    result = {**module.ORDER, "reservation_id": "synthetic-" + task, "amount": 8000,
              "currency": "USD", "payment_status": "unpaid", "synthetic": True}
    decision = {"action": "settle", "settlement_id": result["reservation_id"], "action_summary": json.dumps(result)}
    claims = {**common, "terminal_agent_svid": signer, **decision}
    part = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return [
        {"root_token_id": common["root_token_id"], "task_ref": task, "expires_at_unix_seconds": int(time.time())+7200},
        {**common, "result": "success", "caveat_audience": signer, "terminal_attestation_verification": "verified",
         "caveat_predicates": f"amount_max:8000,originator_reference:PO #4143,task_ref:{task},valid_until:{int(time.time())+1800}"},
        {**common, "actor_spiffe_id": signer},
        {**common, "result": "success", "agent_decision_action": "settle", "terminal_attestation": "fixture."+part+".fixture"},
        {**common, "payload": {"offer": 8000}, "decision": decision},
        signer,
    ]


def test_correlated_result(client_module):
    assert client_module.verify_result(*evidence(client_module))["payment_status"] == "unpaid"


@pytest.mark.parametrize("index,key,value", [
    (1, "terminal_attestation_verification", "signature_invalid"),
    (1, "terminal_attestation_verification", "absent"),
    (2, "root_token_id", "wrong"),
    (3, "token_id", "wrong"),
    (4, "task_ref", "wrong"),
    (2, "actor_spiffe_id", "spiffe://wrong.test/booking"),
])
def test_ack_or_mismatched_evidence_is_not_success(client_module, index, key, value):
    args = copy.deepcopy(evidence(client_module))
    args[index][key] = value
    with pytest.raises(AssertionError):
        client_module.verify_result(*args)


def test_signed_receipt_wrong_order_is_rejected(client_module):
    args = evidence(client_module)
    summary = json.loads(args[4]["decision"]["action_summary"])
    summary["order"] = "PO #9999"
    args[4]["decision"]["action_summary"] = json.dumps(summary)
    with pytest.raises(AssertionError):
        client_module.verify_result(*args)


def test_initial_request_uses_dynamic_budget_and_no_expiry(client_module):
    request = client_module.start_body("fresh-authority", "po-test")
    predicates = {p["predicate"]: p["value"] for p in request["obligations"]}
    assert predicates == {"amount_max": "10000", "originator_reference": "PO #4143", "task_ref": "po-test"}
    assert request["payload"]["offer"] == 9500
    assert request["payload"]["departure"] == "12 May"


def test_waits_for_completion_and_fails_without_dispatch(client_module, monkeypatch):
    monkeypatch.setattr(client_module, "start_task", lambda *_: {
        "root_token_id": "a"*64, "task_ref": "test", "delivery_status": "delivered", "expires_at_unix_seconds": int(time.time())+7200,
        "agent_response": {"action": "forward"}, "applied_predicates": {"amount_max": 10000, "originator_reference": "PO #4143"}})
    monkeypatch.setattr(client_module, "matching", lambda *_: [])
    ticks = iter([0, 1, 31])
    monkeypatch.setattr(client_module.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(client_module.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="No correlated completion"):
        client_module.run()
