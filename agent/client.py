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
DEV_CA = os.environ["AAC_STARTER_CA_FILE"]  # issued the sidecar's TLS certificate
EVENTS = Path(os.environ["AAC_STARTER_EVIDENCE_FILE"])  # the sidecar's record, one JSON event per line


def show(step: str, text: str) -> None:
    print(f"{step:<8}  {text}")


def start_task(task: str) -> dict:
    """Ask the sidecar to start a task. It mints the root authority and runs the whole flow.

    The person the work is done for is synthetic here; a real application
    passes the signed-in user. The class of action names a policy in the
    sidecar's configuration, and the payload is what the agent will see.
    """
    response = httpx.post(
        SIDECAR_TLS + "/v1/agent/mint-root",
        verify=ssl.create_default_context(cafile=DEV_CA),
        timeout=60,
        json={
            "human_originator": {"iss": "https://synthetic.invalid", "sub": "starter-only",
                                 "auth_time_unix_seconds": int(time.time())},
            "class_of_action": "demo_verify",
            "task_ref": task,
            "payload": {"step": "forward"},
        },
    )
    response.raise_for_status()
    return response.json()


def recorded_events(root_token_id: str) -> dict:
    """What the sidecar recorded for this task, by event type."""
    events = {}
    for _ in range(10):  # the sidecar can finish writing a moment after it answers
        for line in EVENTS.read_text().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue  # a line still being written
            if event.get("root_token_id") == root_token_id:
                events[event["event_type"]] = event
        if {"mint", "dispatch", "receive", "respond"} <= events.keys():
            break
        time.sleep(0.5)
    return events


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
    events = recorded_events(started["root_token_id"])
    mint, dispatch = events.get("mint", {}), events.get("dispatch", {})
    receive, respond = events.get("receive", {}), events.get("respond", {})

    show("task", f"{task}: {started['delivery_status']}")
    show("mint", f"the sidecar minted root authority {started['root_token_id'][:12]}... "
                 f"restricted to {mint.get('caveat_predicates')}")
    show("forward", f"your agent decided {dispatch.get('agent_decision_action')}; the sidecar handed the next step "
                    f"to {dispatch.get('destination')}, restricted to {dispatch.get('caveat_predicates')}")
    show("receive", f"the sidecar verified that step as its receiver, presented by {receive.get('presenter_spiffe_id')}")
    show("settle", f"your agent decided {respond.get('agent_decision_action')}; the sidecar signed the "
                   f"terminal attestation {respond.get('terminal_attestation', '')[:20]}...")
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
    sys.exit("The sidecar is not ready after 90 s; see: docker compose logs sidecar")


if __name__ == "__main__":
    {"exercise": exercise, "wait": wait_until_ready}[sys.argv[1]]()
