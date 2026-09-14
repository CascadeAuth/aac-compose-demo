# AAC Compose starter

Run an Agent Authority Cloud (AAC) workload on your own machine in four steps:
install the AAC command-line tool, let it register your developer tenant and
generate everything one workload needs, start the stack with Docker Compose,
and run one complete authorized workflow.

AAC lets an organisation's AI agents and services prove, on every request,
which tenant they belong to and what they were authorised to do. Each workload
runs beside an **AAC sidecar** that signs what goes out and verifies what
comes in against public trust material the tenant publishes. This starter is
the tenant-local half of that picture, running on your machine:

```text
your machine                                          AAC stage (hosted)
┌──────────────────────────────────────────────┐
│ agent  ───── 127.0.0.1:8000 ─────┐            │      api.stage.cascadeauth.dev
│   your sample workload           │            │   ◄── registration, sign-in,
│                                  ▼            │       workload projection
│ sidecar  127.0.0.1:8080 (local API)           │
│          127.0.0.1:9443 (TLS, originator)  ───┼──►  trust.stage.cascadeauth.dev
│   verifies, delegates, settles, keeps evidence│   ◄── published root keys and
│                                               │       CA certificates
│ publisher ────────────────────────────────────┼──►  (uploaded by the publisher)
│   signs and uploads your PUBLIC trust material│
└──────────────────────────────────────────────┘
```

The AAC control plane is the hosted stage service. Nothing here runs, builds
or replaces it, and nothing here builds a sidecar: the sidecar and publisher
are the published images, pulled as they are.

## Before you start

| You need | Notes |
|---|---|
| Docker with Compose v2 | Docker Desktop on macOS, or Docker Engine plus the `docker compose` plugin on Linux. Run everything as a normal user, not root. |
| Python 3.10 or newer | Only for the AAC command-line tool (`aac-cli`). |
| A GitHub or Google account | Registration signs you in with it; that identity becomes your tenant's first administrator. |
| Bash and Git | The `starter` script is plain Bash and runs on macOS's own Bash 3.2. |
| Outbound HTTPS | To `docker.io`, `ghcr.io`, `pypi.org`, `api.stage.cascadeauth.dev`, `trust.stage.cascadeauth.dev` and your sign-in provider. No inbound ports are opened; nothing is published on the host. |

Everything the setup generates is **development material** for one local
workload: a seven-day development CA and one-day certificates, kept under
`~/.aac/` with mode 0600. It does not qualify for production, whatever the
tenant's domain. The stage service is a developer-beta environment, not a
production service.

## The four steps

### 1. Install the CLI and clone this repository

```bash
python3 -m venv ~/.aac-tools
. ~/.aac-tools/bin/activate
pip install 'aac-cli==0.1.5'
git clone https://github.com/CascadeAuth/aac-compose-starter.git
cd aac-compose-starter
```

### 2. Guided setup

```bash
./starter setup
```

The script asks for a display name and a contact address for your tenant and
whether to sign in with GitHub or Google, then hands over to `aac init`,
which does the work in five numbered steps and asks once before creating
the tenant, because a tenant is permanent:

1. registers the developer tenant (first browser sign-in);
2. opens a tenant-admin session (a second browser sign-in today);
3. takes the trust domain AAC assigns to the tenant
   (`<tenant-id>.tenants.stage.cascadeauth.dev`, no DNS work on your side);
4. registers the sample workload `spiffe://<trust-domain>/demo/agent`;
5. generates the keys and certificates and writes the sidecar configuration,
   the publisher environment and the Compose variable file.

Then the script pulls the sidecar and publisher images and builds the sample
agent image. The CLI's page on PyPI describes every file it created, where
it lives and what to back up: <https://pypi.org/project/aac-cli/>.

Running `./starter setup` again is safe. It renews expired development
certificates through the CLI, reports a complete workspace, or names the
exact problem. It never re-registers a tenant and never overwrites a key.

### 3. Start

```bash
./starter up
```

