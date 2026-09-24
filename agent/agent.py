"""The two business policies. Keys, tokens and proofs stay in the sidecars.

Marc's approval and Tourfedia's inventory are explicitly simulated.
"""
import json
import os
from pathlib import Path

from aac_invoke_auth.fastapi import InvokeAuthGuard, InvokeAuthMiddleware
from fastapi import FastAPI, Request

app = FastAPI()
app.add_middleware(InvokeAuthMiddleware, guard=InvokeAuthGuard.from_env(),
                   protected_paths=("/invoke",))
ORDER = {"order": "PO #4143", "from": "Austin", "to": "Shanghai", "departure": "12 May"}


def decide(role: str, body: dict, *, test_mode: bool = False) -> dict:
    payload = body["current_arrival"]["payload"]
    task = body["task_ref"]
    if any(payload.get(key) != value for key, value in ORDER.items()):
        return {"action": "refuse", "reason": "This demo handles only the simulated PO #4143 itinerary."}
    amount = payload.get("offer")
    if type(amount) is not int or amount not in (8000, 9500):
        return {"action": "refuse", "reason": "Unsupported synthetic offer."}
    scenario = payload.get("scenario", "reservation")
    if role == "trip-planner":
        if payload.get("test_return"):
            return {"action": "refuse", "reason": "Test receiver invoked; no business action."}
        return {"action": "forward", "destination": "tourfedia", "payload": payload,
                "additional_predicates": {"amount_max": amount, "originator_reference": ORDER["order"],
                                          "task_ref": task}}
    if role != "booking":
        raise ValueError("role must be trip-planner or booking")
    if scenario == "local-widening" and test_mode:
        return {"action": "forward", "destination": "test_vantis",
                "payload": {**payload, "test_return": True},
                "additional_predicates": {"amount_max": 9500}}
    if scenario not in ("reservation", "fare-change", "fresh-authority"):
        return {"action": "refuse", "reason": "Test scenarios are disabled in the normal booking application."}
    fare = 9500 if scenario == "fare-change" else amount
    if fare > amount:
        return {"action": "refuse", "reason": "Fare changed to $9,500; no reservation was created."}
    reservation = "synthetic-" + task
    result = {**ORDER, "reservation_id": reservation, "amount": fare,
              "currency": "USD", "payment_status": "unpaid", "synthetic": True}
    return {"action": "settle", "settlement_id": reservation,
            "action_summary": json.dumps(result, sort_keys=True)}


@app.post("/invoke")
async def invoke(request: Request) -> dict:
    body = await request.json()
    decision = decide(os.environ["AAC_DEMO_ROLE"], body,
                      test_mode=os.environ.get("AAC_DEMO_TEST_MODE") == "1")
    # Minimal business evidence joined to authenticated callback context.
    record = {"root_token_id": request.headers["x-aac-root-token-id"],
              "token_id": request.headers["x-aac-presenter-token-id"],
              "task_ref": body["task_ref"], "role": os.environ["AAC_DEMO_ROLE"],
              "payload": body["current_arrival"]["payload"], "decision": decision}
    with Path(os.environ["AAC_DEMO_ACTIONS"]).open("a") as output:
        output.write(json.dumps(record) + "\n")
    return decision
