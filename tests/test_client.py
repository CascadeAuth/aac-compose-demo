"""The example client against transports that stand in for the sidecar and agent."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import httpx
import pytest
from aac_invoke_auth import verify_invoke_request

from conftest import AGENT_DIR

SECRET = b"synthetic-starter-pairing-secret-0000"


@pytest.fixture
def client_module():
    sys.path.insert(0, str(AGENT_DIR))
    sys.modules.pop("client", None)
    try:
        yield importlib.import_module("client")
    finally:
        sys.modules.pop("client", None)
        sys.path.remove(str(AGENT_DIR))


class FakeSidecar:
    """Answers mint-root and signed A2A dispatches; records what it saw."""

    def __init__(self, delivery_status: str = "delivered") -> None:
        self.delivery_status = delivery_status
        self.requests: list[tuple[str, dict]] = []
        self.a2a_responses: dict[str, bytes] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        self.requests.append((request.url.path, data))
        if request.url.path == "/v1/agent/mint-root":
            assert str(request.url).startswith("https://127.0.0.1:9443")
            return httpx.Response(200, json={"delivery_status": self.delivery_status, "root_token_id": "a" * 64})
        assert request.url.path == "/v1/agent/a2a/dispatch"
        verify_invoke_request(secret=SECRET, method="POST", path=request.url.path,
                              headers=request.headers, body=request.content)
        assert request.headers["X-AAC-Envelope-Schema"] == "aac.a2a.egress.v1"
        # Same dispatch id -> the retained bytes, exactly as the sidecar does.
        body = self.a2a_responses.setdefault(
            data["dispatch_id"],
            json.dumps({"jsonrpc": "2.0", "id": data["a2a_request"]["id"], "result": {"message": {}}}).encode())
        return httpx.Response(200, content=body, headers={"Content-Type": "application/json"})


def clients_for(sidecar: FakeSidecar):
    loopback = httpx.Client(transport=httpx.MockTransport(sidecar), base_url="http://127.0.0.1:8080")
    originator = httpx.Client(transport=httpx.MockTransport(sidecar), base_url="https://127.0.0.1:9443")
    return loopback, originator


def test_workflow_mints_then_dispatches_and_retries_identically(client_module):
    sidecar = FakeSidecar()
    loopback, originator = clients_for(sidecar)
    summary, envelope, response = client_module.run_workflow(loopback, SECRET, originator)
    paths = [path for path, _ in sidecar.requests]
    assert paths == ["/v1/agent/mint-root", "/v1/agent/a2a/dispatch", "/v1/agent/a2a/dispatch"]
    mint = sidecar.requests[0][1]
    assert mint["class_of_action"] == "demo_verify" and mint["payload"] == {"step": "forward"}
    assert sidecar.requests[1][1] == sidecar.requests[2][1]  # same envelope both times
    assert json.loads(envelope)["destination_profile"] == "self_a2a"
    assert summary["root_token_id"] == "a" * 64
    assert summary["a2a_retry"] == "same response bytes"
    assert set(summary["durations_ms"]) == {"mint_to_settle", "a2a", "a2a_retry"}
    assert response == sidecar.a2a_responses[summary["a2a_dispatch_id"]]


def test_workflow_stops_when_native_delivery_fails(client_module):
    loopback, originator = clients_for(FakeSidecar(delivery_status="failed"))
    with pytest.raises(RuntimeError, match="not delivered"):
        client_module.run_workflow(loopback, SECRET, originator)


def test_saved_dispatch_can_be_retried_after_a_restart(client_module, tmp_path: Path, monkeypatch):
    sidecar = FakeSidecar()
    loopback, originator = clients_for(sidecar)
    summary, envelope, response = client_module.run_workflow(loopback, SECRET, originator)
    saved = tmp_path / client_module.SAVED_DISPATCH
    saved.write_text(json.dumps({"envelope": envelope.decode(), "response": response.decode()}))

    secret_file = tmp_path / "pairing.secret"; secret_file.write_bytes(SECRET)
    ca_file = tmp_path / "ca.pem"; ca_file.write_bytes(_self_signed_ca())
    monkeypatch.setenv("AAC_INVOKE_AUTH_SECRET_FILE", str(secret_file))
    monkeypatch.setenv("AAC_STARTER_CA_FILE", str(ca_file))
    restarted = FakeSidecar(); restarted.a2a_responses = dict(sidecar.a2a_responses)
    monkeypatch.setattr(client_module, "clients", lambda *_: (*clients_for(restarted), SECRET))

    result = client_module.command_retry(str(tmp_path))
    assert result["a2a_dispatch_id"] == summary["a2a_dispatch_id"]
    assert result["retained_result"].startswith("same response bytes")

    restarted.a2a_responses[summary["a2a_dispatch_id"]] = b'{"jsonrpc":"2.0","id":"x","result":{"other":1}}'
    with pytest.raises(RuntimeError, match="different bytes"):
        client_module.command_retry(str(tmp_path))


def test_telemetry_correlation_finds_the_settlement(client_module, tmp_path: Path):
    sink = tmp_path / "telemetry.jsonl"
    root = "b" * 64
    sink.write_text("\n".join(json.dumps(e) for e in [
        {"event_type": "mint", "result": "success", "root_token_id": root},
        {"event_type": "receive", "result": "success", "root_token_id": root},
        {"event_type": "respond", "result": "success", "root_token_id": root, "terminal_attestation": "x.y.z"},
        {"event_type": "mint", "result": "success", "root_token_id": "c" * 64},
        "a JSON string, not an event",
    ]) + "\nnot json at all\n")
    evidence = client_module.correlate_telemetry(sink, root)
    assert evidence == {"events_for_root": ["mint:success", "receive:success", "respond:success"],
                        "terminal_attestation_present": True}
    with pytest.raises(RuntimeError, match="no successful respond event"):
        client_module.correlate_telemetry(sink, "d" * 64, timeout_seconds=0.3)


def test_cli_usage(client_module, capsys):
    assert client_module.main(["client.py", "bogus"]) == 2
    assert "usage" in capsys.readouterr().err


class FakeAgentAndSidecar:
    """Stands in for the agent's protected routes and the sidecar's mint/readyz endpoints."""

    def __init__(self, unknown_class_status: int = 404, unknown_class_code: str = "ERR_CLASS_OF_ACTION_NOT_FOUND",
                 ready_after: int = 0) -> None:
        self.unknown_class_status = unknown_class_status
        self.unknown_class_code = unknown_class_code
        self.ready_after = ready_after
        self.readyz_calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path in ("/invoke", "/a2a/v1"):
            try:
                verify_invoke_request(secret=SECRET, method="POST", path=request.url.path,
                                      headers=request.headers, body=request.content)
            except Exception:
                return httpx.Response(401, json={"detail": "unauthenticated"})
            return httpx.Response(200, json={"action": "refuse"})
        if request.url.path == "/v1/agent/mint-root":
            return httpx.Response(self.unknown_class_status, json={"error": {"code": self.unknown_class_code}})
        if request.url.path == "/readyz":
            self.readyz_calls += 1
            if self.readyz_calls <= self.ready_after:
                return httpx.Response(503, json={"ready": False})
            return httpx.Response(200, json={"replay_profile": "basic", "replay_backend": "memory"})
        raise AssertionError("unexpected path " + request.url.path)


def _install_fake_clients(client_module, fake, monkeypatch, tmp_path):
    secret_file = tmp_path / "pairing.secret"; secret_file.write_bytes(SECRET)
    ca_file = tmp_path / "ca.pem"; ca_file.write_bytes(_self_signed_ca())
    monkeypatch.setenv("AAC_INVOKE_AUTH_SECRET_FILE", str(secret_file))
    monkeypatch.setenv("AAC_STARTER_CA_FILE", str(ca_file))
    real_client = httpx.Client

    def fake_client(*args, **kwargs):  # every base_url the client uses is served by `fake`
        kwargs.pop("verify", None)
        return real_client(*args, transport=httpx.MockTransport(fake), **kwargs)

    monkeypatch.setattr(client_module.httpx, "Client", fake_client)


def test_probe_reports_the_refusals(client_module, monkeypatch, tmp_path):
    _install_fake_clients(client_module, FakeAgentAndSidecar(), monkeypatch, tmp_path)
    result = client_module.command_probe()
    assert "HTTP 401" in result["unsigned_and_wrongly_signed_calls"]
    assert "ERR_CLASS_OF_ACTION_NOT_FOUND" in result["unknown_class_of_action"]
    assert result["replay_profile"] == "basic"


@pytest.mark.parametrize("status,code", [(500, "ERR_INTERNAL"), (404, "ERR_SOMETHING_ELSE"), (200, None)])
def test_probe_fails_when_the_sidecar_answers_off_contract(client_module, monkeypatch, tmp_path, status, code):
    _install_fake_clients(client_module, FakeAgentAndSidecar(status, code), monkeypatch, tmp_path)
    with pytest.raises(SystemExit, match="probe failed"):
        client_module.command_probe()


def test_wait_polls_until_ready(client_module, monkeypatch, tmp_path):
    fake = FakeAgentAndSidecar(ready_after=2)
    _install_fake_clients(client_module, fake, monkeypatch, tmp_path)
    monkeypatch.setattr(client_module.time, "sleep", lambda _: None)
    result = client_module.command_wait(timeout_seconds=5)
    assert fake.readyz_calls == 3
    assert result["replay_profile"] == "basic"


def test_wait_gives_up(client_module, monkeypatch, tmp_path):
    _install_fake_clients(client_module, FakeAgentAndSidecar(ready_after=10**6), monkeypatch, tmp_path)
    monkeypatch.setattr(client_module.time, "sleep", lambda _: None)
    with pytest.raises(SystemExit, match="did not report ready"):
        client_module.command_wait(timeout_seconds=0.05)


def _self_signed_ca() -> bytes:
    import datetime as dt

    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.x509.oid import NameOID

    key = ed25519.Ed25519PrivateKey.generate()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test CA")])
    now = dt.datetime.now(dt.timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(now + dt.timedelta(days=1))
                   .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(key, None))
    return certificate.public_bytes(serialization.Encoding.PEM)
