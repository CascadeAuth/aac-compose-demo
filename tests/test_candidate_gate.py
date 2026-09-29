"""A failed or mismatched consumer receipt stops the actual pre-upload command."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from conftest import REPO


def test_preupload_receipt_gate_blocks_failure_and_changed_candidate(tmp_path):
    artifact = tmp_path / "candidate.whl"; artifact.write_bytes(b"candidate-test-fixture")
    receipt = tmp_path / "receipt.json"
    record = {"passed": True, "candidate_revision": "a"*40,
              "candidate_artifacts": {artifact.name: hashlib.sha256(artifact.read_bytes()).hexdigest()}}
    command = [sys.executable, str(REPO / "tools/check_candidate.py"), "--verify", "--source", "a"*40,
               "--receipt", str(receipt), "--artifact", str(artifact)]
    receipt.write_text(json.dumps(record))
    assert subprocess.run(command, capture_output=True).returncode == 0
    for change in ({"passed": False}, {"candidate_revision": "b"*40},
                   {"candidate_artifacts": {artifact.name: "0"*64}}):
        receipt.write_text(json.dumps(record | change))
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode != 0 and ("consumer" in result.stderr or "artifact" in result.stderr)
    receipt.write_text(json.dumps(record)); artifact.write_bytes(b"changed-after-test")
    assert subprocess.run(command, capture_output=True).returncode != 0
