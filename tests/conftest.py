"""Shared paths and a synthetic workspace for the offline tests."""

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

# A synthetic tenant and workspace in the shape `aac init` produces. The ids
# are fixed test values; nothing here touches ~/.aac or the network.
TENANT_ID = "tnt-550e8400-e29b-41d4-9716-446655440000"
TRUST_DOMAIN = TENANT_ID + ".tenants.stage.cascadeauth.dev"
WORKSPACE_NAME = "starter"


@pytest.fixture
def synthetic_home(tmp_path: Path) -> Path:
    """A CLI home with a rendered, container-layout workspace and its compose.env.

    Built with the CLI's own renderer so the compose file is tested against
    exactly what `aac init` writes, never against a hand-copied sample.
    """
    from aac_cli.config_render import render_compose_env, render_publisher_env, render_sidecar_config, sidecar_config_text
    from aac_cli.workspace_layout import tenant_paths, workspace_paths
    from aac_cli.workspace_manifest import new_manifest

    home = tmp_path / "aac-home"
    workspace = workspace_paths(WORKSPACE_NAME, home)
    tenant = tenant_paths(TENANT_ID, home)
    api_key_file = home / "credentials" / TENANT_ID
    for directory in (workspace.pki, workspace.pair, workspace.state, workspace.ca,
                      tenant.root_keys_directory, tenant.spiffe_bundle_directory, api_key_file.parent):
        directory.mkdir(parents=True, exist_ok=True)
    manifest = new_manifest(
        workspace=WORKSPACE_NAME, profile="stage",
        admin_url="https://api.stage.cascadeauth.dev", trust_url="https://trust.stage.cascadeauth.dev",
        data_plane_url="https://api.stage.cascadeauth.dev", workload_path="demo/agent",
    )
    from dataclasses import replace
    manifest = replace(
        manifest, tenant_id=TENANT_ID, hosted_trust_domain=TRUST_DOMAIN,
        workload_spiffe_id=f"spiffe://{TRUST_DOMAIN}/demo/agent", workload_path="demo/agent",
        root_key_id=workspace.root_key_id(), ca_anchor_id=workspace.ca_anchor_id(), layout="container",
    )
    from aac_cli.workspace_manifest import STEP_ADMIN_KEY_INSTALLED, STEP_HOSTED_DOMAIN, STEP_MATERIAL, STEP_RENDERED, STEP_TENANT, STEP_WORKLOAD, write_manifest
    for step in (STEP_TENANT, STEP_HOSTED_DOMAIN, STEP_WORKLOAD, STEP_MATERIAL, STEP_ADMIN_KEY_INSTALLED, STEP_RENDERED):
        manifest = manifest.with_step(step)
    write_manifest(workspace.manifest, manifest)
    config = render_sidecar_config(manifest, workspace, api_key_file=api_key_file, layout="container")
    workspace.sidecar_config.write_text(sidecar_config_text(config))
    workspace.compose_env.write_text(render_compose_env(manifest, workspace, tenant, api_key_file=api_key_file))
    tenant.publisher_env.write_text(render_publisher_env(manifest, tenant))
    # Real (throwaway) development material, generated with the CLI's own
    # generator, so `aac workspace status` can assess the synthetic workspace.
    from aac_cli import dev_material

    ca_key = dev_material.generate_ed25519_key()
    ca_certificate = dev_material.build_development_ca(ca_key)
    ca_pem = dev_material.certificate_pem(ca_certificate)
    spiffe_id = f"spiffe://{TRUST_DOMAIN}/demo/agent"
    for key_path, cert_path in ((workspace.workload_key, workspace.workload_certificate),
                                (workspace.terminal_key, workspace.terminal_certificate)):
        key = dev_material.generate_ed25519_key()
        certificate = dev_material.issue_identity_certificate(
            ca_key=ca_key, ca_certificate=ca_certificate, subject_key=key, spiffe_id=spiffe_id)
        key_path.write_bytes(dev_material.private_key_pem(key))
        cert_path.write_bytes(dev_material.certificate_pem(certificate))
    server_key = dev_material.generate_p256_key()
    server_certificate = dev_material.issue_localhost_server_certificate(
        ca_key=ca_key, ca_certificate=ca_certificate, server_key=server_key)
    workspace.server_key.write_bytes(dev_material.private_key_pem(server_key))
    workspace.server_certificate.write_bytes(dev_material.certificate_pem(server_certificate))
    root_key = dev_material.generate_ed25519_key()
    workspace.root_signing_key.write_bytes(dev_material.private_key_pem(root_key))
    workspace.root_signing_public_key.write_bytes(dev_material.public_key_pem(root_key))
    tenant.published_root_key(workspace.root_key_id()).write_bytes(dev_material.public_key_pem(root_key))
    for path in (workspace.dev_ca_certificate, workspace.pair_ca_certificate,
                 tenant.published_ca_certificate(workspace.ca_anchor_id())):
        path.write_bytes(ca_pem)
    workspace.dev_ca_key.write_bytes(dev_material.private_key_pem(ca_key))
    workspace.outbound_ca_bundle.write_bytes(ca_pem)
    workspace.pairing_secret.write_text("synthetic-pairing-secret\n")
    admin_key = dev_material.generate_ed25519_key()
    tenant.admin_key.write_bytes(dev_material.private_key_pem(admin_key))
    tenant.admin_public_key.write_bytes(dev_material.public_key_pem(admin_key))
    api_key_file.write_text("synthetic-api-key\n")
    for path in home.rglob("*"):
        path.chmod(0o700 if path.is_dir() else 0o600)
    home.chmod(0o700)
    (home / "manifest-for-tests.json").write_text(json.dumps({
        "sidecar_config": config,
        "publisher_env": tenant.publisher_env.read_text(),
    }))
    return home


def compose_env_values(home: Path) -> dict[str, str]:
    """The KEY=value pairs of the workspace's compose.env (shell quoting removed)."""
    import shlex

    values = {}
    for line in (home / "workspaces" / WORKSPACE_NAME / "compose.env").read_text().splitlines():
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            values[key] = "".join(shlex.split(value))
    return values


def docker_daemon_available() -> bool:
    """`docker info` succeeds: the daemon is running (the starter's preflight needs it)."""
    import shutil
    import subprocess

    if os.environ.get("AAC_STARTER_SKIP_DOCKER") or not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def docker_available() -> bool:
    import shutil
    import subprocess

    if os.environ.get("AAC_STARTER_SKIP_DOCKER"):
        return False
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "compose", "version"], capture_output=True).returncode == 0
