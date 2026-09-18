# AAC Compose starter

Run an Agent Authority Cloud (AAC) workload on your own machine and watch the
pieces of AAC work together. One command registers your developer tenant and
creates everything a workload needs; Docker Compose starts your agent beside
an AAC sidecar; one task then shows, step by step, what the sidecar and your
agent did with it.

This is a teaching example: small, readable, and deliberately free of
production concerns (see "What this example leaves out" below).

## How the pieces fit

```text
 your machine (Docker)                                 AAC stage (hosted)
┌───────────────────────────────────────────────┐
│ client ──start a task──▶ sidecar ◀────────────┼──── api.stage.cascadeauth.dev
│                           │  ▲                │     your tenant and your
│               signed call │  │ decision       │     workload's registration
│                           ▼  │                │
│                          agent                │
│                                               │
│ publisher ──your public keys──────────────────┼───▶ trust.stage.cascadeauth.dev
└───────────────────────────────────────────────┘     where sidecars check what
                                                       yours signed
```

* **`aac`**, the AAC command-line tool, registers your tenant and creates the
  keys, certificates and sidecar configuration. Nothing in this repository
  creates or edits them.
* **The sidecar** (`docker.io/cascadeauth/aac-sidecar`) runs beside your
  agent and does the AAC work: it mints and checks authority, calls your
  agent, carries out its decisions and signs the results.
* **Your agent** (`agent/agent.py`) only decides: forward the work, settle
  it, or refuse it.
* **The publisher** (`ghcr.io/cascadeauth/aac-trust-anchor-publisher`)
  uploads your public keys to AAC, so that sidecars can check what yours
  signs.
* **The client** (`agent/client.py`) starts one task and prints what
  happened.

## What you need

Choose where to run the commands:

| Your computer | Where to run the starter |
|---|---|
| Windows | Inside an Ubuntu 24.04 or newer virtual machine. Native Windows is not supported. |
| macOS | Inside an Ubuntu VM, or directly on macOS. |
| Linux | Directly on Linux. |

