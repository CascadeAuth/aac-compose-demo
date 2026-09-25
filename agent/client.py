"""Vantis's authorized originator; wait for the actual asynchronous result.

The demo operator controls both local stacks and can read their evidence.
Only Vantis's pairing credential is mounted into this originating process.
"""
import base64
import json
import os
import ssl
import sys
import time
import uuid
from pathlib import Path

import httpx
from aac_invoke_auth import sign_invoke_request

ORDER = {"order": "PO #4143", "from": "Austin", "to": "Shanghai", "departure": "12 May"}
START_PATH = "/v1/agent/delegations"


def start_body(scenario: str, task: str) -> dict:
    amount = 9500 if scenario == "fresh-authority" else 8000
    # Initial amount has one source: this simulated application approval.
    # Class valid_for supplies +2h; the destination supplies +30m.
    return {"human_originator": {"iss": "https://vantis.invalid/simulated", "sub": "marc-sterling",
                                 "auth_time_unix_seconds": int(time.time())},
            "class_of_action": "reserve_travel", "task_ref": task,
            "obligations": [{"predicate": "amount_max", "value": "10000"},
                            {"predicate": "originator_reference", "value": ORDER["order"]},
                            {"predicate": "task_ref", "value": task}],
            "payload": {**ORDER, "offer": amount, "scenario": scenario}}


def start_task(scenario: str, task: str) -> dict:
    body = json.dumps(start_body(scenario, task)).encode()
    headers = {"Content-Type": "application/json"}
    headers.update(sign_invoke_request(secret=Path(os.environ["AAC_INVOKE_AUTH_SECRET_FILE"]).read_bytes().strip(),
                                       method="POST", path=START_PATH, headers=headers, body=body))
    response = httpx.post("https://127.0.0.1:9443" + START_PATH, headers=headers, content=body,
                          verify=ssl.create_default_context(cafile="/run/secrets/ca.crt"), timeout=60)
    response.raise_for_status()
    return response.json()


def records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text().splitlines()
    result = []
    for index, line in enumerate(lines):
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            if index != len(lines) - 1:
                raise
            # The last line may still be in flight; the next poll reads it again.
    return result


def matching(directory: Path, filename: str, root: str, task: str) -> list[dict]:
    if filename == "actions.jsonl":
        tokens = {row["token_id"] for row in records(directory / "telemetry.jsonl")
                  if row.get("root_token_id") == root and row.get("task_ref") == task and row.get("token_id")}
        return [row for row in records(directory / filename)
                if row.get("token_id") in tokens and row.get("action_payload", {}).get("task_ref") == task]
    return [row for row in records(directory / filename)
            if row.get("root_token_id") == root and row.get("task_ref") == task]


def verify_result(started: dict, dispatch: dict, received: dict, respond: dict,
                  action: dict, expected_signer: str) -> dict:
    """Require the sender's cryptographic verdict, then inspect business claims.

    Decoding below is not signature verification. The sender verified the ACK;
    the receiver's local receipt and records expose the correlated contents.
    """
    assert dispatch["result"] == "success", dispatch
    assert dispatch["terminal_attestation_verification"] == "verified", dispatch
    root, task = started["root_token_id"], started["task_ref"]
    for row in (dispatch, received, respond):
        assert row["root_token_id"] == root and row["task_ref"] == task, row
        assert row["token_id"] == dispatch["token_id"], row
    assert action["token_id"] == dispatch["token_id"] and action["action_payload"]["task_ref"] == task
    assert dispatch["caveat_audience"] == expected_signer
    assert received["actor_spiffe_id"] == expected_signer
    assert respond["result"] == "success" and respond["agent_decision_action"] == "settle"
    part = respond["terminal_attestation"].split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    assert claims["terminal_agent_svid"] == expected_signer
    assert claims["root_token_id"] == root and claims["task_ref"] == task
    decision = action["action_payload"]["agent_decision"]
    assert claims["settlement_id"] == decision["settlement_id"]
    assert claims["action_summary"] == decision["action_summary"]
    result = json.loads(claims["action_summary"])
    assert all(result[key] == value for key, value in ORDER.items())
    assert result["reservation_id"] == claims["settlement_id"] == "synthetic-" + task
    assert result["payment_status"] == "unpaid" and result["synthetic"] is True
    assert result["currency"] == "USD" and result["amount"] == action["action_payload"]["payload"]["offer"]
    limits = dict(part.split(":", 1) for part in dispatch["caveat_predicates"].split(","))
    assert int(limits["amount_max"]) == result["amount"]
    assert limits["originator_reference"] == ORDER["order"] and limits["task_ref"] == task
    assert int(limits["valid_until"]) <= started["expires_at_unix_seconds"]
    assert 0 < int(limits["valid_until"]) - time.time() <= 1800
    return result


