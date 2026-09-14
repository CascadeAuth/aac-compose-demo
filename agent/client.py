"""The example client: drives one complete workflow through the sidecar.

It runs inside the agent's network namespace (``./starter exercise``), where
the sidecar's local APIs are reachable, and prints correlation identifiers,
outcomes and measured durations. It never prints a secret.

Modes:

* ``exercise`` — mint a root authority for a synthetic task; the sidecar
  invokes the agent, which forwards to itself with a narrower restriction,
  receives, and settles with a signed terminal attestation. Then send one
  unary A2A request through the sidecar and repeat it with the same dispatch
  id, which must return the retained result byte for byte. Finally correlate
  the local telemetry with the returned root token id.
* ``retry`` — resend the A2A dispatch saved by the last ``exercise``; the
  bytes must still match. Run it after a restart to see retained results
  survive the container.
* ``probe`` — prove the refusals: unsigned and wrongly signed calls to the
  agent's protected routes are rejected before any handler runs, and an
  unknown class of action is refused by the sidecar.
* ``wait`` — wait until the sidecar reports ready.
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

LOOPBACK = "http://127.0.0.1:8080"  # the sidecar's local API
EXTERNAL = "https://127.0.0.1:9443"  # the sidecar's TLS listener (originator entry)
AGENT = "http://127.0.0.1:8000"  # the sample agent
A2A_DISPATCH_PATH = "/v1/agent/a2a/dispatch"
ENVELOPE_SCHEMA = "aac.a2a.egress.v1"
SAVED_DISPATCH = "last-a2a-dispatch.json"


def millis(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def synthetic_originator() -> dict:
    # Explicitly synthetic: not a sign-in. A real originator takes these
    # fields from its authenticated application context.
    return {
        "iss": "https://synthetic.invalid",
        "sub": "starter-only",
        "auth_time_unix_seconds": int(time.time()),
    }


def mint(originator: httpx.Client, task: str) -> dict:
    response = originator.post(
        "/v1/agent/mint-root",
        json={
            "human_originator": synthetic_originator(),
            "class_of_action": "demo_verify",
            "task_ref": task,
            "payload": {"step": "forward"},
        },
    )
    response.raise_for_status()
    minted = response.json()
    if minted.get("delivery_status") != "delivered":
        raise RuntimeError("native workflow was not delivered: " + json.dumps(minted))
    return minted


def a2a_envelope(task: str, destination_profile: str) -> dict:
    return {
        "schema_version": ENVELOPE_SCHEMA,
        "dispatch_id": str(uuid.uuid4()),
        "destination_profile": destination_profile,
        "task_ref": task + "-a2a",
        "authority": {
            "mode": "originate",
            "class_of_action": "demo_verify",
            "human_originator": synthetic_originator(),
        },
        "additional_predicates": {},
        "a2a_request": {
            "jsonrpc": "2.0",
            "id": task,
            "method": "SendMessage",
            "params": {
                "message": {
                    "messageId": str(uuid.uuid4()),
                    "role": "ROLE_USER",
                    "parts": [{"text": "Synthetic hello"}],
                }
            },
        },
    }


def send_a2a(client: httpx.Client, secret: bytes, body: bytes) -> httpx.Response:
    """One signed dispatch of exactly these envelope bytes."""
    headers = {"Content-Type": "application/json", "X-AAC-Envelope-Schema": ENVELOPE_SCHEMA}
    headers.update(
        sign_invoke_request(
            secret=secret, method="POST", path=A2A_DISPATCH_PATH, headers=headers, body=body
        )
    )
    response = client.post(A2A_DISPATCH_PATH, headers=headers, content=body)
    response.raise_for_status()
    if "error" in response.json():
        raise RuntimeError("A2A returned a protocol error: " + response.text)
    return response


def run_workflow(client: httpx.Client, secret: bytes, originator: httpx.Client,
                 destination_profile: str = "self_a2a") -> tuple[dict, bytes, bytes]:
    """The native mint/delegate/receive/settle flow, then an A2A call and its retry.

    Returns the summary, the envelope bytes and the response bytes so the
    caller can save them for a later retry.
    """
    task = "starter-" + str(uuid.uuid4())
    started = time.monotonic()
    minted = mint(originator, task)
    mint_ms = millis(started)

    envelope = a2a_envelope(task, destination_profile)
    body = json.dumps(envelope, separators=(",", ":")).encode()
    started = time.monotonic()
    first = send_a2a(client, secret, body)
    a2a_ms = millis(started)
    started = time.monotonic()
    retry = send_a2a(client, secret, body)  # same dispatch id AND same bytes
    retry_ms = millis(started)
    if retry.content != first.content:
        raise RuntimeError("identical A2A retry returned different bytes")

    summary = {
        "task_ref": task,
        "root_token_id": minted["root_token_id"],
        "native_delivery": minted["delivery_status"],
        "a2a_dispatch_id": envelope["dispatch_id"],
        "a2a_retry": "same response bytes",
        "durations_ms": {"mint_to_settle": mint_ms, "a2a": a2a_ms, "a2a_retry": retry_ms},
    }
    return summary, body, first.content


def correlate_telemetry(path: Path, root_token_id: str, timeout_seconds: float = 15) -> dict:
    """Find the local evidence for this root: the settle event with its attestation."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        events = []
        if path.exists():
            for line in path.read_text().splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict) and event.get("root_token_id") == root_token_id:
                    events.append(event)
        settled = [e for e in events if e.get("event_type") == "respond" and e.get("result") == "success"]
        if settled:
            return {
                "events_for_root": [e["event_type"] + ":" + e.get("result", "?") for e in events],
                "terminal_attestation_present": bool(settled[0].get("terminal_attestation")),
            }
        if time.monotonic() > deadline:
            raise RuntimeError(
                "no successful respond event for root " + root_token_id + " in " + str(path)
            )
        time.sleep(0.2)


