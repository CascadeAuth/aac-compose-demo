# Maintainer merge policy (B339)

`CascadeAuth/aac-compose-demo/main` requires a pull request, administrator enforcement,
zero GitHub approvals, no force pushes/deletion, and strict/up-to-date required
checks. The required set is `fixture-checks`, bound to GitHub Actions (app ID 15368).
A branch must incorporate the latest main and pass fresh required checks after
main advances, even when the changes have no textual conflict.

The reviewed, complete inventory and read-only drift checker live in
[aac-infra](https://github.com/CascadeAuth/aac-infra/blob/main/policy/main-protection.json).
Before merging, run from this repository in the normal sibling-checkout layout:

```bash
python3 ../aac-infra/bin/check-main-protection.py --repo CascadeAuth/aac-compose-demo
```

Use a current reviewed aac-infra checkout and the owner's authenticated gh
session with Administration read access. A drift or unknown-state result stops
the merge procedure; never bypass protection or silently replace the inventory
with live settings. A saved snapshot is evidence, not a fresh merge preflight.
Ordinary CI needs no administrator credential. The
[runbook](https://github.com/CascadeAuth/aac-infra/blob/main/docs/runbooks/main-protection.md)
covers all four repositories, layered rules, evidence and authorized settings
changes. Independent project review, owner merge authorization and any live
acceptance/release duties remain separate from GitHub's zero-approval setting.