def run(scenario: str = "reservation") -> dict:
    task = "po4143-" + uuid.uuid4().hex[:12]
    began = time.time()
    started = start_task(scenario, task)
    assert started["delivery_status"] == "delivered", started
    assert started["agent_response"]["action"] == "forward", started
    assert int(started["applied_predicates"]["amount_max"]) == 10000, started
    assert started["applied_predicates"]["originator_reference"] == ORDER["order"]
    assert began + 7199 <= started["expires_at_unix_seconds"] <= time.time() + 7200
    root = started["root_token_id"]
    print(json.dumps({"simulated_approval": "Marc Sterling: PO #4143, up to $10,000",
                      "mint": started}), flush=True)
    sender, receiver = Path("/evidence/vantis"), Path("/evidence/tourfedia")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        sent = matching(sender, "telemetry.jsonl", root, task)
        got = matching(receiver, "telemetry.jsonl", root, task)
        actions = matching(receiver, "actions.jsonl", root, task)
        dispatch = next((e for e in sent if e["event_type"] == "dispatch"), None)
        receive = next((e for e in got if e["event_type"] == "receive" and e["result"] == "success"), None)
        respond = next((e for e in got if e["event_type"] == "respond"), None)
        if scenario == "fare-change" and dispatch and actions:
            assert actions[0]["action_payload"]["agent_decision"] == {"action": "refuse", "reason": "Fare changed to $9,500; no reservation was created."}
            assert not respond
            result = {"application_decline": actions[0], "dispatch": dispatch}
            print(json.dumps(result), flush=True)
            return result
        if scenario == "local-widening":
            failure = next((e for e in got if e["event_type"] == "dispatch"), None)
            if failure:
                assert failure["result"] == "failure" and failure["failure_code"] == "ERR_CHAIN_INVALID", failure
                assert "candidate delegation refused" in failure["failure_detail"], failure
                assert not any(e["event_type"] == "receive" for e in sent)
                assert len(matching(sender, "actions.jsonl", root, task)) == 1
                assert actions[0]["action_payload"]["agent_decision"]["destination"] == "test_vantis"
                print(json.dumps({"local_refusal": failure}), flush=True)
                return failure
        elif dispatch and receive and respond and actions:
            result = verify_result(started, dispatch, receive, respond, actions[0], os.environ["AAC_DEMO_BOOKING_ID"])
            receipt = {"root_token_id": root, "task_ref": task, "reservation": result,
                       "terminal_attestation_verification": dispatch["terminal_attestation_verification"],
                       "dispatch": dispatch, "receive": receive, "respond": respond}
            print(json.dumps(receipt), flush=True)
            return receipt
        time.sleep(0.25)
    raise RuntimeError(f"No correlated completion after 30 seconds for {root}")


def wait_until_ready() -> None:
    for _ in range(90):
        try:
            if httpx.get("http://127.0.0.1:8080/readyz").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise RuntimeError("Sidecar not ready after 90 seconds; inspect ./demo compose <agent> logs sidecar")


if __name__ == "__main__":
    if sys.argv[1] == "wait":
        wait_until_ready()
    else:
        run(sys.argv[1])