def clients(secret_file: str, ca_file: str):
    ssl_context = ssl.create_default_context(cafile=ca_file)
    secret = Path(secret_file).read_bytes().strip()
    client = httpx.Client(base_url=LOOPBACK, timeout=65, trust_env=False)
    originator = httpx.Client(base_url=EXTERNAL, verify=ssl_context, timeout=65, trust_env=False)
    return client, originator, secret


def command_exercise(exercise_dir: str | None, telemetry_file: str | None) -> dict:
    client, originator, secret = clients(
        os.environ["AAC_INVOKE_AUTH_SECRET_FILE"], os.environ["AAC_STARTER_CA_FILE"]
    )
    with client, originator:
        summary, body, response = run_workflow(client, secret, originator)
    if telemetry_file:
        summary["local_evidence"] = correlate_telemetry(Path(telemetry_file), summary["root_token_id"])
    if exercise_dir:
        saved = Path(exercise_dir) / SAVED_DISPATCH
        saved.write_text(json.dumps({"envelope": body.decode(), "response": response.decode()}))
        summary["saved_dispatch"] = str(saved)
    return summary


def command_retry(exercise_dir: str) -> dict:
    saved = Path(exercise_dir) / SAVED_DISPATCH
    if not saved.exists():
        raise SystemExit("nothing to retry: run `./starter exercise` first")
    record = json.loads(saved.read_text())
    client, originator, secret = clients(
        os.environ["AAC_INVOKE_AUTH_SECRET_FILE"], os.environ["AAC_STARTER_CA_FILE"]
    )
    with client, originator:
        started = time.monotonic()
        response = send_a2a(client, secret, record["envelope"].encode())
        elapsed = millis(started)
    if response.content != record["response"].encode():
        raise RuntimeError("the retried dispatch returned different bytes than the saved result")
    envelope = json.loads(record["envelope"])
    return {
        "a2a_dispatch_id": envelope["dispatch_id"],
        "retained_result": "same response bytes as the saved run",
        "durations_ms": {"a2a_retry": elapsed},
    }


def expect_status(label: str, response: httpx.Response, wanted: int, failures: list) -> None:
    if response.status_code != wanted:
        failures.append(f"{label}: expected HTTP {wanted}, got {response.status_code}")


def command_probe() -> dict:
    client, originator, secret = clients(
        os.environ["AAC_INVOKE_AUTH_SECRET_FILE"], os.environ["AAC_STARTER_CA_FILE"]
    )
    failures: list = []
    with client, originator, httpx.Client(base_url=AGENT, timeout=10, trust_env=False) as agent:
        for path in ("/invoke", "/a2a/v1"):
            expect_status(f"unsigned POST {path}", agent.post(path, json={}), 401, failures)
            headers = {"Content-Type": "application/json"}
            body = b"{}"
            headers.update(sign_invoke_request(secret=b"not-the-pairing-secret", method="POST",
                                               path=path, headers=headers, body=body))
            expect_status(f"wrongly signed POST {path}", agent.post(path, headers=headers, content=body),
                          401, failures)
        unknown = originator.post("/v1/agent/mint-root", json={
            "human_originator": synthetic_originator(), "class_of_action": "not_configured",
            "task_ref": "starter-probe", "payload": {}})
        if unknown.status_code < 400:
            failures.append(f"unknown class of action: expected a refusal, got HTTP {unknown.status_code}")
        ready = client.get("/readyz")
        expect_status("GET /readyz", ready, 200, failures)
        readiness = ready.json() if ready.status_code == 200 else {}
    if failures:
        raise SystemExit("probe failed:\n  " + "\n  ".join(failures))
    return {
        "unsigned_and_wrongly_signed_calls": "refused with HTTP 401 before any handler ran",
        "unknown_class_of_action": "refused by the sidecar (HTTP " + str(unknown.status_code) + ")",
        "replay_profile": readiness.get("replay_profile"),
        "replay_backend": readiness.get("replay_backend"),
    }


def command_wait(timeout_seconds: float = 90) -> dict:
    deadline = time.monotonic() + timeout_seconds
    started = time.monotonic()
    with httpx.Client(base_url=LOOPBACK, timeout=5, trust_env=False) as client:
        while True:
            try:
                response = client.get("/readyz")
                if response.status_code == 200:
                    body = response.json()
                    return {"ready_after_ms": millis(started), "replay_profile": body.get("replay_profile")}
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise SystemExit("the sidecar did not report ready within " + str(timeout_seconds) + "s")
            time.sleep(0.5)


def main(argv: list) -> int:
    mode = argv[1] if len(argv) > 1 else "exercise"
    exercise_dir = os.environ.get("AAC_STARTER_EXERCISE_DIR")
    if mode == "exercise":
        result = command_exercise(exercise_dir, os.environ.get("AAC_STARTER_TELEMETRY_FILE"))
    elif mode == "retry":
        result = command_retry(exercise_dir or ".")
    elif mode == "probe":
        result = command_probe()
    elif mode == "wait":
        result = command_wait()
    else:
        print("usage: client.py exercise|retry|probe|wait", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
