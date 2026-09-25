"""The live fixture consumes the public action format and real root joins."""
import importlib.util
from types import SimpleNamespace

import pytest

from conftest import REPO


@pytest.mark.parametrize("mismatch", [None, "token", "root", "task"])
def test_receiver_controls_join_public_actions_through_sidecar_evidence(monkeypatch, mismatch):
    monkeypatch.setenv("AAC_TEST_VANTIS", "{}")
    monkeypatch.setenv("AAC_TEST_TOURFEDIA", "{}")
    monkeypatch.syspath_prepend(str(REPO / "tests/fixtures"))
    spec = importlib.util.spec_from_file_location("adversarial_fixture", REPO / "tests/fixtures/run.py")
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    root, token_id = "a" * 64, "b" * 64
    monkeypatch.setattr(fixture, "chain", lambda *args: ("signed-test-chain", root))
    monkeypatch.setattr(fixture, "proof", lambda *args: "signed-test-proof")
    records = {}
    monkeypatch.setattr(fixture, "rows", lambda tenant, filename: list(records.get((tenant, filename), [])))
    calls = []

    def post(target, *, headers, json):
        case = len(calls)
        calls.append(target)
        if case in (1, 3):
            code = "ERR_CHAIN_INVALID" if case == 1 else "ERR_PRESENTER_NOT_PREVIOUS_HOLDER"
            body = {"error": {"code": code, "message": "8000 to 9500"}}
            return SimpleNamespace(status_code=403, text="", json=lambda: body)
        tenant = "vantis" if case == 0 else "tourfedia"
        task = headers["X-AAC-Task-Ref"]
        action = {
            "timestamp_unix_seconds": 1790330000, "event_type": "action_taken",
            "tenant_id": "tnt-11111111-1111-4111-8111-111111111111", "tenant_short": tenant,
            "token_id": "c" * 64 if mismatch == "token" else token_id,
            "actor_spiffe_id": "spiffe://tenant.example/agent", "action_summary": "test control",
            "action_payload": {"task_ref": "another-task" if mismatch == "task" else task},
        }
        assert len(action) == 8 and "root_token_id" not in action
        records.setdefault((tenant, "actions.jsonl"), []).append(action)
        records.setdefault((tenant, "telemetry.jsonl"), []).append({
            "event_type": "receive", "root_token_id": "d" * 64 if mismatch == "root" else root,
            "token_id": token_id,
        })
        body = {"chain_verification": "PASSED", "status": "refused" if case == 0 else "settled"}
        return SimpleNamespace(status_code=200, text="", json=lambda: body)

    monkeypatch.setattr(fixture, "post", post)
    if mismatch:
        with pytest.raises(AssertionError):
            fixture.receiver_checks()
    else:
        report = fixture.receiver_checks()
        assert [row["application_invocations"] for row in report] == [1, 0, 1, 0]
