import importlib.machinery
import importlib.util
import json
from types import SimpleNamespace

from conftest import REPO


def test_launcher_uses_supported_outputs_and_separate_projects(synthetic_home, monkeypatch):
    monkeypatch.setenv("AAC_CLI_HOME", str(synthetic_home))
    loader = importlib.machinery.SourceFileLoader("demo", str(REPO / "demo"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    calls = []
    monkeypatch.setattr(module.subprocess, "run", lambda argv, **kwargs: (calls.append((argv, kwargs)), SimpleNamespace(stdout=None))[1])
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


def test_run_prints_exact_input_paths_and_saves_mint(synthetic_home, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AAC_CLI_HOME", str(synthetic_home))
    loader = importlib.machinery.SourceFileLoader("demo_capture", str(REPO / "demo"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec); loader.exec_module(module)
    monkeypatch.setattr(module, "REPO", tmp_path)
    started = {"root_token_id": "a" * 64, "task_ref": "attempt-1", "delivery_status": "delivered"}
    monkeypatch.setattr(module, "compose", lambda *a, **k: json.dumps({"mint": started}) + "\n")
    monkeypatch.setattr(module.sys, "argv", ["demo", "run", "reservation"])
    module.main()
    assert json.loads((tmp_path / ".runs/attempt-1.mint.json").read_text()) == started
    output = capsys.readouterr().out
    assert "aeg render --mint-response" in output
    assert str(synthetic_home / "agents/trip-planner/state/telemetry.jsonl") in output
    assert str(synthetic_home / "agents/booking/state/actions.jsonl") in output
    assert "AEG input mapping:" in output
