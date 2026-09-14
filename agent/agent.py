"""The sample agent: the workload the AAC sidecar runs beside.

The sidecar delivers verified work to this application over the shared
loopback interface. Two routes are protected by the pairing secret that both
processes read (the sidecar signs every call, the middleware here verifies
it); an unsigned or wrongly signed request never reaches a handler.

* ``POST /invoke`` receives a verified chain and answers with a decision:
  ``forward`` (delegate to a configured destination with narrower
  restrictions), ``settle`` (finish the task; the sidecar then signs the
  terminal attestation) or ``refuse``.
* ``POST /a2a/v1`` receives a verified unary A2A ``SendMessage`` request and
  returns the reply.
* ``GET /healthz`` is open and only says the process is up.

Replace ``decide`` with your own business policy after the first successful
run; keep the middleware and the route names, which the sidecar relies on.
"""

import os

from aac_invoke_auth.fastapi import InvokeAuthGuard, InvokeAuthMiddleware
from fastapi import FastAPI, Request

app = FastAPI()
app.add_middleware(
    InvokeAuthMiddleware,
    guard=InvokeAuthGuard.from_env(),  # reads AAC_INVOKE_AUTH_SECRET_FILE
    protected_paths=("/invoke", "/a2a/v1"),
)

# The destination named here must exist in the sidecar configuration. The
# configuration `aac init` renders defines `self_receive`: this same workload,
# which is how one agent demonstrates the whole delegate-and-settle flow.
FORWARD_DESTINATION = os.environ.get("AAC_STARTER_DESTINATION", "self_receive")


def decide(body: dict) -> dict:
    """The sample business policy: a two-step task with no real-world effect."""
    payload = body.get("current_arrival", {}).get("payload", {})
    step = payload.get("step") if isinstance(payload, dict) else None
    if step == "forward":
        return {
            "action": "forward",
            "destination": FORWARD_DESTINATION,
            "payload": {"step": "settle"},
            # Narrow, never widen: the delegated step is bound to this task.
            "additional_predicates": {"task_ref": body["task_ref"]},
        }
    if step == "settle":
        return {
            "action": "settle",
            "settlement_id": body["task_ref"],
            "action_summary": "Completed the synthetic starter task; no business effect.",
        }
    return {"action": "refuse", "reason": "The starter agent has no other business policy."}


@app.post("/invoke")
async def invoke(request: Request) -> dict:
    return decide(await request.json())


@app.post("/a2a/v1")
async def a2a(request: Request) -> dict:
    body = await request.json()
    message = body["params"]["message"]
    return {
        "jsonrpc": "2.0",
        "id": body["id"],
        "result": {
            "message": {
                "messageId": message["messageId"] + "-reply",
                "contextId": "starter-" + message["messageId"],
                "role": "ROLE_AGENT",
                "parts": [{"text": "Synthetic AAC-authorized reply"}],
            }
        },
    }


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
