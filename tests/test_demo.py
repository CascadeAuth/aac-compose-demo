import importlib.machinery
import importlib.util
import json
import subprocess
from types import SimpleNamespace

import pytest
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
    monkeypatch.setattr(module, "renew_expired", lambda agent: False)  # nothing expired in the synthetic home
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


def test_run_shows_the_client_rows_and_exit_code_when_the_scenario_fails(synthetic_home, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AAC_CLI_HOME", str(synthetic_home))
    loader = importlib.machinery.SourceFileLoader("demo_failure", str(REPO / "demo"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec); loader.exec_module(module)
    monkeypatch.setattr(module, "REPO", tmp_path)
    monkeypatch.setattr(module, "renew_expired", lambda agent: False)  # nothing expired in the synthetic home
    rows = (json.dumps({"mint": {"task_ref": "attempt-2"}}) + "\n"
            + json.dumps({"dispatch": {"terminal_attestation_verification": "workload_unresolved"}}) + "\n")

    def failing_client(*args, **kwargs):
        raise subprocess.CalledProcessError(3, ["docker", "compose"], output=rows)

    monkeypatch.setattr(module, "compose", failing_client)
    monkeypatch.setattr(module.sys, "argv", ["demo", "run", "reservation"])
    with pytest.raises(SystemExit) as stopped:
        module.main()
    assert stopped.value.code == 3
    assert capsys.readouterr().out == rows
    assert not (tmp_path / ".runs").exists()


def load_demo(name, synthetic_home, monkeypatch):
    """The demo script as a module, pointed at the synthetic CLI home."""
    monkeypatch.setenv("AAC_CLI_HOME", str(synthetic_home))
    loader = importlib.machinery.SourceFileLoader(name, str(REPO / "demo"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def status_document(**certificates):
    """The CLI's status report with the given certificate labels; unnamed ones are valid."""
    report = {}
    for label in ("dev_ca", "workload", "terminal", "tls_server"):
        report[label] = {"expired": False, "renew_now": False, **certificates.get(label, {})}
    return {"agent": "trip-planner", "certificates": report, "healthy": not any(r["expired"] for r in report.values())}


def stub_cli(module, monkeypatch, document):
    """Answer `aac agent status` with the document and record every other command."""
    calls = []

    def run(argv, **kwargs):
        calls.append(list(argv))
        if list(argv[:3]) == ["aac", "agent", "status"]:
            return SimpleNamespace(stdout=json.dumps(document), returncode=0 if document["healthy"] else 3)
        return SimpleNamespace(stdout="{}", returncode=0)

    monkeypatch.setattr(module.subprocess, "run", run)
    return calls


def test_renew_renews_only_expired_leaf_certificates(synthetic_home, monkeypatch, capsys):
    module = load_demo("demo_renew", synthetic_home, monkeypatch)
    calls = stub_cli(module, monkeypatch, status_document(workload={"expired": True}, tls_server={"expired": True}))
    assert module.renew_expired("booking") is True
    assert calls == [["aac", "agent", "status", "--agent", "booking", "--output", "json"],
                     ["aac", "agent", "renew", "--agent", "booking"]]
    assert capsys.readouterr().out == "booking: renewed its expired development certificates (workload, tls_server)\n"


def test_renew_leaves_valid_certificates_alone(synthetic_home, monkeypatch, capsys):
    module = load_demo("demo_renew_valid", synthetic_home, monkeypatch)
    calls = stub_cli(module, monkeypatch, status_document(workload={"renew_now": True}))
    assert module.renew_expired("trip-planner") is False
    assert [argv[2] for argv in calls] == ["status"]
    assert capsys.readouterr().out == ""


def test_renew_stops_at_the_ca_case_with_the_readme_commands(synthetic_home, monkeypatch):
    module = load_demo("demo_renew_ca", synthetic_home, monkeypatch)
    for dev_ca in ({"renew_now": True}, {"expired": True, "renew_now": True}):  # inside its window; already expired
        calls = stub_cli(module, monkeypatch, status_document(dev_ca=dev_ca, workload={"expired": True}))
        with pytest.raises(SystemExit) as stopped:
            module.renew_expired("booking")
        assert "aac agent renew --agent booking --ca" in str(stopped.value)
        assert "./demo compose booking up -d --force-recreate publisher" in str(stopped.value)
        assert [argv[2] for argv in calls] == ["status"]


def test_renew_leaves_certificates_your_own_issuer_signed_to_that_issuer(synthetic_home, monkeypatch, capsys):
    module = load_demo("demo_renew_supplied", synthetic_home, monkeypatch)
    document = status_document(workload={"expired": True, "renew_now": True})
    document["certificates"]["ca"] = document["certificates"].pop("dev_ca")  # the CLI's label for a supplied CA
    calls = stub_cli(module, monkeypatch, document)
    assert module.renew_expired("booking") is False
    assert [argv[2] for argv in calls] == ["status"]
    assert capsys.readouterr().out == ""


def test_renew_command_says_what_loads_the_renewed_certificates(synthetic_home, monkeypatch, capsys):
    module = load_demo("demo_renew_command", synthetic_home, monkeypatch)
    visited = []
    monkeypatch.setattr(module, "renew_expired", lambda agent: (visited.append(agent), agent == "trip-planner")[1])
    monkeypatch.setattr(module.sys, "argv", ["demo", "renew"])
    module.main()
    assert visited == ["trip-planner", "booking"]  # the second agent is renewed even after the first was
    assert capsys.readouterr().out == "Run ./demo up so the sidecars load the renewed certificates\n"
    monkeypatch.setattr(module, "renew_expired", lambda agent: False)
    module.main()
    assert capsys.readouterr().out == ""


def test_renew_passes_on_the_exit_code_when_the_cli_cannot_report(synthetic_home, monkeypatch):
    module = load_demo("demo_renew_no_report", synthetic_home, monkeypatch)
    monkeypatch.setattr(module.subprocess, "run", lambda argv, **kwargs: SimpleNamespace(stdout="", returncode=2))
    with pytest.raises(SystemExit) as stopped:
        module.renew_expired("trip-planner")
    assert stopped.value.code == 2


def test_renew_skips_an_agent_that_is_not_registered_yet(synthetic_home, tmp_path, monkeypatch):
    module = load_demo("demo_renew_first_run", synthetic_home, monkeypatch)
    calls = stub_cli(module, monkeypatch, status_document(workload={"expired": True}))
    monkeypatch.setattr(module, "CLI_HOME", tmp_path / "fresh-clone")
    assert module.renew_expired("trip-planner") is False
    assert calls == []


def test_run_recreates_a_renewed_pair_before_the_scenario(synthetic_home, tmp_path, monkeypatch, capsys):
    module = load_demo("demo_run_renewed", synthetic_home, monkeypatch)
    monkeypatch.setattr(module, "REPO", tmp_path)
    monkeypatch.setattr(module, "renew_expired", lambda agent: agent == "booking")
    started = {"root_token_id": "a" * 64, "task_ref": "attempt-3", "delivery_status": "delivered"}
    calls = []

    def compose(agent, *args, **kwargs):
        calls.append((agent, args))
        return json.dumps({"mint": started}) + "\n" if "client" in args and "wait" not in args else None

    monkeypatch.setattr(module, "compose", compose)
    monkeypatch.setattr(module.sys, "argv", ["demo", "run", "fare-change"])
    module.main()
    assert calls == [("booking", ("up", "--detach", "--no-build", "--force-recreate")),
                     ("booking", ("run", "--rm", "--no-deps", "client", "wait")),
                     ("trip-planner", ("run", "--rm", "--no-deps", "client", "fare-change"))]


def test_up_renews_before_it_recreates_the_containers(synthetic_home, monkeypatch, capsys):
    module = load_demo("demo_up_renews", synthetic_home, monkeypatch)
    order = []
    monkeypatch.setattr(module, "renew_expired", lambda agent: order.append(("renew", agent)))
    monkeypatch.setattr(module, "command", lambda *args, **kwargs: "aac-compose-demo\n" if args[1] == "network" else None)
    monkeypatch.setattr(module, "compose", lambda agent, *args, **kwargs: order.append((args[0], agent)))
    monkeypatch.setattr(module, "wait_for_publication", lambda agent: order.append(("wait", agent)))
    monkeypatch.setattr(module.sys, "argv", ["demo", "up"])
    module.main()
    assert order[:2] == [("renew", "trip-planner"), ("renew", "booking")]
    assert order[2:5] == [("build", "trip-planner"), ("up", "trip-planner"), ("up", "booking")]


def published(root_key, ca_anchor):
    return json.dumps({"remote": {"root_keys": {"contains_root_key_id": root_key},
                                  "spiffe_bundle": {"contains_ca_anchor_id": ca_anchor}}})


def test_wait_for_publication_retries_a_failed_status_check(synthetic_home, monkeypatch):
    module = load_demo("demo_wait_retry", synthetic_home, monkeypatch)
    answers = [SimpleNamespace(returncode=3, stdout="", stderr="agent needs attention\n"),
               SimpleNamespace(returncode=0, stdout=published(True, False), stderr=""),
               SimpleNamespace(returncode=3, stdout=published(True, True), stderr="")]  # published; needs attention
    monkeypatch.setattr(module.subprocess, "run", lambda argv, **kwargs: answers.pop(0))
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    module.wait_for_publication("booking")
    assert answers == []


def test_wait_for_publication_starts_no_check_after_the_deadline(synthetic_home, monkeypatch):
    module = load_demo("demo_wait_cutoff", synthetic_home, monkeypatch)
    checks = []
    monkeypatch.setattr(module.subprocess, "run", lambda argv, **kwargs:
                        (checks.append(argv), SimpleNamespace(returncode=0, stdout=published(True, False), stderr=""))[1])
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    clock = iter([0, 150, 300])  # the deadline is taken; the pause after the second check reaches it
    monkeypatch.setattr(module.time, "monotonic", lambda: next(clock))
    with pytest.raises(RuntimeError):
        module.wait_for_publication("booking")
    assert len(checks) == 2


def test_wait_for_publication_reports_the_last_error_at_the_deadline(synthetic_home, monkeypatch):
    module = load_demo("demo_wait_deadline", synthetic_home, monkeypatch)
    monkeypatch.setattr(module.subprocess, "run", lambda argv, **kwargs:
                        SimpleNamespace(returncode=3, stdout="", stderr="trust URL unreachable\n"))
    clock = iter([0, 301])  # the deadline is taken, then the first check is already past it
    monkeypatch.setattr(module.time, "monotonic", lambda: next(clock))
    with pytest.raises(RuntimeError) as failed:
        module.wait_for_publication("trip-planner")
    assert "Public keys not visible for trip-planner" in str(failed.value)
    assert "trust URL unreachable" in str(failed.value)
