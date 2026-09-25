"""Controlled adversarial checks; never run as either business application."""
import json
import os
import ssl
import time
import uuid
from pathlib import Path

import httpx
from aac_invoke_auth import sign_invoke_request

from wire import chain, proof

ORIGIN = json.loads(os.environ["AAC_TEST_VANTIS"])
BOOKING = json.loads(os.environ["AAC_TEST_TOURFEDIA"])
ORDER = {"order": "PO #4143", "from": "Austin", "to": "Shanghai", "departure": "12 May"}


def rows(tenant, filename):
    path = Path("/evidence") / tenant / filename
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def post(target, **kwargs):
    tenant = "vantis" if "trip-planner" in target else "tourfedia"
    return httpx.post(target, verify=ssl.create_default_context(cafile=f"/keys/{tenant}/ca.crt"),
                      timeout=30, **kwargs)


def starts():
    report = []
    for alias in ("delegations", "mint-root"):
        path = "/v1/agent/" + alias
        for mode in ("absent", "wrong-pair", "altered"):
            task = "negative-" + uuid.uuid4().hex
            before = rows("vantis", "telemetry.jsonl")
            actions = rows("vantis", "actions.jsonl")
            body = json.dumps({"human_originator": {"iss": "https://vantis.invalid/simulated",
                                "sub": "marc-sterling", "auth_time_unix_seconds": int(time.time())},
                               "class_of_action": "reserve_travel", "task_ref": task,
                               "obligations": [{"predicate": "amount_max", "value": "10000"}]}).encode()
            headers = {"Content-Type": "application/json"}
            if mode != "absent":
                tenant = "tourfedia" if mode == "wrong-pair" else "vantis"
                secret = Path(f"/pair/{tenant}/pairing.secret").read_bytes().strip()
                headers.update(sign_invoke_request(secret=secret, method="POST", path=path,
                                                   headers=headers, body=body))
            if mode == "altered":
                body += b" "
            response = post("https://trip-planner:9443" + path, content=body, headers=headers)
            assert response.status_code == 401, response.text
            assert rows("vantis", "actions.jsonl") == actions
            new_events = rows("vantis", "telemetry.jsonl")[len(before):]
            assert not any(e["event_type"] == "mint" and e["result"] == "success" for e in new_events)
            report.append({"case": mode, "alias": alias, "http_status": 401,
                           "response": response.json(), "successful_mints": 0, "application_invocations": 0})
    return report


def receiver_checks():
    report = []
    # Same identities, CA trust, wire constructor and TLS path for control/attack.
    for case, amount, signer, receiver, expected in (
        ("return-control", 7000, "tourfedia", "vantis", None),
        ("forced-widening", 9500, "tourfedia", "vantis", "ERR_CHAIN_INVALID"),
        ("presenter-control", None, "vantis", "tourfedia", None),
        ("wrong-presenter", None, "tourfedia", "tourfedia", "ERR_PRESENTER_NOT_PREVIOUS_HOLDER"),
    ):
        task = "fixture-" + uuid.uuid4().hex
        token, root = chain(ORIGIN, BOOKING, "/keys/vantis/root.pem", task, amount)
        target = "https://" + ("trip-planner" if receiver == "vantis" else "booking") + ":9443/v1/agent/receive"
        headers = {"Authorization": "AAC-Macaroon " + token, "X-AAC-Task-Ref": task,
                   "DPoP": proof(token, f"/keys/{signer}/workload.key", f"/keys/{signer}/workload.crt", target)}
        before = rows(receiver, "actions.jsonl")
        payload = {**ORDER, "offer": 8000, "scenario": "reservation"}
        if receiver == "vantis":
            payload["test_return"] = True
        response = post(target, headers=headers, json=payload)
        after = rows(receiver, "actions.jsonl")
        if expected:
            assert response.status_code == 403, response.text
            error = response.json()
            assert error["error"]["code"] == expected, error
            if case == "forced-widening":
                assert "8000 to 9500" in json.dumps(error), error
            assert after == before, "receiver invoked its business application"
        else:
            assert response.status_code == 200, response.text
            assert response.json()["chain_verification"] == "PASSED"
            assert len(after) == len(before) + 1
            action = after[-1]
            assert action["action_payload"]["task_ref"] == task
            # Application records identify tokens; sidecar evidence supplies roots.
            assert any(event.get("event_type") == "receive"
                       and event.get("root_token_id") == root
                       and event.get("token_id") == action["token_id"]
                       for event in rows(receiver, "telemetry.jsonl"))
            assert response.json()["status"] == ("refused" if receiver == "vantis" else "settled")
        report.append({"case": case, "root_token_id": root, "task_ref": task,
                       "http_status": response.status_code, "response": response.json(),
                       "application_invocations": len(after) - len(before)})
    return report


if __name__ == "__main__":
    print(json.dumps({"chain_start": starts(), "receiver": receiver_checks()}))
