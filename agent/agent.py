"""The sample agent: your workload, with the AAC sidecar running beside it.

The sidecar checks AAC authority before any work reaches this code. The two
share a pairing secret: the sidecar signs every call it makes here, and the
middleware below refuses a call without a valid signature before any handler
runs. The guard authenticates possession of the pair secret: the authorized
originator holding it can also sign callbacks inside this trusted boundary.

* ``POST /invoke``: the sidecar delivers a piece of work it has verified; the
  agent answers with a decision the sidecar then carries out: ``forward``
  (hand a narrower next step to a destination), ``settle`` (finish; the
  sidecar signs a terminal attestation) or ``refuse``.
* ``POST /a2a/v1``: the sidecar delivers an agent-to-agent request it has
  verified; the agent returns the reply.

Change ``decide`` to try your own policy; the route names are the ones the
sidecar calls.
"""

from aac_invoke_auth.fastapi import InvokeAuthGuard, InvokeAuthMiddleware
from fastapi import FastAPI, Request

app = FastAPI()
app.add_middleware(
    InvokeAuthMiddleware,
    guard=InvokeAuthGuard.from_env(),  # reads the pairing secret from AAC_INVOKE_AUTH_SECRET_FILE
    protected_paths=("/invoke", "/a2a/v1"),
)


def decide(body: dict) -> dict:
    """The sample business policy: a two-step task with no real-world effect.

    Step one forwards the task to ``self_receive``, a destination the sidecar
    configuration `aac init` wrote defines as this same agent, and narrows the
    authority to this one task. Step two settles it.
    """
    step = body["current_arrival"]["payload"].get("step")
    if step == "forward":
        return {
            "action": "forward",
            "destination": "self_receive",
            "payload": {"step": "settle"},
            "additional_predicates": {"task_ref": body["task_ref"]},  # narrower, never wider
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
