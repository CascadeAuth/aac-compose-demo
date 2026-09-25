# Measured runs

## Execution-graph acceptance — 2026-09-25 UTC

[aeg-20260925.json](aeg-20260925.json) records public `aac-aeg 0.1.0`, CLI 0.2.3,
the demo's sidecar v0.4.1 and publisher 0.2.3, against stage control plane 0.2.3.
The clean public installation passed 82 AEG interface tests. This source passes
33 offline tests and three selected live tests (6.40 seconds). The separate CA
lifecycle campaign was not repeated; expired leaf certificates were renewed
through the CLI before the run, retaining the existing tenants and CAs.

The first live campaign exposed a stale adversarial-test assertion that read
`root_token_id` from the application record. The public eight-field format has
`token_id`; the corrected fixture joins it to receiver telemetry for the expected
root and checks the task reference. Four offline cases accept the public format
and reject mismatched token/root/task evidence. The corrected live campaign
passed all six invalid chain-start cases and both receiver attacks, with positive
controls and no application invocation on the refused attacks.

The $8,000 unpaid reservation, fare-change refusal and fresh $9,500 authority
have separate recorded roots. Full, sender-only, receiver-only, hybrid and
central graphs render; local listing keeps repeated attempts distinct. A real
receiver-only forwarded root also renders through the hosted endpoint with
missing ancestors labeled. Hosted graphs contain no private order/reservation
fields. The full graph's details show both workloads, 10,000 → 8,000 caps and
expiry, PO #4143, the unpaid result, recorded `verified` grade and receipt source.

Ten generated artifacts have no declared external or relative asset URLs.
Chrome inspection over loopback HTTP observed no off-origin asset requests;
its automatic local favicon probe is recorded separately. Direct file-URL
navigation was not available to the browser automation. Existing ignored
minZoom/maxZoom diagnostics remain; graph rendering and details work. These
receipts describe observed evidence, not proof of payment or independent
verification of the business result. Old action logs were preserved before the
format transition.

## Supplied-material repeat-run correction — 2026-09-24 UTC

The renamed public main clone passed 22 offline tests and three live tests,
but repeating the supplied-material test found a harness error: it passed
first-time material-import flags to `aac init` for an existing `book-supplied`
slot. CLI 0.2.2 correctly refused to replace that material.

[reservation-repeat-20260924.json](reservation-repeat-20260924.json) records the
test-only fix at `4ff7c622d0f0e4083bd26aca0412ae6d736eda77`: renew an existing
slot, then apply its configuration, and restore the normal booking slot even
when setup fails. All 25 offline tests pass, including fresh/repeated setup and
controlled setup-failure restoration. Two consecutive live supplied-material
runs against the same existing slot passed in 48.96 and 51.23 seconds, each
including three verified reservations and three cross-tenant refusal campaigns.
The application, sidecar and original historical receipts are unchanged.

## Two-tenant reservation acceptance — 2026-09-24 UTC

[reservation-20260924.json](reservation-20260924.json) records implementation
commit `0e45df5820a74d65eae864a41726b11b09981eae`, public CLI 0.2.2,
sidecar v0.4.1, publisher 0.2.3, exact image digests and actual signed receipts.
The macOS arm64 stage campaign passed 22 offline tests and all four live tests
(140.23 seconds), including 63 successful commands and nine cross-tenant
adversarial campaigns during configuration/certificate maintenance.

The recorded checks cover the $8,000 unpaid reservation with the sender's
verified receipt grade, separate fare-change decline and fresh $9,500 authority,
six invalid starts across both aliases, local/forced widening and wrong presenter
with successful controls. Local widening is combined with the released Go
instrumented tests proving zero outgoing proof-signing calls; those tested
runtime files are unchanged from v0.4.1. Both tenants' leaf/CA renewals and
explicit peer trust refresh passed, as did replacement in a supplied-material
slot for the same booking workload. The test issuer was the CLI's development
issuer; no production issuer qualification is claimed.

A clean source archive of that commit, without Git/private coordination files,
installed its test dependencies from public PyPI and passed 22 offline tests.
With an empty Docker credential configuration it started the stacks and passed
the two positive/adversarial live tests (3.35 seconds), using the already
authorized test tenant material. Anonymous registry reads confirmed both public
image manifests. This is prepublication consumer evidence: the renamed public
clone, final public documentation and release closeout remain pending.

The external-review response adds documentation and a wire-profile docstring
after this measurement. The JSON source hashes remain the original measured
bytes at `0e45df5820a74d65eae864a41726b11b09981eae`; the fixture's executable
logic is unchanged. Do not replace historical hashes with later source hashes.

## Historical one-agent measurements

Real runs of this starter against the AAC stage service. Nothing in these
files is secret: identifiers, outcomes and durations only.

The Ubuntu amd64 run on 2026-09-18 used starter commit
`f468dbb1a9869ecf3b146602df47630b117ba7e4`, aac-cli 0.2.0 and sidecar v0.3.1.

## Component versions used in the 2026-09-18 measurement

| Component | Measured version |
|---|---|
| AAC sidecar image | `v0.3.1` |
| Trust-anchor publisher image | `0.2.3` |
| `aac-invoke-auth` (in the agent image) | `0.1.2` |
| `aac-cli` | `0.2.0` |

These versions identify this test run; they are not a compatibility limit.
The snapshot stays tied to the measured commit when the starter's dependencies
change. Exact image digests and tool versions are in the run record below.

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

## Measurements from 2026-09-14

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