Starts the agent, the sidecar (joined to the agent's network namespace) and
the publisher, waits until the sidecar reports ready, then waits until the
public trust material the publisher uploaded is visible at the trust URL.

### 4. Exercise

```bash
./starter exercise
```

Runs the example client once, inside the agent's network namespace, and
prints a summary like this:

```json
{
  "task_ref": "starter-052b1552-…",
  "root_token_id": "cc7d6f3f…",
  "native_delivery": "delivered",
  "a2a_dispatch_id": "b146c0af-…",
  "a2a_retry": "same response bytes",
  "durations_ms": {"mint_to_settle": 4, "a2a": 4, "a2a_retry": 1},
  "local_evidence": {
    "events_for_root": ["mint:success", "receive:success", "respond:success", "dispatch:success"],
    "terminal_attestation_present": true
  }
}
```

What that proves, in order:

* **mint** — the client asked the sidecar to create a root authority for a
  synthetic task under the configured class of action `demo_verify`;
* **delegate** — the sidecar invoked the agent, which returned a `forward`
  decision to the destination `self_receive` with a narrower restriction
  (the same task reference), never a wider one;
* **receive** — the sidecar verified the delegated request as a receiver:
  signature chain, workload identity, recipient and replay protection;
* **settle** — the agent returned `settle`; the sidecar signed a terminal
  attestation, which the client found in the local evidence file;
* **A2A** — one unary agent-to-agent request went through the sidecar and
  was answered by the agent; the identical retry, same dispatch id and same
  bytes, returned the retained result instead of running again.

Every call the sidecar makes to the agent is signed with the pairing secret
both read; `./starter check` shows that an unsigned or wrongly signed call is
refused with HTTP 401 before any handler runs.

## What was measured

Timings are measured, not promised; they depend on your network and your
sign-in speed. `./starter status` prints the timings of your own runs.

| Environment | Guided setup (`aac init`, two browser sign-ins included) | Image download and build | Start until ready | Trust visible | Exercise | First authenticated success |
|---|---|---|---|---|---|---|
| Ubuntu 24.04 VM, arm64, Docker Engine 29.1, Compose 2.40 — fresh machine, new tenant | 247 s | 21 s (cold) | 6–7 s | 0–1 s | 1 s | about 4.6 minutes, sign-ins included |
| macOS 15, Apple silicon, Docker Desktop 29.7, Compose 5.5 — existing tenant, repeat runs | 0–3 s (already complete) | 13 s with cached images; the cold pull of the two images took 6–7 minutes on that network | 2–7 s | 0–1 s | 0–1 s | under 30 s |

The numbers come from `docs/evidence/` (the live test harness in `tests/live/`
writes one file per platform, and the VM's complete timing log is beside it).
Sign-in time is yours: the guided-setup figure is dominated by the two
browser sign-ins, and the download figure by your connection to the
registries.

## Running it again

The tenant, its assigned domain, the workload identity and every credential
are created once and reused. `./starter down` removes the containers and
nothing else. `./starter up` after that, a container recreation or a
rebuilt agent image all start with the same identities; the A2A retained
results survive because they live in the workspace's `state/` directory,
not in a container. Try it:

```bash
./starter down
./starter up
./starter retry      # resends the last A2A dispatch: same bytes, from retained state
```

Two things do **not** survive a restart, by design:

* The sidecar's **replay protection** in the Basic profile is process-local
  memory. A restart forgets which proofs it has seen; that is the documented
  limit of Basic. Retained A2A results are separate and do survive.
* The **one-day certificates** expire. `./starter up` refuses to start with
  expired material and points at the fix; `./starter setup` renews them
  through `aac workspace renew` (the development CA is renewed weekly, and
  the publisher then uploads the new CA certificate at its next start).

## When something is missing

`./starter status` shows what exists, what expired and the next command,
straight from the CLI. Two cases deserve a note:

* **The tenant API key is gone** (`missing_files` lists `credentials/<tenant-id>`).
  Restore the protected copy you kept, or issue a new one with
  `aac tenant reissue-api-key --profile stage`. Only a hash of the key exists
  on the server, so a lost key is replaced, never recovered.
* **A new computer.** The CLI's PyPI page has the procedure ("Setting up
  aac-cli on a new computer"); it needs the tenant API key and the tenant
  directory from your backup, and a new workspace name.

Nothing in this repository registers a tenant on its own. A second tenant is
a deliberate choice of another profile name:

```bash
AAC_STARTER_PROFILE=other-tenant ./starter setup
```

## What is running

| Service | Image | Runs as | Reads | Writes |
|---|---|---|---|---|
| `agent` | built here from `agent/Dockerfile` (Python 3.12, `aac-invoke-auth[fastapi]`) | you | `pair/` (pairing secret, development CA certificate) | nothing |
| `sidecar` | `docker.io/cascadeauth/aac-sidecar:v0.2.0` | you | `sidecar-config.yaml`, `pki/`, the pairing secret, the tenant API key | `state/` (local evidence, retained A2A results) |
| `publisher` | `ghcr.io/cascadeauth/aac-trust-anchor-publisher:0.2.3` | you | the tenant-admin private key, `root-keys/`, `spiffe-bundle/` (public halves) | nothing locally; uploads to AAC |
| `client` | the agent image | you | `pair/`, `state/` (read-only) | `.starter/exercise/` in this checkout |

All containers run with a read-only root file system, no capabilities and no
published ports. The sidecar shares the agent's network namespace, so the
rendered configuration's `127.0.0.1` addresses hold as they would in a
production pod; the loopback API on 8080 and the TLS listener on 9443 are
reachable only from inside that namespace. Containers run as your user so
the CLI's private files can stay mode 0600.

The development CA **private** key (`ca/dev-ca.key`) is never mounted into
any container. The publisher receives public keys and certificates plus the
tenant-admin signing key it needs to sign uploads; the sidecar receives the
workload's private material; the agent receives only the pairing secret.

## Make it your agent

`agent/agent.py` is deliberately small. Replace `decide` with your business
policy, keep the middleware and the two route names (`/invoke`, `/a2a/v1`),
which the sidecar relies on, then:

```bash
./starter build
./starter up
./starter exercise
```

The decision your agent returns is what AAC executes: `forward` names a
destination from the sidecar configuration and may only narrow the
authority; `settle` finishes the task and produces the signed attestation;
`refuse` stops it. A workload in another language implements the same
pairing authentication the `aac-invoke-auth` package documents.

## Commands

| Command | What it does |
|---|---|
| `./starter setup` | Guided setup through `aac init`; renews expired certificates; pulls and builds images |
| `./starter up` | Starts the stack, waits for readiness and for the published trust material |
| `./starter exercise` | One complete workflow with local evidence and the A2A retry |
| `./starter check` | Readiness, refusal probes, published trust material |
| `./starter status` | The CLI's workspace report, running containers, measured timings |
| `./starter retry` | Resends the last A2A dispatch and checks the retained result |
| `./starter build` | Rebuilds the sample agent image after you edit `agent/` |
| `./starter logs [service]` | Follows the containers' logs |
| `./starter down` | Stops and removes the containers; keeps the tenant, workspace and state |
| `./starter clean` | Also removes the local agent image and `.starter/`; never touches `~/.aac` |

Environment variables: `AAC_STARTER_PROFILE` (CLI profile, default `stage`),
`AAC_STARTER_WORKSPACE` (default `starter`), `AAC_CLI_HOME` (relocates
`~/.aac`), and the three stage URLs `AAC_STARTER_ADMIN_URL`,
`AAC_STARTER_DATA_PLANE_URL`, `AAC_STARTER_TRUST_URL`.

## Versions

| Component | Version | Where it is pinned |
|---|---|---|
| AAC sidecar image | `v0.2.0` | `compose.yaml` (`AAC_SIDECAR_VERSION`) |
| Trust-anchor publisher image | `0.2.3` | `compose.yaml` (`AAC_PUBLISHER_VERSION`) |
| `aac-invoke-auth` (in the agent image) | `0.1.2` | `compose.yaml` (`AAC_INVOKE_AUTH_VERSION`), `agent/Dockerfile` |
| `aac-cli` (on your machine) | `0.1.5` (0.1.4 or newer works) | `tests/requirements.txt`; the script checks the floor |

The four move together: a starter release is a tag on the commit whose table
names the versions it was verified with.

## Supported environments

| Environment | Status |
|---|---|
| Linux arm64 (Ubuntu 24.04, Docker Engine 29.1, Compose 2.40) | Measured: fresh machine, new tenant, full flow |
| macOS on Apple silicon (Docker Desktop 29.7, Compose 5.5) | Measured: repeat runs, restart, recreate, rebuild, renew, missing credential |
| Linux amd64 | Same multi-architecture images and the same user mapping; not measured yet |
| Windows | Not supported by this starter (no claim) |

## Troubleshooting

* `error from registry: denied` while pulling — a stale registry login on
  your machine; `docker logout ghcr.io` (or `docker logout`) and retry. Both
  images are public and need no account.
* `./starter up` says the workspace is not ready — read the CLI report it
  prints; the `next_command` line is the fix.
* The trust material never becomes visible — `./starter logs publisher`
  shows each upload attempt and the reason it was refused.
* An agent HTTP 401 in the sidecar's logs — the two processes read different
  pairing secrets; `./starter status` shows the file. Never disable the check.

## License

Apache-2.0 (see `LICENSE`). The sidecar image you pull is distributed under
its own developer-beta license, shown on its Docker Hub page.
