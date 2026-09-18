"""Shared paths and a synthetic agent for the offline tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
COMPOSE_FILE = REPO / "compose.yaml"
STARTER = REPO / "starter"
AGENT_DIR = REPO / "agent"

# A synthetic tenant and agent in the shape `aac init` produces. The ids
# are fixed test values; nothing here touches ~/.aac or the network.
TENANT_ID = "tnt-550e8400-e29b-41d4-9716-446655440000"
TRUST_DOMAIN = TENANT_ID + ".tenants.stage.cascadeauth.dev"
AGENT_NAME = "starter"


@pytest.fixture(params=["issued-here", "supplied"])
def synthetic_home(tmp_path: Path, request) -> Path:
    """A CLI home with a rendered, container-layout agent and its compose.env.

    Built with the CLI's own renderer so the compose file is tested against
    exactly what `aac init` writes, never against a hand-copied sample.
    """
    from aac_cli.config_render import render_compose_env, render_publisher_env, render_sidecar_config, sidecar_config_text
    from aac_cli.agent_layout import tenant_paths, agent_paths
    from aac_cli.agent_record import new_record

    home = tmp_path / "aac-home"
    agent = agent_paths(AGENT_NAME, home)
    tenant = tenant_paths(TENANT_ID, home)
    api_key_file = home / "credentials" / TENANT_ID
    for directory in (agent.sidecar_dir, agent.agent_dir, agent.state,
                      tenant.root_keys_directory, tenant.spiffe_bundle_directory, api_key_file.parent):
        directory.mkdir(parents=True, exist_ok=True)
    record = new_record(
        agent=AGENT_NAME, profile="stage", material_source=request.param,
        admin_url="https://api.stage.cascadeauth.dev", trust_url="https://trust.stage.cascadeauth.dev",
        data_plane_url="https://api.stage.cascadeauth.dev", workload_path="demo/agent",
    )
    from dataclasses import replace
    record = replace(
        record, tenant_id=TENANT_ID, hosted_trust_domain=TRUST_DOMAIN,
        workload_spiffe_id=f"spiffe://{TRUST_DOMAIN}/demo/agent", workload_path="demo/agent",
        root_key_id=agent.root_key_id(), ca_anchor_id=agent.ca_anchor_id(request.param), layout="container",
    )
    from aac_cli.agent_record import STEP_ADMIN_KEY_INSTALLED, STEP_HOSTED_DOMAIN, STEP_MATERIAL, STEP_SETTINGS, STEP_TENANT, STEP_WORKLOAD, write_record
    for step in (STEP_TENANT, STEP_HOSTED_DOMAIN, STEP_WORKLOAD, STEP_MATERIAL, STEP_ADMIN_KEY_INSTALLED, STEP_SETTINGS):
        record = record.with_step(step)
    write_record(agent.record, record)
    config = render_sidecar_config(record, agent, api_key_file=api_key_file, layout="container")
    agent.sidecar_config.write_text(sidecar_config_text(config, agent_name=AGENT_NAME, material_source=request.param, profile="stage"))
    agent.compose_env.write_text(render_compose_env(record, agent, tenant, api_key_file=api_key_file))
    tenant.publisher_env.write_text(render_publisher_env(record, tenant))
    # Real (throwaway) development material, generated with the CLI's own
    # generator, so `aac agent status` can assess the synthetic agent.
    from aac_cli import dev_material

    ca_key = dev_material.generate_ed25519_key()
    ca_certificate = dev_material.build_development_ca(ca_key)
    ca_pem = dev_material.certificate_pem(ca_certificate)
    spiffe_id = f"spiffe://{TRUST_DOMAIN}/demo/agent"
    for key_path, cert_path in ((agent.workload_key, agent.workload_certificate),
                                (agent.terminal_key, agent.terminal_certificate)):
        key = dev_material.generate_ed25519_key()
        certificate = dev_material.issue_identity_certificate(
            ca_key=ca_key, ca_certificate=ca_certificate, subject_key=key, spiffe_id=spiffe_id)
        key_path.write_bytes(dev_material.private_key_pem(key))
        cert_path.write_bytes(dev_material.certificate_pem(certificate))
    server_key = dev_material.generate_p256_key()
    server_certificate = dev_material.issue_localhost_server_certificate(
        ca_key=ca_key, ca_certificate=ca_certificate, server_key=server_key)
    agent.server_key.write_bytes(dev_material.private_key_pem(server_key))
    agent.server_certificate.write_bytes(dev_material.certificate_pem(server_certificate))
    root_key = dev_material.generate_ed25519_key()
    agent.root_signing_key.write_bytes(dev_material.private_key_pem(root_key))
    agent.root_signing_public_key.write_bytes(dev_material.public_key_pem(root_key))
    tenant.published_root_key(agent.root_key_id()).write_bytes(dev_material.public_key_pem(root_key))
    for path in (agent.ca_certificate, agent.agent_ca_certificate,
                 tenant.published_ca_certificate(record.ca_anchor_id)):
        path.write_bytes(ca_pem)
    if request.param == "issued-here":
        agent.keep_dir.mkdir()
        agent.ca_key.write_bytes(dev_material.private_key_pem(ca_key))
    agent.outbound_ca_bundle.write_bytes(ca_pem)
    agent.pairing_secret.write_text("synthetic-pairing-secret\n")
    admin_key = dev_material.generate_ed25519_key()
    tenant.admin_key.write_bytes(dev_material.private_key_pem(admin_key))
    tenant.admin_public_key.write_bytes(dev_material.public_key_pem(admin_key))
    api_key_file.write_text("synthetic-api-key\n")
    (home / "config").write_text(
        f"[stage]\nadmin_url = {record.admin_url}\ndata_plane_url = {record.data_plane_url}\ntenant_id = {TENANT_ID}\n")
    for path in home.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
    home.chmod(0o700)
    (home / "record-for-tests.json").write_text(json.dumps({
        "sidecar_config": config,
        "publisher_env": tenant.publisher_env.read_text(),
    }))
    return home


def compose_env_values(home: Path) -> dict[str, str]:
    """The KEY=value pairs of the agent's compose.env (shell quoting removed)."""
    import shlex

    values = {}
    for line in (home / "agents" / AGENT_NAME / "compose.env").read_text().splitlines():
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            values[key] = "".join(shlex.split(value))
    return values


def docker_available() -> bool:
    import shutil
    import subprocess

    if os.environ.get("AAC_STARTER_SKIP_DOCKER"):
        return False
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "compose", "version"], capture_output=True).returncode == 0
