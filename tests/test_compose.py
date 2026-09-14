"""The compose file against a synthetic workspace rendered by the CLI itself.

`docker compose config` resolves every variable and anchor exactly as a run
would; the assertions pin the consumer (this repository) to the producer (the
CLI's container layout and compose.env), so a rename on either side fails here.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml
from aac_cli.workspace_layout import (
    CONTAINER_SECRETS_DIRECTORY,
    CONTAINER_SIDECAR_DIRECTORY,
    CONTAINER_STATE_DIRECTORY,
)

from conftest import COMPOSE_FILE, REPO, TENANT_ID, TRUST_DOMAIN, compose_env_values, docker_available

pytestmark = pytest.mark.skipif(not docker_available(), reason="docker compose is not available")

UID, GID = "4242", "4243"


def rendered(home: Path, tmp_path: Path, *profiles: str) -> dict:
    env = {**os.environ, "AAC_STARTER_UID": UID, "AAC_STARTER_GID": GID,
           "AAC_STARTER_EXERCISE_DIR": str(tmp_path / "exercise")}
    command = ["docker", "compose", "--project-directory", str(REPO),
               "--env-file", str(home / "workspaces" / "starter" / "compose.env")]
    for profile in profiles:
        command += ["--profile", profile]
    command += ["config", "--format", "json"]
    result = subprocess.run(command, capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def mounts(service: dict) -> dict[str, dict]:
    return {volume["target"]: volume for volume in service["volumes"]}


def test_sidecar_mounts_exactly_what_the_container_layout_expects(synthetic_home, tmp_path):
    values = compose_env_values(synthetic_home)
    config = rendered(synthetic_home, tmp_path)
    sidecar = config["services"]["sidecar"]
    by_target = mounts(sidecar)
    expected = {
        f"{CONTAINER_SIDECAR_DIRECTORY}/sidecar-config.yaml": values["AAC_SIDECAR_CONFIG_FILE"],
        f"{CONTAINER_SIDECAR_DIRECTORY}/pki": values["AAC_WORKSPACE_PKI_DIR"],
        f"{CONTAINER_SECRETS_DIRECTORY}/pairing.secret": values["AAC_WORKSPACE_PAIR_DIR"] + "/pairing.secret",
        f"{CONTAINER_SECRETS_DIRECTORY}/tenant-api-key": values["AAC_API_KEY_FILE"],
        CONTAINER_STATE_DIRECTORY: values["AAC_WORKSPACE_STATE_DIR"],
    }
    assert {target: mount["source"] for target, mount in by_target.items()} == expected
    for target, mount in by_target.items():
        assert mount.get("read_only", False) == (target != CONTAINER_STATE_DIRECTORY), target
    # Every path the rendered configuration names is served by one of these mounts.
    sidecar_config = json.loads((synthetic_home / "manifest-for-tests.json").read_text())["sidecar_config"]
    referenced = {
        sidecar_config["sidecar"]["agent_invoke_auth"]["secret_file"],
        sidecar_config["sidecar"]["tls_cert_file"], sidecar_config["sidecar"]["tls_key_file"],
        sidecar_config["sidecar"]["tls_ca_file"], sidecar_config["sidecar"]["telemetry"]["sink"],
        sidecar_config["tenant"]["signing_key_file"], sidecar_config["agent"]["svid_key_file"],
        sidecar_config["agent"]["svid_cert_file"], sidecar_config["agent"]["attestation_key_file"],
        sidecar_config["agent"]["attestation_cert_file"], sidecar_config["workload_projection"]["api_key_file"],
        sidecar_config["a2a"]["egress_idempotency"]["state_file"],
    }
    for path in referenced:
        assert any(path == target or path.startswith(target + "/") for target in by_target), path
    assert sidecar["network_mode"] == "service:agent"
    assert sidecar["command"] == ["-config", f"{CONTAINER_SIDECAR_DIRECTORY}/sidecar-config.yaml"]
    # The development CA private key never enters a container.
    for service in config["services"].values():
        for mount in service.get("volumes", []):
            assert not mount["source"].endswith("/ca") and "dev-ca.key" not in mount["source"]


def test_publisher_environment_matches_the_cli_render(synthetic_home, tmp_path):
    from aac_cli.workspace_layout import tenant_paths

    config = rendered(synthetic_home, tmp_path)
    publisher = config["services"]["publisher"]
    tenant = tenant_paths(TENANT_ID, synthetic_home)
    cli_env = {}
    for line in tenant.publisher_env.read_text().splitlines():
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            cli_env[key] = value.strip("'")
    translated = {
        "AAC_TAP_ADMIN_KEY_FILE": ("/keys/tenant-admin.pem", str(tenant.admin_key)),
        "AAC_TAP_ROOT_KEYS_DIR": ("/root-keys", str(tenant.root_keys_directory)),
        "AAC_TAP_SPIFFE_BUNDLE_DIR": ("/spiffe-bundle", str(tenant.spiffe_bundle_directory)),
    }
    compose_env = publisher["environment"]
    assert set(compose_env) == set(cli_env), "the compose file must set exactly the variables the CLI renders"
    for key, cli_value in cli_env.items():
        if key in translated:
            container_path, host_path = translated[key]
            assert compose_env[key] == container_path
            assert cli_value == host_path
            assert mounts(publisher)[container_path]["source"] == host_path
            assert mounts(publisher)[container_path]["read_only"] is True
        else:
            assert compose_env[key] == cli_value, key
    assert compose_env["AAC_TAP_SPIFFE_TRUST_DOMAIN"] == TRUST_DOMAIN


def test_every_container_runs_as_the_caller_without_ports_or_privileges(synthetic_home, tmp_path):
    config = rendered(synthetic_home, tmp_path, "exercise")
    assert set(config["services"]) == {"agent", "sidecar", "publisher", "client"}
    for name, service in config["services"].items():
        assert service["user"] == f"{UID}:{GID}", name
        assert service["read_only"] is True, name
        assert service["cap_drop"] == ["ALL"], name
        assert service["security_opt"] == ["no-new-privileges:true"], name
        assert "ports" not in service, name
        assert service.get("privileged") is not True
    assert config["services"]["client"]["network_mode"] == "service:agent"
    assert "exercise" in config["services"]["client"]["profiles"]


def test_the_client_is_not_part_of_a_plain_up(synthetic_home, tmp_path):
    assert "client" not in rendered(synthetic_home, tmp_path)["services"]


def test_running_without_the_starter_variables_is_refused(synthetic_home, tmp_path):
    result = subprocess.run(
        ["docker", "compose", "--project-directory", str(REPO),
         "--env-file", str(synthetic_home / "workspaces" / "starter" / "compose.env"), "config"],
        capture_output=True, text=True, env={k: v for k, v in os.environ.items() if not k.startswith("AAC_STARTER_")})
    assert result.returncode != 0
    assert "./starter" in result.stderr