For a VM, we recommend [Multipass](https://canonical.com/multipass), the setup
used for the Ubuntu VM measurement below. WSL2 with Ubuntu is another option
on Windows, but has not been tested with this starter. Install Python, Git
and Docker Engine inside the VM, and run all the steps there.

* Docker with Compose v2: Docker Desktop on macOS, or Docker Engine on Linux.
  Run everything as your normal user.
* Python 3.10 or newer, for the `aac` command-line tool.
* A GitHub or Google account. Registering signs you in, and that account
  becomes your tenant's administrator.

## Run it

### 1. Install the CLI and get the code

```bash
python3 -m venv ~/.aac-tools
. ~/.aac-tools/bin/activate
pip install 'aac-cli==0.2.0'
git clone https://github.com/CascadeAuth/aac-compose-starter.git
cd aac-compose-starter
```

### 2. Set up your tenant

```bash
./starter setup --display-name "Your team" --contact you@example.com --idp github
```

`./starter setup` runs `aac init` against the AAC stage service. It asks once
before creating your tenant, because a tenant is permanent, and opens your
browser twice to sign in. Then it:

1. registers your developer tenant;
2. takes the trust domain AAC assigns to it,
   `<tenant-id>.tenants.stage.cascadeauth.dev`;
3. registers the sample workload `spiffe://<trust-domain>/demo/agent`;
4. creates the development keys and certificates and writes the sidecar
   configuration, all under `~/.aac/`;

and finally downloads the sidecar and publisher images. Once setup is complete,
`./starter setup` needs no options: it refreshes the generated settings while
keeping your tenant and keys.

One CLI profile names your tenant; one agent folder holds this workload's
files, by default `~/.aac/agents/starter/`:

| Generated path | Used by |
|---|---|
| `sidecar/` | The sidecar, mounted at `/etc/aac/pki`. |
| `agent/` | The agent and client, mounted at `/run/secrets`: `pairing.secret` and `ca.crt`. The sidecar also reads the pairing secret. |
| `keep/` | You only: the development CA private key. Never mounted in a container; absent when you supply certificates. |
| `state/` | The sidecar's runtime records; the client reads `telemetry.jsonl`. |
| `sidecar-config.yaml`, `compose.env`, `record.json` | The CLI's generated settings and setup record. |

The publisher reads your tenant's public material and admin signing key under
`~/.aac/tenants/<tenant-id>/`. The sidecar also reads the tenant API key from
`~/.aac/credentials/<tenant-id>`. The CLI writes every file; the starter only
mounts them.

### 3. Start

```bash
./starter up
```

This builds the agent image and starts the agent, the sidecar and the
publisher, then waits for two things, saying before each which it is waiting
for:

1. **The sidecar is ready**: it has loaded its identity, keys and
   configuration. It gives up after 90 seconds.
2. **AAC serves your public keys.** The publisher signs your public root key
   and development CA certificate with your tenant-admin key and uploads them
   to AAC, which serves them at `https://trust.stage.cascadeauth.dev`. Every
   sidecar that checks what yours signs, yours included, reads them there.
   `./starter up` has the CLI read them back from that address, and gives up
   after five minutes. After the first start they are already there, so this
   takes a moment.

### 4. Run a task

```bash
./starter exercise
```

You should see something like:

```text
mint      the sidecar minted root authority 35c9e381335c... for task starter-425868e6, restricted to {"action": "dev_noop", "valid_until": 1789428108}
agent     the sidecar called your agent (delivered); its answer: {"action": "forward", "additional_predicates": {"task_ref": "starter-425868e6"}, "destination": "self_receive", "payload": {"step": "settle"}}
dispatch  the sidecar handed the next step to self_receive, restricted to action:dev_noop,task_ref:starter-425868e6,valid_until:1789427808
receive   the sidecar verified that step as its receiver, presented by spiffe://tnt-97d0232e-….tenants.stage.cascadeauth.dev/demo/agent
respond   your agent decided settle; the sidecar signed the terminal attestation eyJhbGciOiJFZERTQSIs...
a2a       your agent's request went through the sidecar to self_a2a: dispatched
refused   a call to your agent without the pairing signature: HTTP 401
```

## How it works

Each line is one hand-off. The first two come from the sidecar's answer to
the client; `dispatch`, `receive` and `respond` come from the sidecar's own
record of events, `~/.aac/agents/starter/state/telemetry.jsonl` (one JSON
object per line, named by `event_type`), where you can find the same values.

**mint.** `start_task` in `agent/client.py` asks the sidecar to start a task
for a person (a synthetic one here) under the class of action `demo_verify`.
The sidecar mints a *root authority*: a signed token that says who the work
is for and what it may do. Its restrictions, the action `dev_noop` and an
expiry time, come from that class of action in the sidecar configuration
`aac init` wrote.

**agent.** The sidecar calls your agent's `/invoke` with that authority,
signed with the pairing secret the two share, and returns your agent's answer
to the client. `decide` in `agent/agent.py` answers `forward` to the
destination `self_receive` and adds a restriction, `task_ref`. The sidecar
answers the client at this point and carries out the forward afterwards; the
client follows it in the record.

**dispatch.** The sidecar mints the delegated step and sends it to
`self_receive`. Compare its restrictions with the root's: one more
restriction and an earlier expiry. Authority only narrows as it is passed on.
The sidecar writes this record when the step has been answered.

**receive.** `self_receive` is this same agent, so the delegated step comes
back to the sidecar, which now checks it as its receiver: the signature chain
back to your root key, the workload that presented it (its SPIFFE ID,
certified by your development CA), that the step is meant for this workload,
and that it has not been seen before. The root key and CA it checks against
are the ones the publisher uploaded to AAC.

**respond.** The sidecar hands the verified step to your agent, which answers
`settle`. The sidecar signs a *terminal attestation*: a receipt that the task
finished under this authority.

**a2a.** `send_a2a_request` shows the other direction, an agent-to-agent
request that your agent sends (the client plays that part). The request is
signed with the pairing secret; the sidecar mints authority for it and
delivers it to `self_a2a`, again this same agent, through its A2A route.

**refused.** A call to your agent without the pairing signature is turned
away before your code runs. Only the sidecar, after it has checked AAC
authority, reaches `decide`.

## Make it your own

Change `decide` in `agent/agent.py`, then:

```bash
./starter up
./starter exercise
```

`./starter up` rebuilds the agent image every time. The exercise shows only
what happened: if your agent answers `refuse`, the `agent` line shows the
refusal and nothing is forwarded. At the first step an agent may answer only
`forward` or `refuse` (`settle` finishes a step it has received); the sidecar
reports any other answer as a failed delivery, with the reason in the `agent`
line.

## Stop and start again

```bash
./starter down
./starter up
```

`down` removes the containers only. Your tenant, its trust domain, the
workload identity and every key stay in `~/.aac/`, and the next `up` uses
them again.

## What this example leaves out

This example shows how AAC works; it is not a deployment recipe. It leaves
out:

* **Production hardening** of containers and secrets, such as read-only file
  systems, dropped capabilities and a secret store. The AAC sidecar
  documentation covers deployment.
* **Replay protection across restarts.** The sidecar here uses the Basic
  replay profile, which remembers the proofs it has seen in memory, so a
  restart forgets them. Production uses the Shared durable profile.
* **Retries and failure handling.** When something fails, the message from
  Docker, the CLI or the sidecar is what you see.
* **More than one tenant or workload at a time**, and native Windows.
* **A production certificate lifecycle.** The default run uses development
  material: leaf certificates last one day and the development CA seven.
  The CLI’s two certificate cases are described below.

## From this example to a network of agents

| | Agent 1 (starts the task) | Agents 2–100 (receive and forward) |
|---|---|---|
| The sidecar | yes | yes |
| An identity: a SPIFFE ID with a certificate and key from the tenant's own issuer, chaining to the CA the tenant publishes | yes | yes |
| The workload registered with AAC (`aac tenant add-workload --spiffe-id …`, one per agent, scriptable) | yes | yes |
| A root signing key (mints the chain's first authority) | yes | no — a forwarding sidecar narrows the authority it received and signs its proof with its own identity key |
| A receipt-signing (terminal attestation) key | if it finishes tasks | agent 100, which finishes the task |
| The sidecar config, the pairing secret shared with its agent, the tenant API key its sidecar uses to reach AAC | yes | yes |

Once per tenant, not per agent: tenant registration and admin key; one publisher publishing the tenant's CA and the originators' root public keys (here only agent 1's). Worked example: a chain of 100 agents where agent n calls agent n+1.

## Two ways to get your agent’s certificates

The steps above use development material. The CLI also accepts certificates
your own issuer signed; pass its flags through `./starter setup`. Both cases
use the same container mounts. Supplying certificates alone does not make
this teaching example a production deployment.

<!-- material-cases:start -->

<!-- Generated from aac_cli/material_cases.py. Do not edit by hand. -->

### The CLI creates a development CA

The laptop case. The CLI creates a certificate authority on this machine and signs the agent's identity, receipt and HTTPS certificates with it.

**Flags.** No flags are needed. To reuse a development CA across agents, pass `--ca-key-file` and `--ca-cert-file` together; neither one alone.

**Keys and signatures.** The CA and the two identity keys are Ed25519; the HTTPS key is EC P-256.

**The CLI** creates a 7-day certificate authority and keeps its private key in the agent's keep/ folder; issues the workload, receipt and HTTPS certificates; publishes the CA certificate as a trust anchor named `<agent>-dev-ca`.

**The CLI does not** ask you for anything from your own certificate authority.

**Renewal.** `aac agent renew --agent <name>` issues fresh certificates from the same CA.

### I bring my own CA

The production case. Your own issuer has already signed the agent's certificates, and your CA private key never reaches this machine.

**Flags.** All seven together: `--workload-cert-file`, `--terminal-cert-file` and `--tls-cert-file`, each with its key file (`--workload-key-file`, `--terminal-key-file`, `--tls-key-file`), plus `--ca-cert-file`. Never `--ca-key-file`: the CLI does not want your CA key.

**Keys and signatures.** Your CA's key must be Ed25519 or EC P-256, and it must have signed each certificate with Ed25519 or ECDSA-with-SHA-256. The two identity keys may be Ed25519 or EC P-256; the HTTPS key must be EC P-256. RSA is not supported: the sidecar cannot verify against it.

**The CLI** checks each certificate against its key, its issuer and its validity window; registers the workload and writes the settings files and the pairing secret; publishes your CA certificate as a trust anchor named `<agent>-ca`.

**The CLI does not** create a certificate authority; issue any certificate; ask for, read or store your CA private key.

**Renewal.** `aac agent renew --agent <name>` cannot reissue what it did not sign: it takes the replacements your issuer produced.

<!-- material-cases:end -->

## Troubleshooting

* After a day or more the development certificates have expired, and the
  sidecar cannot use them. Run `aac agent renew --agent starter`,
  then `./starter up`.
* `error from registry: denied` while downloading: a stale registry login.
  Run `docker logout ghcr.io` (or `docker logout`); both images are public.
* The image download never finishes: Docker's credential helper is not
  answering. `printf 'https://index.docker.io/v1/' | docker-credential-desktop get`
  should answer at once on Docker Desktop; if it hangs, restart Docker
  Desktop.
* `./starter up` gives up waiting for your public keys after five minutes:
  `docker logs aac-starter-publisher-1` shows each upload attempt.
* Anything else the sidecar did: `docker logs aac-starter-sidecar-1`.
* To see what `aac init` created and whether it is complete:
  `aac agent status --agent starter`.
* Another tenant or agent: set `AAC_STARTER_PROFILE` and
  `AAC_STARTER_AGENT` to new names for every `./starter` command (an
  agent belongs to the profile that created it).

## What was measured

Timings from the live test in `tests/live/`, recorded in `docs/evidence/`;
they are measurements, not a promise.

On 2026-09-18, Ubuntu amd64 ran starter commit `f468dbb` with aac-cli 0.2.0
and sidecar v0.3.1. All five live tests passed: the full exercise, unsigned
call rejection, and the same identity after stopping and starting again.

| Environment | `./starter setup`, tenant in place | `./starter up` | `./starter exercise` |
|---|---|---|---|
| Ubuntu 24.04.4, amd64, EC2 t3.medium, Docker Engine 29.8, Compose 5.5 | 1.2 s | 13.4 s with the first agent image build; 3.2 s after `./starter down` | 1.3 s |

Fresh setup took 215.25 s including both browser sign-ins and the cold
sidecar/publisher downloads. Fresh setup, first startup and the exercise
added up to about 3.8 minutes. This excludes host provisioning, CLI
installation, code transfer, offline checks and idle gaps between commands.
See [the evidence notes](docs/evidence/README.md) for tool/image versions,
host access details and timing limitations. The temporary host and its
supporting resources were destroyed after the evidence was retrieved.

The two measurements below are from 2026-09-14 at starter commit `d76dd64`,
with aac-cli 0.1.5 and sidecar v0.2.0. They do not measure the versions
pinned below.

| Environment | `./starter setup`, tenant in place | `./starter up` | `./starter exercise` |
|---|---|---|---|
| Ubuntu 24.04 VM, arm64, Docker Engine 29.1, Compose 2.40 | 1.5 s | 12.3 s replacing running containers; 1.9 s after `./starter down` | 0.9 s |
| macOS 26, Apple silicon, Docker Desktop 29.7, Compose 5.5 | 1.9 s | 5.7 s replacing running containers; 1.7 s after `./starter down` | 0.8 s |

On that fresh Ubuntu arm64 VM with a new tenant, the steps added up to about
4.6 minutes, 247 s of it `aac init` with both browser sign-ins.

## Versions

| Component | Version |
|---|---|
| AAC sidecar image | `v0.3.1` |
| Trust-anchor publisher image | `0.2.3` |
| `aac-invoke-auth` (in the agent image) | `0.1.2` |
| `aac-cli` (on your machine) | `0.2.0` |

## License

Apache-2.0 (see `LICENSE`). The sidecar image you pull is distributed under
its own developer-beta license, shown on its Docker Hub page.
