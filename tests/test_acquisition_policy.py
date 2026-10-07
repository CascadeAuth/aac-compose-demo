"""Bounded acquisition regressions, not the B304 network-blocking campaign."""
import json
import sys
import zipfile

import pytest
import yaml

import components
from conftest import REPO
from tools import check_candidate, prepare_checks


@pytest.fixture
def inputs(tmp_path):
    selection = tmp_path / "selection.json"
    selection.write_bytes((REPO / "tests/fixtures/components.json").read_bytes())
    binary = tmp_path / "aac-sidecar"
    binary.write_bytes(b"test binary, never executed by mocked runner")
    wheel = tmp_path / "candidate.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("aac_cli.dist-info/METADATA", "Name: aac-cli\nVersion: 0.2.9\n")
    return selection, binary, wheel


@pytest.fixture
def isolated_runner(monkeypatch):
    """Allow only known test/install commands; reject all registry/helper calls."""
    calls = []
    def output(argv, **kwargs):
        if argv == ["git", "rev-parse", "HEAD"]:
            return "a" * 40
        if argv[1:] == ["-m", "pip", "list", "--format", "json"]:
            return "[]"
        pytest.fail("unexpected external command: " + repr(argv))
    def run(argv, **kwargs):
        argv = list(argv)
        assert argv[1:4] == ["-m", "pip", "install"] or argv[1:3] == ["-m", "pytest"], argv
        calls.append((argv, kwargs))
    monkeypatch.setattr(check_candidate.subprocess, "check_output", output)
    monkeypatch.setattr(check_candidate.subprocess, "run", run)
    monkeypatch.setattr(check_candidate.venv.EnvBuilder, "create", lambda self, path: None)
    monkeypatch.setattr(components, "resolve", lambda: pytest.fail("public component discovery"))
    monkeypatch.setattr(components, "image_digest", lambda ref: pytest.fail("container discovery: " + ref))
    monkeypatch.setattr(components, "read_json", lambda url: pytest.fail("unexpected metadata discovery: " + url))
    return calls


def test_fixture_setup_uses_committed_pins_without_discovery_or_run_state(monkeypatch, tmp_path, isolated_runner):
    monkeypatch.setattr(prepare_checks.sys, "prefix", "active-venv")
    monkeypatch.setattr(prepare_checks, "ROOT", tmp_path)
    prepare_checks.prepare()
    argv = isolated_runner[0][0]
    record = components.load_selection(prepare_checks.SELECTION)
    for name in components.PACKAGES:
        assert components.package_spec(name, record["packages"][name]) in argv
    assert not (tmp_path / ".local").exists()


@pytest.mark.parametrize("component", [*components.PACKAGES, "sidecar"])
def test_supplied_inputs_run_exact_binary_without_registry_helpers(component, inputs, tmp_path, isolated_runner):
    selection, binary, wheel = inputs
    if component != "sidecar":
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("candidate.dist-info/METADATA", f"Name: {component}\nVersion: 0.2.9\n")
    artifacts = [binary] if component == "sidecar" else [wheel]
    options = {} if component == "sidecar" else {
        "sidecar_binary": binary, "sidecar_sha256": check_candidate.digest(binary)}
    receipt = tmp_path / "receipt.json"
    record = check_candidate.check(component, artifacts, receipt, "a"*40, selection=selection, **options)
    assert record["passed"] is True
    assert record["sidecar_source"] == ("candidate" if component == "sidecar" else "supplied")
    assert record["sidecar_binary_sha256"] == check_candidate.digest(binary)
    assert record["selection_sha256"] == check_candidate.digest(selection)
    assert record["companions"] == components.load_selection(selection)
    assert check_candidate.verify(receipt, "a"*40, artifacts) == record
    tests = [(argv, kw) for argv, kw in isolated_runner if argv[1:3] == ["-m", "pytest"]]
    assert len(tests) == 2
    assert tests[1][0][3] == "tests/compatibility/test_consumer.py"
    assert all(kw["env"]["AAC_COMPAT_BINARY"] == str(binary) for _, kw in tests)


