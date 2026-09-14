"""The sample agent, exercised through FastAPI's test client with a known secret."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest
from aac_invoke_auth import sign_invoke_request
from fastapi.testclient import TestClient

from conftest import AGENT_DIR

SECRET = b"synthetic-starter-pairing-secret-0000"


@pytest.fixture
def agent_app(tmp_path: Path, monkeypatch):
    secret_file = tmp_path / "pairing.secret"
    secret_file.write_bytes(SECRET + b"\n")
    monkeypatch.setenv("AAC_INVOKE_AUTH_SECRET_FILE", str(secret_file))
    monkeypatch.setenv("AAC_INVOKE_AUTH_ALLOW_UNAUTHENTICATED", "false")
    monkeypatch.syspath_prepend(str(AGENT_DIR))
    sys.modules.pop("agent", None)
    module = importlib.import_module("agent")
    with TestClient(module.app) as client:
        yield client


def post(client: TestClient, path: str, value: dict, mode: str = "valid"):
    raw = json.dumps(value, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json", "X-AAC-Task-Ref": "starter-task"}
    if mode != "missing":
        secret = SECRET if mode != "wrong" else b"wrong"
        headers.update(sign_invoke_request(secret=secret, method="POST", path=path, headers=headers, body=raw))
    if mode == "tampered":
        raw += b" "
    return client.post(path, headers=headers, content=raw)


@pytest.mark.parametrize("path", ["/invoke", "/a2a/v1"])
@pytest.mark.parametrize("mode", ["missing", "wrong", "tampered"])
def test_protected_routes_refuse_unauthenticated_calls(agent_app, path, mode):
    assert post(agent_app, path, {}, mode).status_code == 401


def test_healthz_is_open(agent_app):
    assert agent_app.get("/healthz").json() == {"status": "ok"}


def test_decisions_forward_then_settle_and_refuse_anything_else(agent_app):
    forward = post(agent_app, "/invoke", {"task_ref": "starter-task", "current_arrival": {"payload": {"step": "forward"}}}).json()
    assert forward["action"] == "forward"
    assert forward["destination"] == "self_receive"
    assert forward["additional_predicates"] == {"task_ref": "starter-task"}
    assert forward["payload"] == {"step": "settle"}

    settle = post(agent_app, "/invoke", {"task_ref": "starter-task", "current_arrival": {"payload": {"step": "settle"}}}).json()
    assert settle["action"] == "settle"
    assert settle["settlement_id"] == "starter-task"

    other = post(agent_app, "/invoke", {"task_ref": "starter-task", "current_arrival": {"payload": {"step": "pay"}}}).json()
    assert other["action"] == "refuse"


def test_a2a_reply_shape(agent_app):
    request = {"jsonrpc": "2.0", "id": "request-1", "method": "SendMessage",
               "params": {"message": {"messageId": "message-1", "role": "ROLE_USER", "parts": [{"text": "hello"}]}}}
    assert post(agent_app, "/a2a/v1", request).json() == {
        "jsonrpc": "2.0", "id": "request-1",
        "result": {"message": {"messageId": "message-1-reply", "contextId": "starter-message-1",
                               "role": "ROLE_AGENT", "parts": [{"text": "Synthetic AAC-authorized reply"}]}}}


def test_missing_secret_fails_startup(monkeypatch):
    monkeypatch.setenv("AAC_INVOKE_AUTH_SECRET_FILE", "")
    monkeypatch.syspath_prepend(str(AGENT_DIR))
    sys.modules.pop("agent", None)
    from aac_invoke_auth.fastapi import InvokeAuthConfigurationError

    with pytest.raises(InvokeAuthConfigurationError):
        importlib.import_module("agent")
    sys.modules.pop("agent", None)
