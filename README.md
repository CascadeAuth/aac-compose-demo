# AAC: two tenants, one reservation made

Vantis Equity's trip-planner asks Tourfedia's booking workload to create a
**reservation**. Each fictional organization has its own AAC
tenant, assigned trust domain, CA, public trust publication and private keys.

Marc Sterling's approval is **simulated**: PO #4143, Austin to Shanghai,
departing 12 May, up to $10,000. Vantis's application signs the native chain-start
request and supplies that budget. T0 establishes origin; T1 carries $10,000,
the order reference and two hours of authority. The trip-planner narrows to
$8,000 and 30 minutes, addressed to Tourfedia. Tourfedia returns a signed
terminal receipt; Vantis verifies it against the expected identity and actual
chain root.

The example application creates a reservation result; supplier integration and
payment are omitted for clarity. Thirty minutes
limits the **authority**, not a guaranteed price hold. Returning a receipt is
not another delegation or another business agent.

## Requirements

macOS or Linux, Python 3.11+, Docker with Compose, and two stage developer
tenants you control. Registration requires interactive GitHub sign-in.
The two tenants can have the same human owner. A contact email is registration
metadata; it does not select your GitHub account.

| Public component | How it is supplied |
|---|---|
| [aac-cli on PyPI](https://pypi.org/project/aac-cli/) | Install in your host Python environment |
| [AAC sidecar on Docker Hub](https://hub.docker.com/r/cascadeauth/aac-sidecar/) | Compose pulls the selected immutable image |
| [Trust-anchor publisher on GHCR](https://github.com/orgs/CascadeAuth/packages/container/package/aac-trust-anchor-publisher) | Compose pulls the selected image |
| [aac-invoke-auth on PyPI](https://pypi.org/project/aac-invoke-auth/) | Installed inside the application image |
| [Python application image](https://hub.docker.com/_/python) | Application base image; host Python is also required for the CLI |
| [uvicorn](https://pypi.org/project/uvicorn/) / [httpx](https://pypi.org/project/httpx/) | Installed inside the application image |

Current AAC installation metadata is published in the
[released-component record](https://cascadeauth.github.io/aac-starter-guide/released-components.json).
The exact combination exercised by this demo remains in Compose, the Dockerfile,
test dependencies and [test receipts](docs/evidence/README.md). Component updates
must pass the demo's compatibility checks; changing a guide does not change a
recorded run or silently select a different container.

No private repository or AAC SDK is required. The applications build locally
from this public source. See the [AAC guide](https://cascadeauth.github.io/aac-starter-guide/)
for protocol/configuration reference and production deployment choices.

## 1. Install and declare each agent

```sh
git clone https://github.com/CascadeAuth/aac-compose-demo.git
cd aac-compose-demo
python3 -m venv .venv
. .venv/bin/activate
./demo prepare
mkdir -p .local
export AAC_CLI_HOME="$PWD/.local/aac"
cp config/trip-planner.yaml .local/trip-planner.yaml
cp config/booking.yaml .local/booking.yaml
```

Keep this environment variable in each terminal used for the demo. It gives
the demo its own CLI home and leaves your other profiles alone.

These are **operator-authored inputs**, supplied explicitly with
`--agent-config`. The CLI alone generates keys, certificates, publisher
configuration, `compose.env` and `sidecar-config.yaml`. Never hand-edit those
generated outputs or consume the private `record.json` schema.

The inputs select Basic in-memory replay protection with `dev_mode: false`.
Development-issued certificates do not require development exceptions.
Each pair shares its own loopback interface; the sidecars communicate over a
private Docker network using HTTPS names `trip-planner` and `booking`.
No host ports are published.

`./demo prepare` requires public aac-cli 0.2.7 or later and resolves current stable AAC package releases from PyPI and the
sidecar from the published release record, then resolves exact container digests.
It saves `.local/components.json` and installs the selected CLI in your active
virtual environment. Subsequent starts and maintenance reuse that file; they
never silently change a running demo. To start a new run with newer components,
stop the demo, retain the old receipt, and move the selection file aside before
running `./demo prepare` again. There is no mutable sidecar `latest` tag.

## 2. Register two tenants

Set your real contact addresses:

```sh
export VANTIS_CONTACT='you+vantis@example.com'
export TOURFEDIA_CONTACT='you+tourfedia@example.com'
aac init --profile vantis --agent trip-planner --agent-config .local/trip-planner.yaml --layout container --admin-url https://api.stage.cascadeauth.dev --data-plane-url https://api.stage.cascadeauth.dev --trust-url https://trust.stage.cascadeauth.dev --idp github --display-name 'Vantis Equity Demo' --contact "$VANTIS_CONTACT"
aac init --profile tourfedia --agent booking --agent-config .local/booking.yaml --layout container --admin-url https://api.stage.cascadeauth.dev --data-plane-url https://api.stage.cascadeauth.dev --trust-url https://trust.stage.cascadeauth.dev --idp github --display-name 'Tourfedia Demo' --contact "$TOURFEDIA_CONTACT"
```

Run interactively and acknowledge each permanent tenant registration. There
are two sign-ins per tenant: registration and administration. Use the same
GitHub account for both sign-ins of that tenant. A rerun reuses its registration;
it does not create another tenant. Noninteractive registration additionally
requires the explicit `--create-tenant` acknowledgement.

The assigned domains come from AAC; owning `tourfedia.com` is not a trust-domain
binding. Empty peer configuration is intentional during initial registration.

## 3. Explicitly trust and address the peer

Read the registered facts through supported CLI status output:

```sh
aac agent status --agent trip-planner --output json > .local/vantis-status.json
aac agent status --agent booking --output json > .local/tourfedia-status.json
VANTIS_TENANT=$(aac agent status --agent trip-planner --field tenant-id)
VANTIS_DOMAIN=$(aac agent status --agent trip-planner --field hosted-trust-domain)
VANTIS_ID=$(aac agent status --agent trip-planner --field workload-spiffe-id)
TOURFEDIA_TENANT=$(aac agent status --agent booking --field tenant-id)
TOURFEDIA_DOMAIN=$(aac agent status --agent booking --field hosted-trust-domain)
TOURFEDIA_ID=$(aac agent status --agent booking --field workload-spiffe-id)
```

Append these sections **once** to the input copies. The peer's public CA
path is an explicit trust choice; no private key is exchanged.
`ca.crt` is the peer's public CA certificate, the same anchor it publishes
through AAC. In a real deployment the peer supplies that public certificate;
reading it from the other agent's local directory is a convenience of running
both tenants on one machine, not a requirement to access a peer's private files.

```sh
cat >> .local/trip-planner.yaml <<EOF
trust_anchors:
  tenant_ids: [$TOURFEDIA_TENANT]
spiffe_bundles:
  trust_domains: [$TOURFEDIA_DOMAIN]
https_trust:
  ca_files: ["$AAC_CLI_HOME/agents/booking/agent/ca.crt"]
destinations:
  tourfedia:
    url: https://booking:9443/v1/agent/receive
    audience_pattern: $TOURFEDIA_ID
    valid_for: +30m
    timeout_ms: 10000
EOF
cat >> .local/booking.yaml <<EOF
trust_anchors:
  tenant_ids: [$VANTIS_TENANT]
spiffe_bundles:
  trust_domains: [$VANTIS_DOMAIN]
https_trust:
  ca_files: ["$AAC_CLI_HOME/agents/trip-planner/agent/ca.crt"]
EOF
aac init --profile vantis --agent trip-planner --agent-config .local/trip-planner.yaml
aac init --profile tourfedia --agent booking --agent-config .local/booking.yaml
```

These three trust settings have different jobs: verify tenant root signatures,
verify workload certificates, and verify outbound HTTPS connections.
The destination names the exact registered booking identity. The initial
class supplies `valid_for: +2h`; the destination supplies `+30m`.
Dynamic amounts come only from the application. Released native chain starts
refuse conflicting class/request values and any request-supplied
`valid_until`.

## 4. Start and run

```sh
./demo up
./demo run
./demo run fare-change
./demo run fresh-authority
```

`up` builds the small application image, starts the two pairs and their
publishers, and waits for readiness and public trust publication.
`run` starts one task, then waits up to 30 seconds for correlated completion.
Failure or missing evidence exits nonzero.

The output includes the actual mint response, root/task IDs, dispatch and
receive events, signed terminal receipt, reservation/order and
`terminal_attestation_verification: verified`. An HTTP 200 or `dispatched`
acknowledgement alone does not pass. Read the output alongside
[agent/client.py](agent/client.py) and [agent/agent.py](agent/agent.py).

The normal run reports an $8,000 reservation. In the separate
fare-change run Tourfedia sees $9,500 and declines before reserving; this is a
business decision. The fresh-authority run starts a new Vantis authorization
under the simulated $10,000 approval and reserves at $9,500. It does not widen
the old authority held by Tourfedia.

Local `state/telemetry.jsonl` and `state/actions.jsonl` contain the protocol
and business evidence. The demo operator controls both stacks and reads their
records locally. This is not automatic access to another tenant's files.
The supplied configuration enables metadata-only central forwarding through each
profile's generated endpoint and its own mounted API-key file. Private business
records, caps, expiry and receipts stay local. Forwarding is asynchronous; an
actual root returned by `aac chain show` is the evidence that delivery occurred.

### View this execution graph

The CLI installation above supplies both `aac` and `aeg`. Check the installed
graph command on the setup host:

```sh
aeg --version
```

Each `./demo run` now saves its successful mint response in `.runs/`, prints the
order → scenario → task-reference → root mapping and prints a complete
`aeg render` command with the actual telemetry/action paths and HTML output.
Run that printed command. Add `--profile vantis` to combine authorized central
metadata with those local records in the same invocation. The resulting HTML
opens without a server or network assets; double-click nodes for all actions,
receipt evidence, limits and workload identities.

### Discover executions and select a root

The supplied sources choose the mode: files alone are local, `--profile` alone
queries the control plane, and both combine local evidence with authorized
central observations. No local files are uploaded. These paths come from the
demo's CLI-managed agent directory; use the paths printed by `./demo run` if
your files are elsewhere.

```sh
EVENTS="$AAC_CLI_HOME/agents/trip-planner/state/telemetry.jsonl"
ACTIONS="$AAC_CLI_HOME/agents/trip-planner/state/actions.jsonl"

# Local evidence only; no network request.
aeg list --events "$EVENTS" --actions "$ACTIONS" --since 24h --output table

# Participant-visible central observations only.
aeg list --profile vantis --since 24h --limit 50 --output table

# Hybrid: join the two sources by the actual root token ID.
aeg list --profile vantis --events "$EVENTS" --actions "$ACTIONS" --since 24h --limit 50 --max-pages 3 --output table
```

Each row's `sources` value is `local`, `control-plane` or `both`: it says what
contributed to this query. A `local` row does not prove AAC never received it;
time windows, later pages, late forwarding, access and query failures can all
exclude a central contribution. Central times, hops and outcomes are observed
metadata, not proof of complete forwarding or business completion.

For an exact task reference, add `--task-ref TASK_REF` to the local or hybrid
command, replacing `TASK_REF` with the value printed for that attempt. Only
locally matching roots qualify. That option is refused with a profile alone,
because private task references are not stored centrally. Actions without a
root mapping produce diagnostics rather than guessed joins.

For a fixed interval, choose UTC times covering your run and replace this
example day. `--from` is inclusive and `--to` is exclusive; the same interval
selects local and central activity. Online intervals are limited to 31 days.

```sh
aeg list --profile vantis --events "$EVENTS" --actions "$ACTIONS" --from 2026-09-25T00:00:00Z --to 2026-09-26T00:00:00Z --limit 50 --max-pages 3 --output json
```

Online listing defaults to one page. `--limit` sets the page size (1–200), and
`--max-pages` bounds how many pages this invocation fetches (1–20). When the
output provides a continuation token, replace `PAGE_TOKEN` below and continue
with the same profile, files and task filter, omitting `--since`. A continuation
reuses its bound interval and page size. Tokens expire after 15 minutes; restart
the original query when one expires.

```sh
aeg list --profile vantis --events "$EVENTS" --actions "$ACTIONS" --page-token PAGE_TOKEN --max-pages 3 --output table
```

Continuation calls may repeat local rows; source labels describe each call's
contributions. `exhausted` means no further query pages, not complete evidence.
A failed central fetch exits 4 and reports partial coverage/diagnostics with
recoverable rows. Retry a token only for a transient failure; restart the
original query after a rejected or expired token. Do not treat failure as an
empty successful result. A failed bare continuation cannot select local rows
until its interval is known. Invalid arguments or local evidence exit 2.

Choose a listed root and replace `ROOT_ID` below. Keep separate attempts
separate: the fresh-$9,500 root and earlier $8,000 root are distinct even when
both concern PO #4143.

```sh
aeg render --profile vantis --events "$EVENTS" --actions "$ACTIONS" --root-token-id ROOT_ID --output .runs/selected.html
```

Omit the profile for an offline render, or omit the files for a central-only
render. Sender-only or receiver-only inputs produce a partial graph with
missing evidence labeled. Local business records are application reports,
not receipt-verification results. The applications emit the public eight-field
`action_taken` format; malformed inputs are reported by file and line.
See the [AEG guide](https://cascadeauth.github.io/aac-starter-guide/aeg.html)
for the schema, source modes, filtering, continuation and interpretation.


## 5. Refusals and controlled attacks

```sh
./demo check
```

This explicit test driver uses CLI-issued test material and the public
`cryptography==50.0.1` package. Its isolated container mounts the two test
identities; the normal applications never receive those private keys.
The driver constructs the attack chains itself using a test-only copy of the
AAC v1 wire encoding. Its positive controls must pass against the sidecar
release recorded in `.local/components.json` before an attack result counts.

It checks both chain-start aliases: absent, wrong-pair and altered signatures
must fail before any successful mint or application invocation. It constructs
an otherwise valid $8,000 → $9,500 continuation signed by Tourfedia and
addressed to Vantis; Vantis must return `ERR_CHAIN_INVALID` before invoking
its application. A $7,000 control proves that the same identities, trust,
encoding and route work. It also sends Tourfedia a fresh proof signed by
Tourfedia instead of Vantis: `ERR_PRESENTER_NOT_PREVIOUS_HOLDER` must precede
booking invocation. The correctly presented control succeeds.

For the **local** widening check, explicitly add a test-only return destination
and enable the booking application's test decision:

```sh
cp .local/booking.yaml .local/booking-test.yaml
cat >> .local/booking-test.yaml <<EOF
destinations:
  test_vantis:
    url: https://trip-planner:9443/v1/agent/receive
    audience_pattern: $VANTIS_ID
    valid_for: +5m
    timeout_ms: 10000
EOF
aac init --profile tourfedia --agent booking --agent-config .local/booking-test.yaml
AAC_DEMO_TEST_MODE=1 ./demo up
./demo run local-widening
aac init --profile tourfedia --agent booking --agent-config .local/booking.yaml
./demo up
```

Tourfedia's failure event must identify candidate chain validation of
$8,000 → $9,500; no return receive or Vantis application invocation is allowed.
The released sender validates the candidate before proof signing or transport.
The reverse route and decision are test-only; normal booking returns
`settle`, which means the delegated task finished, not payment settlement.

## 6. Refresh, renew and restart

Refresh uses the last explicitly applied input, even if the source YAML has
since been edited. To apply edits, pass `--agent-config` explicitly.

```sh
aac init --profile vantis --agent trip-planner
aac init --profile tourfedia --agent booking
./demo up
./demo run
./demo check
```

Leaf renewal keeps identities, root key, destinations and peer configuration.
Stop the affected pair before changing mounted material, then recreate it:

```sh
./demo compose booking stop sidecar agent
aac agent renew --agent booking
./demo up
./demo run
./demo check
```

CA renewal additionally requires public republication and explicit peer HTTPS
trust refresh. Old published anchors remain until deliberately retired.

```sh
./demo compose booking stop sidecar agent
aac agent renew --agent booking --ca
./demo compose booking up -d --force-recreate publisher
aac agent status --agent booking --remote
# Reapply Vantis's input to read Tourfedia's replacement PUBLIC CA.
aac init --profile vantis --agent trip-planner --agent-config .local/trip-planner.yaml
./demo up
./demo run
./demo check
```

`up` waits for the current anchor ID to be published. Repeat the same procedure
with the roles reversed: renew `trip-planner`, reapply `booking.yaml`, restart,
and repeat both directions' checks. Compare the generated configuration before
and after maintenance: only expected certificate/CA references and trust bytes
should change; classes, destinations, identities and durations must remain.

For **supplied certificates**, your issuer generates the replacement; the CLI
does not issue it and stores no CA private key. Pass the issuer's files:

```sh
./demo compose booking stop sidecar agent
aac agent renew --agent booking --workload-cert-file /issuer/booking/workload.crt --workload-key-file /issuer/booking/workload.key --terminal-cert-file /issuer/booking/terminal.crt --terminal-key-file /issuer/booking/terminal.key --tls-cert-file /issuer/booking/server.crt --tls-key-file /issuer/booking/server.key --ca-cert-file /issuer/booking/ca.crt
```

That command applies to an agent originally initialized with the seven supplied
material flags. It does not convert a development-issued agent to supplied mode.
Certificates must retain its registered SPIFFE identity and cover `booking`,
`localhost` and `127.0.0.1`. On a CA replacement, republish and refresh peer
trust as above before restart. Certificate source does not certify a production
deployment. The live acceptance procedure covers this separate mode.

## Cleanup and limits

```sh
./demo down
```

This removes the local containers/network and preserves the CLI home and
evidence. Tenant registrations are permanent; deleting a local profile does
not delete a tenant. Keep protected copies of credentials and keys, or
deliberately retire test workloads through the supported tenant lifecycle.
Do not delete someone else's material as cleanup.

This teaches native AAC, not A2A, payment processing, durable inventory,
production hardening, retries or reliable delivery. Basic replay history is
lost on sidecar restart. The runtime's receipt grade is audit evidence; this
runner requires `verified` rather than claiming a fail-closed runtime policy.
The distinct receipt key is not an enforced certificate-role isolation boundary.

## Tests and recorded evidence

`prepare --tests` installs the test dependencies and AAC helpers matching the
existing run selection. It retains the selected CLI and component receipt.

```sh
./demo prepare --tests
python -m pytest tests -q --ignore tests/live
AAC_DEMO_LIVE=1 python -m pytest tests/live -q
# Explicitly enable configuration and certificate lifecycle mutations:
AAC_DEMO_LIVE=1 AAC_DEMO_LIFECYCLE=1 python -m pytest tests/live -q
```

Live tests use the already-authorized, configured tenants in `AAC_CLI_HOME`.
They read the input copies in `.local/`; set `AAC_DEMO_CONFIG_DIR` if yours are
elsewhere. The supplied-material test uses the CLI-issued booking material as
a test issuer and imports it through the supported supplied-file flags into
`book-supplied`, a separate local slot for the **same booking workload**.
Only one slot runs at a time; neither the business application nor that supplied
slot receives the issuer's CA private key. The test restores the normal booking
slot afterwards. This tests replacement mechanics, not a production issuer.
See [docs/evidence/README.md](docs/evidence/README.md) for exact measured
versions, commits, positive/negative cases and lifecycle receipts.
Historical one-agent measurements remain historical; they are not B271 passes.