@pytest.mark.parametrize("supplied", [False, True])
def test_binary_paths_discover_only_python_companions(supplied, inputs, tmp_path, isolated_runner, monkeypatch):
    _, binary, wheel = inputs
    urls = []
    def fetch(url):
        urls.append(url)
        assert url.startswith("https://pypi.org/pypi/")
        return {"info": {"version": "0.2.9"}, "urls": [{"packagetype": "bdist_wheel", "yanked": False,
            "url": "https://files.pythonhosted.org/fixture.whl", "digests": {"sha256": "3"*64}}]}
    monkeypatch.setattr(components, "read_json", fetch)
    options = {"sidecar_binary": binary, "sidecar_sha256": check_candidate.digest(binary)} if supplied else {}
    record = check_candidate.check("aac-cli" if supplied else "sidecar", [wheel] if supplied else [binary],
                                   tmp_path / "receipt.json", "a"*40, **options)
    assert record["passed"] is True
    assert urls == [f"https://pypi.org/pypi/{name}/json" for name in components.PACKAGES]
    assert "sidecar" not in record["companions"]


@pytest.mark.parametrize("failure", ["missing-binary", "tampered-binary", "missing-selection",
    "invalid-selection", "missing-package", "bad-hash", "binary-only", "hash-only", "selection-only", "candidate-conflict"])
def test_supplied_input_failure_has_no_public_fallback(failure, inputs, tmp_path, isolated_runner):
    selection, binary, wheel = inputs
    options = {"selection": selection, "sidecar_binary": binary, "sidecar_sha256": check_candidate.digest(binary)}
    if failure == "missing-binary": binary.unlink()
    if failure == "tampered-binary": binary.write_bytes(b"tampered")
    if failure == "missing-selection": selection.unlink()
    if failure == "invalid-selection": selection.write_text("{}")
    if failure in ("missing-package", "bad-hash"):
        record = json.loads(selection.read_text())
        if failure == "missing-package": del record["packages"]["aac-cli"]
        else: record["packages"]["aac-cli"]["sha256"] = "bad"
        selection.write_text(json.dumps(record))
    if failure == "binary-only": del options["sidecar_sha256"]
    if failure == "hash-only": del options["sidecar_binary"]
    if failure == "selection-only":
        del options["sidecar_sha256"]; del options["sidecar_binary"]
    receipt = tmp_path / "receipt.json"
    with pytest.raises((ValueError, FileNotFoundError)):
        check_candidate.check("sidecar" if failure == "candidate-conflict" else "aac-cli", [wheel],
                              receipt, "a"*40, **options)
    assert json.loads(receipt.read_text())["passed"] is False
    assert isolated_runner == []


def test_checks_workflow_calls_only_fixture_setup_and_non_live_checks():
    workflow = yaml.safe_load((REPO / ".github/workflows/checks.yml").read_text())
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {"fixture-checks"}
    job = workflow["jobs"]["fixture-checks"]
    assert set(job) == {"runs-on", "steps"}
    assert [step for step in job["steps"] if "uses" in step] == [
        {"uses": "actions/checkout@v6"},
        {"uses": "actions/setup-python@v6", "with": {"python-version": "3.12"}}]
    scripts = [step["run"] for step in job["steps"] if "run" in step]
    # An explicit command inventory also catches indirect discovery helpers,
    # docker/oras/cosign additions and credential setup, not just host spelling.
    assert len(scripts) == 1
    assert scripts[0].splitlines() == [
        "python -m venv .venv", "source .venv/bin/activate",
        "python tools/prepare_checks.py",
        "python -m py_compile demo agent/*.py tests/fixtures/*.py",
        "python -m pytest tests -q --ignore tests/live",
        "docker build --quiet --build-arg AAC_INVOKE_AUTH_VERSION=$(python tools/prepare_checks.py --invoke-version) agent"]
    assert all(set(step) == {"run"} for step in job["steps"] if "run" in step)


def test_cli_exposes_supplied_interface_without_network(tmp_path):
    import subprocess
    result = subprocess.run([sys.executable, str(REPO / "tools/check_candidate.py"), "--help"],
                            check=True, capture_output=True, text=True)
    for option in ("--selection", "--sidecar-binary", "--sidecar-sha256"):
        assert option in result.stdout
