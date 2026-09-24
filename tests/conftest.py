"""Offline material comes exclusively from the installed public CLI's generator."""
import importlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from aac_cli import dev_material
from aac_cli.agent_config import load_config
from aac_cli.agent_layout import agent_paths, tenant_paths
from aac_cli.agent_record import new_record
from aac_cli.config_render import render_compose_env, render_publisher_env, render_sidecar_config, sidecar_config_text

REPO = Path(__file__).resolve().parents[1]
AGENT_DIR = REPO / "agent"


@pytest.fixture
def client_module(monkeypatch):
    monkeypatch.syspath_prepend(str(AGENT_DIR))
    return importlib.import_module("client")


@pytest.fixture
def synthetic_home(tmp_path):
    home = tmp_path / "aac-home"
    for index, agent in enumerate(("trip-planner", "booking"), 1):
        tenant_id = f"tnt-550e8400-e29b-41d4-9716-44665544000{index}"
        domain = tenant_id + ".tenants.stage.cascadeauth.dev"
        paths, tenant = agent_paths(agent, home), tenant_paths(tenant_id, home)
        for directory in (paths.sidecar_dir, paths.agent_dir, paths.state, tenant.root_keys_directory,
                          tenant.spiffe_bundle_directory, home / "credentials"):
            directory.mkdir(parents=True, exist_ok=True)
        config, cas = load_config(REPO / "config" / (agent + ".yaml"))
        record = new_record(agent=agent, profile=agent, workload_path=agent, agent_config=config,
                            admin_url="https://api.stage.cascadeauth.dev", data_plane_url="https://api.stage.cascadeauth.dev",
                            trust_url="https://trust.stage.cascadeauth.dev")
        record = replace(record, tenant_id=tenant_id, hosted_trust_domain=domain,
                         workload_spiffe_id=f"spiffe://{domain}/{agent}", root_key_id=paths.root_key_id(), layout="container")
        api = home / "credentials" / tenant_id
        api.write_text("synthetic-credential")
        ca_key = dev_material.generate_ed25519_key()
        ca = dev_material.build_development_ca(ca_key)
        for path in (paths.ca_certificate, paths.agent_ca_certificate, paths.outbound_ca_bundle):
            path.write_bytes(dev_material.certificate_pem(ca))
        for key_path, cert_path in ((paths.workload_key, paths.workload_certificate), (paths.terminal_key, paths.terminal_certificate)):
            key = dev_material.generate_ed25519_key()
            cert = dev_material.issue_identity_certificate(ca_key=ca_key, ca_certificate=ca,
                        subject_key=key, spiffe_id=record.workload_spiffe_id)
            key_path.write_bytes(dev_material.private_key_pem(key))
            cert_path.write_bytes(dev_material.certificate_pem(cert))
        root_key = dev_material.generate_ed25519_key()
        paths.root_signing_key.write_bytes(dev_material.private_key_pem(root_key))
        paths.pairing_secret.write_text("synthetic-" + agent + "-pairing-secret")
        tenant.admin_key.write_bytes(dev_material.private_key_pem(dev_material.generate_ed25519_key()))
        rendered = render_sidecar_config(record, paths, api_key_file=api, layout="container")
        paths.sidecar_config.write_text(sidecar_config_text(rendered, agent_name=agent, material_source="issued-here", profile=agent))
        paths.compose_env.write_text(render_compose_env(record, paths, tenant, api_key_file=api))
        tenant.publisher_env.write_text(render_publisher_env(record, tenant))
        (paths.root / "public-status.json").write_text(json.dumps({"tenant_id": tenant_id,
            "workload_spiffe_id": record.workload_spiffe_id, "root_key_id": record.root_key_id}))
    return home
