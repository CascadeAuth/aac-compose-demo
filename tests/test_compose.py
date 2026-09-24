"""Resolve the actual Compose input against the public CLI-generated paths."""
import json
import os
import shutil
import subprocess

import pytest
import yaml
from conftest import REPO

pytestmark = pytest.mark.skipif(not shutil.which("docker"), reason="Docker Compose unavailable")


@pytest.mark.parametrize("agent", ["trip-planner", "booking"])
def test_independent_mounts_tls_and_runtime(synthetic_home, agent):
    env = {**os.environ, "AAC_DEMO_ROLE": agent, "AAC_DEMO_UID": "4242", "AAC_DEMO_GID": "4243",
           "AAC_DEMO_VANTIS_STATE": str(synthetic_home / "agents/trip-planner/state"),
           "AAC_DEMO_TOURFEDIA_STATE": str(synthetic_home / "agents/booking/state")}
    folder = synthetic_home / "agents" / agent
    result = subprocess.run(["docker", "compose", "--env-file", str(folder / "compose.env"),
        "--profile", "exercise", "config", "--format", "json"], cwd=REPO, env=env,
        capture_output=True, text=True, check=True)
    rendered = json.loads(result.stdout)
    services = rendered["services"]
    assert rendered["name"] == "aac-compose-demo-" + agent
    assert services["sidecar"]["image"] == "docker.io/cascadeauth/aac-sidecar:v0.4.1"
    assert services["sidecar"]["network_mode"] == "service:agent"
    assert services["client"]["network_mode"] == "service:agent"
    assert services["agent"]["environment"]["AAC_DEMO_ROLE"] == agent
    assert services["agent"]["networks"]["peers"]["aliases"] == [agent]
    for service in services.values():
        assert service["user"] == "4242:4243"
        assert "ports" not in service
        for mount in service["volumes"]:
            assert "/keep" not in mount["source"]
    for name in ("agent", "client"):
        mounts = {m["target"]: m["source"] for m in services[name]["volumes"]}
        assert mounts["/run/secrets"] == str(folder / "agent")
        assert not any("/sidecar" in source for source in mounts.values())
    sidecar = {m["target"]: m for m in services["sidecar"]["volumes"]}
    assert sidecar["/etc/aac/pki"]["source"] == str(folder / "sidecar")
    assert sidecar["/etc/aac/pki"]["read_only"]
    cfg = yaml.safe_load((folder / "sidecar-config.yaml").read_text())
    assert cfg["sidecar"]["dev_mode"] is False
    assert cfg["sidecar"]["external_bind_address"] == "0.0.0.0"
    assert cfg["replay_protection"]["deployment_profile"] == "basic"
    assert cfg["destinations"] == {}
    assert agent in (folder / "compose.env").read_text()
    if agent == "trip-planner":
        coa = cfg["classes_of_action"]["reserve_travel"]
        assert coa["valid_for"] == "+2h" and "amount_max" not in coa["predicates"]
    else:
        assert cfg["classes_of_action"] == {}
