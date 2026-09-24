# AAC: two tenants, one unpaid reservation

Vantis Equity's trip-planner asks Tourfedia's booking workload to create a
**synthetic unpaid reservation**. Each fictional organization has its own AAC
tenant, assigned trust domain, CA, public trust publication and private keys.

Marc Sterling's approval is **simulated**: PO #4143, Austin to Shanghai,
departing 12 May, up to $10,000. Vantis's application signs the native chain-start
request and supplies that budget. T0 establishes origin; T1 carries $10,000,
the order reference and two hours of authority. The trip-planner narrows to
$8,000 and 30 minutes, addressed to Tourfedia. Tourfedia returns a signed
terminal receipt; Vantis verifies it against the expected identity and actual
chain root.

This creates no real supplier booking, payment or paid ticket. Thirty minutes
limits the **authority**, not a guaranteed price hold. Returning a receipt is
not another delegation or another business agent.

## Requirements

macOS or Linux, Python 3.11+, Docker with Compose, and two stage developer
tenants you control. Registration requires interactive GitHub sign-in.
The two tenants can have the same human owner. A contact email is registration
metadata; it does not select your GitHub account.

| Public component | Version used here |
|---|---|
| aac-cli on PyPI | 0.2.2 |
| AAC sidecar on Docker Hub | v0.4.1 |
| Trust-anchor publisher on GHCR | 0.2.3 |
| aac-invoke-auth on PyPI | 0.1.2 |
| Python application image | 3.12-slim |
| uvicorn / httpx | 0.52.4 / 0.28.1 |

No private repository or AAC SDK is required. The applications build locally
from this public source. See the [AAC guide](https://cascadeauth.github.io/aac-sidecar-go/)
for protocol/configuration reference and production deployment choices.

## 1. Install and declare each agent

```sh
git clone https://github.com/CascadeAuth/aac-compose-demo.git
cd aac-compose-demo
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'aac-cli==0.2.2'
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
value() { python -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2"; }
VANTIS_TENANT=$(value .local/vantis-status.json tenant_id)
VANTIS_DOMAIN=$(value .local/vantis-status.json hosted_trust_domain)
VANTIS_ID=$(value .local/vantis-status.json workload_spiffe_id)
TOURFEDIA_TENANT=$(value .local/tourfedia-status.json tenant_id)
TOURFEDIA_DOMAIN=$(value .local/tourfedia-status.json hosted_trust_domain)
TOURFEDIA_ID=$(value .local/tourfedia-status.json workload_spiffe_id)
test "$VANTIS_TENANT" != "$TOURFEDIA_TENANT"
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

The normal run reports an unpaid synthetic $8,000 reservation. In the separate
fare-change run Tourfedia sees $9,500 and declines before reserving; this is a
business decision. The fresh-authority run starts a new Vantis authorization
under the simulated $10,000 approval and reserves at $9,500. It does not widen
the old authority held by Tourfedia.

Local `state/telemetry.jsonl` and `state/actions.jsonl` contain the protocol
and business evidence. The demo operator controls both stacks and reads their
records locally. This is not automatic access to another tenant's files.
Central telemetry remains off here; enriched graph integration is separate.

## 5. Refusals and controlled attacks

```sh
./demo check
```

This explicit test driver uses CLI-issued test material and the public
`cryptography==50.0.1` package. Its isolated container mounts the two test
identities; the normal applications never receive those private keys.
The driver constructs the attack chains itself using a test-only copy of the
AAC v1 wire encoding accepted by sidecar v0.4.1. Keep it aligned with the tested
sidecar release; its positive controls must pass before an attack result counts.

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

```sh
python -m pip install -r tests/requirements.txt
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
