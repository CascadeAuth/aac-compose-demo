"""Resolve once, fail closed and retain current companion identities."""
import json
from types import SimpleNamespace

import pytest
import components


def test_current_selection_resolves_all_packages_and_exact_images(monkeypatch):
    seen = []
    def fetch(url):
        seen.append(url)
        if url == components.SITE:
            return {"sidecar": {"version": "v0.4.4", "image_digest": "sha256:" + "1"*64}}
        return {"info": {"version": "0.2.7"}, "urls": [{"packagetype": "bdist_wheel", "yanked": False,
            "url": "https://files.pythonhosted.org/example.whl", "digests": {"sha256": "3"*64}}]}
    monkeypatch.setattr(components, "read_json", fetch)
    monkeypatch.setattr(components, "image_digest", lambda reference: reference + "@sha256:" + "1"*64)
    record = components.resolve()
    assert set(record["packages"]) == set(components.PACKAGES)
    assert len(seen) == 4 and "latest" not in json.dumps(record)
    monkeypatch.setattr(components, "image_digest", lambda reference: reference + "@sha256:" + "2"*64)
    with pytest.raises(ValueError, match="differs"):
        components.resolve()


def test_prepare_reuses_run_without_resolving_new_versions(tmp_path, monkeypatch):
    record = {"packages": {"aac-cli": {"version": "0.2.7", "url": "https://files.pythonhosted.org/cli.whl", "sha256": "3"*64}},
              "sidecar": {}, "publisher": {}}
    monkeypatch.setattr(components.sys, "prefix", "active-venv")
    monkeypatch.setattr(components, "resolve", lambda: record)
    monkeypatch.setattr(components, "selected", lambda root: json.loads((root / ".local/components.json").read_text()))
    monkeypatch.setattr(components.subprocess, "check_output", lambda *a, **k: "4"*40)
    installs = []
    monkeypatch.setattr(components.subprocess, "run", lambda argv, **kw: installs.append(argv))
    components.prepare(tmp_path)
    before = (tmp_path / ".local/components.json").read_bytes()
    monkeypatch.setattr(components, "resolve", lambda: pytest.fail("silently re-resolved running demo"))
    components.prepare(tmp_path)
    assert len(installs) == 2 and installs[0] == installs[1]
    assert installs[0][-1].endswith("#sha256=" + "3"*64)
    assert (tmp_path / ".local/components.json").read_bytes() == before
