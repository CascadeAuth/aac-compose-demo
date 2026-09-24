import importlib.machinery
import importlib.util
import json

from conftest import REPO


def test_launcher_uses_supported_outputs_and_separate_projects(synthetic_home, monkeypatch):
    monkeypatch.setenv("AAC_CLI_HOME", str(synthetic_home))
    loader = importlib.machinery.SourceFileLoader("demo", str(REPO / "demo"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    calls = []
    monkeypatch.setattr(module.subprocess, "run", lambda argv, **kwargs: calls.append((argv, kwargs)))
    module.compose("trip-planner", "config")
    module.compose("booking", "config")
    assert calls[0][0][3] != calls[1][0][3]
    assert calls[0][1]["env"]["AAC_DEMO_ROLE"] == "trip-planner"
    assert calls[1][1]["env"]["AAC_DEMO_ROLE"] == "booking"
    assert calls[0][1]["env"]["AAC_DEMO_BOOKING_ID"].endswith("/booking")
    assert "record.json" not in (REPO / "demo").read_text()


def test_test_only_wire_and_proof_use_cli_issued_material(synthetic_home, monkeypatch):
    import base64
    from cryptography import x509
    monkeypatch.syspath_prepend(str(REPO / "tests" / "fixtures"))
    import wire
    origin_dir = synthetic_home / "agents" / "trip-planner"
    booking_dir = synthetic_home / "agents" / "booking"
    origin = json.loads((origin_dir / "public-status.json").read_text())
    booking = json.loads((booking_dir / "public-status.json").read_text())
    token, root = wire.chain(origin, booking, origin_dir / "sidecar/root.pem", "fixture", 9500)
    assert len(root) == 64
    target = "https://trip-planner:9443/v1/agent/receive"
    proof = wire.proof(token, booking_dir / "sidecar/workload.key", booking_dir / "sidecar/workload.crt", target)
    header, body, signature = proof.split(".")
    decode = lambda value: base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    cert = x509.load_der_x509_certificate(base64.b64decode(json.loads(decode(header))["x5c"][0]))
    cert.public_key().verify(decode(signature), (header + "." + body).encode())
    claims = json.loads(decode(body))
    assert claims["htu"] == target
    assert claims["ath"] == wire.b64(wire.hashlib.sha256(token.encode()).digest())
