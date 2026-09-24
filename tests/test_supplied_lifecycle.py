"""Exercise the live driver twice against the CLI's no-overwrite contract."""
import importlib
import json
import os

import pytest
import yaml
from conftest import REPO


@pytest.fixture
def driver(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(REPO / "tests/live"))
    module = importlib.import_module("test_supplied_material")
    config = tmp_path / "inputs"
    config.mkdir()
    (config / "booking.yaml").write_text((REPO / "config/booking.yaml").read_text())
    home = tmp_path / "aac"
    monkeypatch.setattr(module, "HOME", home)
    monkeypatch.setattr(module, "CONFIG", config)
    monkeypatch.delenv("AAC_TEST_BOOKING_AGENT", raising=False)
    calls = []

    def run(*args):
        calls.append((args, os.environ.get("AAC_TEST_BOOKING_AGENT")))
        if args[:3] == ("aac", "agent", "status"):
            return json.dumps({"workload_spiffe_id": "spiffe://tourfedia.test/booking"})
        if args[:2] == ("aac", "init") and args[args.index("--agent") + 1] == "book-supplied":
            slot = home / "agents/book-supplied"
            if (slot / "compose.env").exists() and "--workload-cert-file" in args:
                raise AssertionError("init refuses material replacement; use renew")
            slot.mkdir(parents=True, exist_ok=True)
            (slot / "compose.env").write_text("# CLI-generated output\n")
            (slot / "sidecar-config.yaml").write_text(yaml.safe_dump({"agent": {"spiffe_id": "spiffe://tourfedia.test/booking"}}))
        return ""

    monkeypatch.setattr(module, "run", run)
    return module, calls, run


def test_fresh_then_repeat_supplied_lifecycle(driver, monkeypatch):
    module, calls, _ = driver
    module.test_supplied_certificate_replacement(monkeypatch)
    first_end = len(calls)
    module.test_supplied_certificate_replacement(monkeypatch)
    repeated = calls[first_end:]
    setup = [args for args, _ in calls if args[:2] == ("aac", "init") and "book-supplied" in args]
    assert "--workload-cert-file" in setup[0]
    assert "--workload-cert-file" not in setup[1]
    first_mutation = next(args for args, _ in repeated if args[:3] == ("aac", "agent", "renew"))
    assert first_mutation[4] == "book-supplied" and "--workload-cert-file" in first_mutation
    assert calls[-1] == (("./demo", "up"), None)


@pytest.mark.parametrize("existing", [False, True])
def test_setup_failure_restores_normal_booking_slot(driver, monkeypatch, existing):
    module, calls, run = driver
    if existing:
        module.test_supplied_certificate_replacement(monkeypatch)
        calls.clear()

    def fail_setup(*args):
        if args[:2] == ("aac", "init") and "book-supplied" in args:
            raise AssertionError("controlled setup failure")
        return run(*args)

    monkeypatch.setattr(module, "run", fail_setup)
    with pytest.raises(AssertionError, match="controlled setup failure"):
        module.test_supplied_certificate_replacement(monkeypatch)
    assert calls[-1] == (("./demo", "up"), None)
    assert "AAC_TEST_BOOKING_AGENT" not in os.environ
