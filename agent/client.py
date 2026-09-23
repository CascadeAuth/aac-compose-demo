"""The example client: starts one task through the AAC sidecar and shows what each piece did.

`./starter exercise` runs it inside the agent's network, where the sidecar's
local ports are. Every line it prints comes from what the sidecar returned or
wrote to its local record of events; read it next to "How it works" in the
README.
"""

import json
import os
import ssl
import sys
import time
import uuid
from pathlib import Path

import httpx
from aac_invoke_auth import sign_invoke_request

SIDECAR_TLS = "https://127.0.0.1:9443"  # where work starts: the sidecar's TLS listener
SIDECAR_API = "http://127.0.0.1:8080"  # the sidecar's local API, for its own agent
AGENT = "http://127.0.0.1:8000"  # the agent itself

PAIRING_SECRET = Path(os.environ["AAC_INVOKE_AUTH_SECRET_FILE"]).read_bytes().strip()
CA_FILE = os.environ["AAC_STARTER_CA_FILE"]  # issued the sidecar's TLS certificate
EVENTS = Path(os.environ["AAC_STARTER_EVIDENCE_FILE"])  # the sidecar's record, one JSON event per line


def show(step: str, text: str) -> None:
    print(f"{step:<8}  {text}")


def start_task(task: str) -> dict:
    """Ask the sidecar to start a task: it mints the root authority and calls your agent.

    The sidecar answers with the root authority, its restrictions and your
    agent's first decision. It carries out a `forward` after answering. The
    person the work is done for is synthetic here; a real application passes
    the signed-in user. The class of action names a policy in the sidecar's
    configuration, and the payload is what the agent will see.
    """
    path = "/v1/agent/mint-root"
    body = json.dumps({
        "human_originator": {"iss": "https://synthetic.invalid", "sub": "starter-only",
                             "auth_time_unix_seconds": int(time.time())},
        "class_of_action": "demo_verify", "task_ref": task,
        "payload": {"step": "forward"},
    }).encode()
    headers = {"Content-Type": "application/json"}
    headers.update(sign_invoke_request(secret=PAIRING_SECRET, method="POST", path=path,
                                       headers=headers, body=body))
    response = httpx.post(
        SIDECAR_TLS + path, headers=headers, content=body,
        verify=ssl.create_default_context(cafile=CA_FILE), timeout=60,
    )
    response.raise_for_status()
    return response.json()


def follow_forward(root_token_id: str) -> dict:
    """What the sidecar recorded while it carried out a forward, by event type.

    Its `dispatch` record is written once the forwarded step has been answered,
    so the client waits for that one.
    """
    events = {}
    for _ in range(30):
        events = {}
        for line in EVENTS.read_text().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue  # a line still being written
            if event.get("root_token_id") == root_token_id:
                events[event["event_type"]] = event
        if "dispatch" in events:
            break
        time.sleep(0.5)
    return events


def describe(event: dict) -> str:
    """One recorded event in words, with the fields that show what happened."""
    if event.get("result") != "success":
        return f"{event.get('result')}: {event.get('failure_code')} {event.get('failure_detail', '')}".rstrip()
    if event["event_type"] == "dispatch":
        return (f"the sidecar handed the next step to {event.get('destination')}, "
                f"restricted to {event.get('caveat_predicates')}")
    if event["event_type"] == "receive":
        return f"the sidecar verified that step as its receiver, presented by {event.get('presenter_spiffe_id')}"
    if event["event_type"] == "respond":
        decided = f"your agent decided {event.get('agent_decision_action')}"
        attestation = event.get("terminal_attestation")
        if attestation:
            return f"{decided}; the sidecar signed the terminal attestation {attestation[:20]}..."
        return decided
    return json.dumps(event)


def send_a2a_request(task: str) -> dict:
    """Your agent sends an agent-to-agent request through its sidecar.

    The agent signs the envelope with the pairing secret, as the sidecar signs
    its calls to the agent. The sidecar mints authority for the request, sends
    it to the destination `self_a2a` (this same agent, through the sidecar's
    A2A route) and answers with the dispatch status.
    """
    envelope = {
        "schema_version": "aac.a2a.egress.v1",
        "dispatch_id": str(uuid.uuid4()),
        "destination_profile": "self_a2a",
        "task_ref": task + "-a2a",
        "authority": {
            "mode": "originate",
            "class_of_action": "demo_verify",
            "human_originator": {"iss": "https://synthetic.invalid", "sub": "starter-only",
                                 "auth_time_unix_seconds": int(time.time())},
        },
        "additional_predicates": {},
        "a2a_request": {
            "jsonrpc": "2.0",
            "id": task,
            "method": "SendMessage",
            "params": {"message": {"messageId": str(uuid.uuid4()), "role": "ROLE_USER",
                                   "parts": [{"text": "Synthetic hello"}]}},
        },
    }
    path = "/v1/agent/a2a/dispatch"
    body = json.dumps(envelope).encode()
    headers = {"Content-Type": "application/json", "X-AAC-Envelope-Schema": "aac.a2a.egress.v1"}
    headers.update(sign_invoke_request(secret=PAIRING_SECRET, method="POST", path=path, headers=headers, body=body))
    response = httpx.post(SIDECAR_API + path, headers=headers, content=body, timeout=60)
    response.raise_for_status()
    return response.json()


def exercise() -> None:
    task = "starter-" + uuid.uuid4().hex[:8]
    started = start_task(task)
    show("mint", f"the sidecar minted root authority {started['root_token_id'][:12]}... for task {task}, "
                 f"restricted to {json.dumps(started['applied_predicates'], ensure_ascii=False)}")
    show("agent", f"the sidecar called your agent ({started['delivery_status']}); "
                  f"its answer: {json.dumps(started['agent_response'], ensure_ascii=False)}")
    if started["delivery_status"] == "delivered" and started["agent_response"].get("action") == "forward":
        events = follow_forward(started["root_token_id"])
        for event_type in ("dispatch", "receive", "respond"):  # the order in which they happen
            if event_type in events:
                show(event_type, describe(events[event_type]))
        if "dispatch" not in events:
            show("dispatch", "no record of the forwarded step after 15 s; see: docker logs aac-starter-sidecar-1")
    show("a2a", f"your agent's request went through the sidecar to self_a2a: {send_a2a_request(task)['status']}")
    refused = httpx.post(AGENT + "/invoke", json={})
    show("refused", f"a call to your agent without the pairing signature: HTTP {refused.status_code}")


def wait_until_ready() -> None:
    """For ./starter up: the sidecar answers /readyz once it has loaded its identity and configuration."""
    for _ in range(90):
        try:
            if httpx.get(SIDECAR_API + "/readyz").status_code == 200:
                print("The sidecar is ready.")
                return
        except httpx.HTTPError:
            pass  # not listening yet
        time.sleep(1)
    sys.exit("The sidecar is not ready after 90 s; see: docker logs aac-starter-sidecar-1")


if __name__ == "__main__":
    {"exercise": exercise, "wait": wait_until_ready}[sys.argv[1]]()
