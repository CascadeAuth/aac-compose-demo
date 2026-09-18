# Measured runs

Real runs of this starter against the AAC stage service. Nothing in these
files is secret: identifiers, outcomes and durations only.

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
