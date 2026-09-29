"""Real demo app + exact sidecar process, using installed CLI-produced material.

Local fixture control-plane replies isolate this release contract from stage
accounts and browser sign-in. This is not a live provider/deployment acceptance.
"""
import base64
import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import time

import httpx
import pytest
import yaml
from aac_cli.cli import main
from aac_cli.config import SessionCredential, write_session_credential
from aac_cli import dev_material
from aac_invoke_auth import sign_invoke_request
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ROOT = Path(__file__).resolve().parents[2]
BINARY = os.environ.get("AAC_COMPAT_BINARY")
pytestmark = pytest.mark.skipif(not BINARY, reason="release consumer requires AAC_COMPAT_BINARY")


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait(predicate, processes, logs):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if any(p.poll() is not None for p in processes):
            pytest.fail("consumer process exited: " + "\n".join(p.read_text() for p in logs))
        try:
            if predicate(): return
        except (httpx.ConnectError, FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(.1)
    pytest.fail("consumer timed out: " + "\n".join(p.read_text() for p in logs))


def test_installed_cli_peer_configuration_and_verified_reservation(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("AAC_CLI_HOME", str(home))
    tenants = {}
    active = {}
    def post(url, **kwargs):
        body = kwargs["json"]
        if url.endswith("/v1/tenants"):
            tenant = active["tenant"]
            public = serialization.load_pem_public_key(body["tenant_admin_pubkey_pem"].encode())
            tenants[tenant] = dev_material.admin_key_id(public)
            domain = tenant + ".tenants.example.com"
            hosted = {"trust_domain": domain, "binding": {"trust_domain": domain,
                      "scope_tenant_id": tenant, "status": "ACTIVE", "binding_version": 1,
                      "binding_id": "00000000-0000-4000-8000-000000000246"}}
            request = kwargs["headers"]["Idempotency-Key"]
            return httpx.Response(201, headers={"Idempotency-Key": request}, json={
                "registration_request_id": request, "tenant_id": tenant,
                "api_key": "local-fixture-api-key", "key_id": "ak_0123456789abcdef",
                "hosted_trust_domain": hosted})
        if url.endswith("/workloads"):
            return httpx.Response(201, json={"tenant_id": active["tenant"], "workload_id": "wl_fixture",
                "spiffe_id": body["spiffe_id"], "display_name": body["display_name"], "status": "active"})
        raise AssertionError("unexpected setup mutation: " + url)
    def get(url, **kwargs):
        tenant = url.rsplit("/", 1)[1]
        return httpx.Response(200, json={"tenant_id": tenant, "tenant_admin_keys": [
            {"key_id": tenants[tenant], "key_status": "ACTIVE"}]})
    real_get = httpx.get
    statuses, inputs, ports = {}, {}, {}
    with monkeypatch.context() as setup:
        setup.setattr("aac_cli.cli.httpx.post", post)
        setup.setattr("aac_cli.cli.httpx.get", get)
        setup.setattr("aac_cli.cli.httpx.request", lambda method, url, **kw: (get if method == "GET" else post)(url, **kw))
        for index, agent in enumerate(("trip-planner", "booking"), 1):
            tenant = f"tnt-00000000-0000-4000-8000-00000000024{index}"
            active["tenant"] = tenant
            now = int(time.time())
            write_session_credential(SessionCredential(access_token="local-fixture-session", token_type="Bearer",
                audience="aac-control-plane", tenant_id=tenant, obtained_at_unix_seconds=now,
                expires_at_unix_seconds=now + 3600))
            app, loop, tls = ports[agent] = (port(), port(), port())
            config = yaml.safe_load((ROOT / "config" / (agent + ".yaml")).read_text())
            config["sidecar"].update(loopback_port=loop, external_port=tls,
                agent_invoke_url=f"http://127.0.0.1:{app}/invoke")
            config["sidecar"]["telemetry"]["central_forward"] = False
            file = tmp_path / (agent + ".yaml"); file.write_text(yaml.safe_dump(config)); inputs[agent] = file
            assert main(["init", "--profile", agent, "--agent", agent, "--agent-config", str(file),
                         "--admin-url", "http://fixture.invalid", "--data-plane-url", "http://fixture.invalid",
                         "--trust-url", "https://trust.example.com", "--display-name", "Consumer fixture",
                         "--contact", "test@example.com", "--bootstrap-token", "local-fixture", "--create-tenant"]) == 0
            capsys.readouterr()
            assert main(["agent", "status", "--agent", agent]) == 0
            statuses[agent] = json.loads(capsys.readouterr().out)
            for field in ("tenant-id", "hosted-trust-domain", "workload-spiffe-id"):
                assert main(["agent", "status", "--agent", agent, "--field", field]) == 0
                assert capsys.readouterr().out == statuses[agent][field.replace("-", "_")] + "\n"
        planner, booking = statuses["trip-planner"], statuses["booking"]
        config = yaml.safe_load(inputs["trip-planner"].read_text())
        config["destinations"] = {"tourfedia": {"url": f"https://127.0.0.1:{ports['booking'][2]}/v1/agent/receive",
            "audience_pattern": booking["workload_spiffe_id"], "predicates": {}, "valid_for": "+30m", "timeout_ms": 10000}}
        inputs["trip-planner"].write_text(yaml.safe_dump(config))
        assert main(["init", "--profile", "trip-planner", "--agent", "trip-planner", "--agent-config", str(inputs["trip-planner"])]) == 0
        capsys.readouterr()
    # Exercise the installed publisher's real daemon and signed HTTP uploads.
    published, publication_errors = {}, []
    decode = lambda value: base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    class Ingest(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def reply(self, body):
            raw = json.dumps(body).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
        def do_GET(self):
            self.reply({"binding": {"status": "ACTIVE", "binding_version": 1}})
        def do_POST(self):
            try:
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                header, body, signature = self.headers["AAC-Tenant-Admin"].split(".")
                claims = json.loads(decode(body)); tenant = claims["iss"]
                public = serialization.load_pem_public_key((home / "tenants" / tenant / "tenant-admin.pub.pem").read_bytes())
                public.verify(decode(signature), (header + "." + body).encode())
                assert claims["body_sha256"] == hashlib.sha256(raw).hexdigest()
                document = json.loads(raw)
                assert document.get("keys") or document.get("trust_anchors")
                published[(tenant, claims["artifact_class"])] = document
            except Exception as error:
                publication_errors.append(str(error))
            self.reply({"accepted": True})
    server = ThreadingHTTPServer(("127.0.0.1", 0), Ingest)
    serving = threading.Thread(target=server.serve_forever, daemon=True); serving.start()
    publishers, publisher_logs, streams = [], [], []
    try:
        endpoint = f"http://127.0.0.1:{server.server_port}"
        for agent, status in statuses.items():
            tenant_dir = home / "tenants" / status["tenant_id"]
            env = {k: v for k, v in os.environ.items() if not k.startswith("AAC_TAP_")}
            env.update(AAC_TAP_TENANT_ID=status["tenant_id"], AAC_TAP_ADMIN_KEY_FILE=str(tenant_dir / "tenant-admin.pem"),
                AAC_TAP_ROOT_KEYS_DIR=str(tenant_dir / "root-keys"), AAC_TAP_ROOT_KEYS_INGEST_URL=endpoint + "/v1/root-keys/ingest",
                AAC_TAP_SPIFFE_BUNDLE_DIR=str(tenant_dir / "spiffe-bundle"), AAC_TAP_SPIFFE_BUNDLE_INGEST_URL=endpoint + "/v1/spiffe-bundle/ingest",
                AAC_TAP_SPIFFE_TRUST_DOMAIN=status["hosted_trust_domain"],
                AAC_TAP_SPIFFE_BUNDLE_READ_URL=endpoint + "/.well-known/spiffe-bundle/" + status["hosted_trust_domain"])
            path = tmp_path / (agent + "-publisher.log"); stream = path.open("wb")
            publisher_logs.append(path); streams.append(stream)
            publishers.append(subprocess.Popen([sys.executable, "-m", "trust_anchor_publisher"], env=env,
                cwd=tmp_path, stdout=stream, stderr=stream))
        wait(lambda: len(published) == 4 or publication_errors, publishers, publisher_logs)
        assert not publication_errors
        assert all((item["tenant_id"], role) in published for item in statuses.values() for role in ("root_keys", "spiffe_bundle"))
    finally:
        for process in publishers:
            process.terminate(); process.wait(timeout=5)
        for stream in streams: stream.close()
        server.shutdown(); server.server_close(); serving.join(timeout=5)

    # Test-only trust sources isolate the candidate's runtime from remote stage.
    roots, bundles = tmp_path / "public-roots", tmp_path / "public-cas"
    roots.mkdir(); bundles.mkdir()
    for agent, status in statuses.items():
        # Feed the actual publisher output to the sidecar trust sources: a
        # wrong/missing key or CA must break the reservation, not pass merely
        # because the daemon emitted some JSON.
        tenant = status["tenant_id"]
        for key in published[(tenant, "root_keys")]["keys"]:
            assert key["kty"] == "OKP" and key["crv"] == "Ed25519"
            public = Ed25519PublicKey.from_public_bytes(decode(key["x"]))
            (roots / (tenant + "." + key["kid"] + ".pub.pem")).write_bytes(public.public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        bundle = published[(tenant, "spiffe_bundle")]
        assert bundle["publisher_tenant_id"] == tenant and bundle["trust_domain"] == status["hosted_trust_domain"]
        certs = "".join(anchor["cert_pem"] for anchor in bundle["trust_anchors"])
        (bundles / (status["hosted_trust_domain"] + ".ca.pem")).write_text(certs)
    processes, logs, handles = [], [], []
    def start(argv, env):
        path = tmp_path / f"process-{len(processes)}.log"
        stream = path.open("wb"); logs.append(path); handles.append(stream)
        processes.append(subprocess.Popen(argv, cwd=ROOT / "agent", env=env, stdout=stream, stderr=stream))
    try:
        for agent, status in statuses.items():
            folder = home / "agents" / agent
            config = yaml.safe_load((folder / "sidecar-config.yaml").read_text())
            config["sidecar"]["dev_mode"] = True
            config["trust_anchors"] = {"source": "filesystem", "directory": str(roots)}
            config["spiffe_bundles"] = {"source": "filesystem", "directory": str(bundles)}
            config["workload_projection"] = {"source": "static", "static_workloads": {
                item["workload_spiffe_id"]: item["tenant_id"] for item in statuses.values()}}
            # Both independent issuer roots are public trust in this fixture.
            ca = folder / "sidecar/outbound-ca.pem"
            ca.write_bytes(b"".join(path.read_bytes() for path in bundles.glob("*.pem")))
            config_file = tmp_path / (agent + "-runtime.yaml"); config_file.write_text(yaml.safe_dump(config))
            env = {**os.environ, "AAC_DEMO_ROLE": agent, "AAC_TENANT_ID": status["tenant_id"],
                   "AAC_WORKLOAD_SPIFFE_ID": status["workload_spiffe_id"],
                   "AAC_DEMO_ACTIONS": str(folder / "state/actions.jsonl"),
                   "AAC_INVOKE_AUTH_SECRET_FILE": str(folder / "agent/pairing.secret")}
            start([sys.executable, "-m", "uvicorn", "agent:app", "--host", "127.0.0.1", "--port", str(ports[agent][0])], env)
            start([BINARY, "-config", str(config_file)], env)
        for app, loop, _ in ports.values():
            wait(lambda: real_get(f"http://127.0.0.1:{loop}/readyz").status_code == 200 and
                 real_get(f"http://127.0.0.1:{app}/invoke").status_code == 401, processes, logs)
        spec = importlib.util.spec_from_file_location("consumer_client", ROOT / "agent/client.py")
        client = importlib.util.module_from_spec(spec); spec.loader.exec_module(client)
        task = "consumer-reservation-" + str(time.time_ns())
        body = json.dumps(client.start_body("reservation", task)).encode()
        folder = home / "agents/trip-planner"
        headers = {"Content-Type": "application/json"}
        headers.update(sign_invoke_request(secret=(folder / "agent/pairing.secret").read_bytes().strip(),
            method="POST", path="/v1/agent/delegations", headers=headers, body=body))
        context = ssl.create_default_context(cafile=str(folder / "sidecar/outbound-ca.pem"))
        response = httpx.post(f"https://127.0.0.1:{ports['trip-planner'][2]}/v1/agent/delegations",
                             content=body, headers=headers, verify=context)
        assert response.status_code == 200, response.text
        started = response.json(); root = started["root_token_id"]
        sender = folder / "state"; receiver = home / "agents/booking/state"
        def finished():
            sent = client.matching(sender, "telemetry.jsonl", root, task)
            got = client.matching(receiver, "telemetry.jsonl", root, task)
            return any(e.get("event_type") == "dispatch" for e in sent) and any(e.get("event_type") == "respond" for e in got)
        wait(finished, processes, logs)
        sent = client.matching(sender, "telemetry.jsonl", root, task)
        got = client.matching(receiver, "telemetry.jsonl", root, task)
        actions = client.matching(receiver, "actions.jsonl", root, task)
        result = client.verify_result(started, next(e for e in sent if e["event_type"] == "dispatch"),
            next(e for e in got if e["event_type"] == "receive"), next(e for e in got if e["event_type"] == "respond"),
            actions[0], statuses["booking"]["workload_spiffe_id"])
        assert result["amount"] == 8000
    finally:
        for process in reversed(processes):
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        for stream in handles: stream.close()
