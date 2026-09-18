# Measured runs

Real runs of this starter against the AAC stage service. Nothing in these
files is secret: identifiers, outcomes and durations only.

The Ubuntu amd64 run on 2026-09-18 used starter commit
`f468dbb1a9869ecf3b146602df47630b117ba7e4`, aac-cli 0.2.0 and sidecar v0.3.1:

* [`linux-x86_64-20260918T222443Z-f468dbb.json`](linux-x86_64-20260918T222443Z-f468dbb.json) records the five passing live tests' command
  durations, actual exercise output and unchanged identity after restart.
* [`linux-x86_64-20260918-run.json`](linux-x86_64-20260918-run.json) records fresh setup, exact CLI/image/AMI
  and tool versions, test outcomes, evidence retrieval checksum and teardown.

Fresh setup took 215.25 s, including both browser sign-ins and the first
sidecar/publisher downloads. First startup took 13.4 s including the first
agent image build, sidecar readiness and public-key readiness; exercise took
1.3 s. Their sum is about 230 s, excluding idle gaps between commands and
the preparation steps (host provisioning, code transfer, CLI installation and
offline checks). The clock includes human sign-in time, so it is not a
service-latency measurement.

The EC2 host used Session Manager and required `sudo docker`. A temporary
command outside the checkout preserved the starter's UID/GID variables when
invoking Docker with sudo; the CLI and containers ran as user 1001:1001.
The starter checkout stayed clean. The host used standard CPU credits,
which can throttle sustained load. Evidence was copied out and its checksum
verified before full infrastructure teardown; the instance, disk, network
and IAM resources were confirmed gone. Shared Terraform state history remains.

The macOS and Ubuntu arm64 JSON files were measured on 2026-09-14 at
`d76dd641564aa6c4ebd18fc0cd6fab73f529838b`, with aac-cli 0.1.5 and sidecar
v0.2.0. The first-run arm64 log is from the same date and versions. These
files are retained as measurements of that starter, not the current pins.

| File | What it is |
|---|---|
| `darwin-arm64.json` | The live test (`tests/live/`) on macOS, Apple silicon, Docker Desktop, with an existing tenant: how long each `./starter` command took, what the exercise printed, and the commit it measured (`starter_commit`). |
| `linux-aarch64.json` | The same on an Ubuntu 24.04 arm64 virtual machine with Docker Engine, with the tenant that machine registered. |
| `first-run-linux-aarch64.txt` | The first lines of that virtual machine's timing log on the day it registered a new tenant: `aac init` with both browser sign-ins (247 s; the next line is a second run that found everything in place), the image download (18 s, after two of the three images had been pulled by hand), the start (6 s), the published keys (1 s) and the first task (0 s). A starter script of that time wrote the log; its setup, start and exercise did what `./starter setup`, `up` and `exercise` do. |

The cold download of the sidecar and publisher images on the macOS machine's
network was timed separately with `time docker pull` at 6 min 39 s and
6 min 42 s, a property of that network rather than of the images (12 MB and
233 MB).
