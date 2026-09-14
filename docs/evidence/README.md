# Measured runs

Each file here is written by a real run of this starter against the AAC
stage service. Nothing in these files is secret: identifiers, outcomes and
durations only.

| File | What it is |
|---|---|
| `linux-aarch64.json` | The live test harness (`tests/live/`) on an Ubuntu 24.04 arm64 virtual machine (Docker Engine 29.1, Compose 2.40), after that machine had registered a new tenant through `./starter setup`. |
| `linux-aarch64-timings.txt` | The same machine's complete timings log (`.starter/<workspace>/timings`): the first line is the fresh-tenant guided setup with both browser sign-ins (247 s); the run at 19:59 is a cold image download with every image removed first (21 s); the run at 19:54 followed a manual pull of two of the three images (18 s). |
| `darwin-arm64.json` | The live test harness on macOS (Apple silicon, Docker Desktop 29.7, Compose 5.5) with an existing tenant: repeat runs, recreate, rebuild, the missing-credential refusal. Both `.json` files are from the final harness run; the timing logs also hold every earlier run of the day, including runs before `./starter up` recreated containers on every start (the shorter "start until the sidecar is ready" lines). |
| `darwin-arm64-timings.txt` | The macOS machine's timings log. Every image download there hit the cache; the cold pull of the sidecar and publisher images on that machine was measured separately with `time docker pull` at 6 min 39 s and 6 min 42 s, a property of that network rather than of the images (12 MB and 233 MB). |
