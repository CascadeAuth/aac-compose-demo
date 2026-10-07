#!/usr/bin/env python3
"""Bounded release gate: exact candidate + current public demo companions.

Runs only local test tenants/fixtures, never stage onboarding. A separate public
acceptance run is required after release. The receipt binds source, demo and
artifact identities; verify mode is called immediately before publisher upload.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import venv
import zipfile
from email.parser import BytesParser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import components


def digest(path):
    return hashlib.file_digest(path.open("rb"), "sha256").hexdigest()


def run(*argv, **kwargs):
    return subprocess.run(argv, check=True, **kwargs)


def verify(receipt, source, artifacts):
    record = json.loads(receipt.read_text())
    if not artifacts or {p.name for p in artifacts} != set(record["candidate_artifacts"]):
        raise ValueError("candidate artifact set differs from the demo consumer receipt")
    if record.get("passed") is not True or record["candidate_revision"] != source:
        raise ValueError("demo consumer did not pass for this candidate revision")
    for artifact in artifacts:
        if record["candidate_artifacts"].get(artifact.name) != digest(artifact):
            raise ValueError("candidate artifact differs from the demo consumer receipt")
    return record


def python_requirements(component, artifacts, current):
    packages = []
    candidate_version = None
    for name, metadata in current["packages"].items():
        if name != component:
            packages.append(components.package_spec(name, metadata))
    if component != "sidecar":
        wheels = [p for p in artifacts if p.suffix == ".whl"]
        if len(wheels) != 1:
            raise ValueError("exactly one candidate wheel is required")
        with zipfile.ZipFile(wheels[0]) as archive:
            metadata = BytesParser().parsebytes(archive.read(next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))))
        if metadata["Name"] != component:
            raise ValueError("candidate wheel belongs to a different component")
        candidate_version = metadata["Version"]
        packages.append(components.package_spec(component, {"url": wheels[0].resolve().as_uri(), "sha256": digest(wheels[0])}))
    deps = [line for line in (ROOT / "tests/requirements.txt").read_text().splitlines()
            if line and not line.startswith(("#", "aac-"))]
    return [*packages, *deps], candidate_version


def check(component, artifacts, receipt, source, *, selection=None,
          sidecar_binary=None, sidecar_sha256=None):
    if not artifacts or any(not path.is_file() for path in artifacts):
        raise ValueError("candidate artifacts are required")
    record = {"schema_version": 1, "passed": False, "component": component,
              "candidate_revision": source,
              "candidate_artifacts": {p.name: digest(p) for p in artifacts},
              "demo_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()}
    receipt.parent.mkdir(parents=True, exist_ok=True)
    try:
        if component == "sidecar" and (sidecar_binary is not None or sidecar_sha256 is not None):
            raise ValueError("sidecar candidates use their candidate artifact, not a supplied companion binary")
        if (sidecar_binary is None) != (sidecar_sha256 is None):
            raise ValueError("supply both --sidecar-binary and --sidecar-sha256")
        if sidecar_binary is not None:
            if digest(sidecar_binary) != sidecar_sha256:
                raise ValueError("supplied sidecar binary differs from the expected SHA256")
        if selection is not None:
            # Explicit pins must not silently fall back to registry discovery.
            current = components.load_selection(selection)
            record["selection_sha256"] = digest(selection)
            if component != "sidecar" and sidecar_binary is None:
                raise ValueError("a supplied selection requires a supplied sidecar binary for companion checks")
        elif component == "sidecar" or sidecar_binary is not None:
            current = components.resolve_packages()
        else:
            # PR3 migrates existing companion callers to the supplied interface.
            current = components.resolve()
        record["companions"] = current
        with tempfile.TemporaryDirectory(prefix="aac-demo-consumer-") as directory:
            work = Path(directory)
            venv.EnvBuilder(with_pip=True).create(work / "venv")
            python = work / "venv/bin/python"
            packages, version = python_requirements(component, artifacts, current)
            if version is not None:
                record["candidate_version"] = version
            run(str(python), "-m", "pip", "install", *packages)
            binary = (artifacts[0].resolve() if component == "sidecar" else
                      sidecar_binary.resolve() if sidecar_binary is not None else work / "aac-sidecar")
            record["sidecar_source"] = ("candidate" if component == "sidecar" else
                                        "supplied" if sidecar_binary is not None else "public-image")
            if component != "sidecar" and sidecar_binary is None:
                image = current["sidecar"]["image"]
                # Linux is the release-runner platform; local macOS callers can
                # supply a native sidecar candidate to exercise this same gate.
                if platform.system() != "Linux":
                    raise ValueError("companion container binary requires a Linux release runner")
                run("docker", "pull", image)
                container = subprocess.check_output(["docker", "create", image], text=True).strip()
                try:
                    run("docker", "cp", container + ":/aac-sidecar", str(binary))
                finally:
                    run("docker", "rm", container)
                binary.chmod(0o755)
            record["sidecar_binary_sha256"] = digest(binary)
            if sidecar_binary is not None and record["sidecar_binary_sha256"] != sidecar_sha256:
                raise ValueError("supplied sidecar binary differs from the expected SHA256")
            record["installed_packages"] = json.loads(subprocess.check_output(
                [str(python), "-m", "pip", "list", "--format", "json"], text=True))
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith("AAC_") and k not in ("PYTHONPATH", "PYTHONHOME")}
            env.update(AAC_COMPAT_BINARY=str(binary), PATH=str(python.parent) + os.pathsep + os.environ["PATH"])
            run(str(python), "-m", "pytest", "tests", "--ignore", "tests/live", "-q", cwd=ROOT, env=env)
            # Explicit path prevents an accidental rename/skip from silently
            # turning the real sidecar consumer into only unit tests.
            run(str(python), "-m", "pytest", "tests/compatibility/test_consumer.py", "-q", cwd=ROOT, env=env)
            record["passed"] = True
    finally:
        receipt.write_text(json.dumps(record, indent=2) + "\n")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", choices=(*components.PACKAGES, "sidecar"))
    parser.add_argument("--artifact", type=Path, action="append", default=[])
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--selection", type=Path, help="JSON with schema_version 1 and pinned packages")
    parser.add_argument("--sidecar-binary", type=Path, help="caller-verified native companion binary")
    parser.add_argument("--sidecar-sha256", help="expected SHA256 from the caller's verified release evidence")
    args = parser.parse_args()
    if args.verify:
        verify(args.receipt, args.source, args.artifact)
    else:
        if not args.component:
            parser.error("--component is required")
        check(args.component, args.artifact, args.receipt, args.source,
              selection=args.selection, sidecar_binary=args.sidecar_binary,
              sidecar_sha256=args.sidecar_sha256)


if __name__ == "__main__":
    main()
