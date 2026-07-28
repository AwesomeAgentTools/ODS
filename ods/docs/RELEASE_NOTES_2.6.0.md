# ODS 2.6.0 Draft Release Notes

Draft status: release-prep branch. Do not publish as stable until the final
release-stamp commit has a release-grade validation receipt.

## Summary

ODS 2.6.0 rolls up the post-2.5.3 work on remote providers, model
switchboard, verified context selection, GPU reassignment rollback, rootless
Linux installs, Windows and macOS native-runtime stability, dashboard polish,
and release hygiene.

Use this release for new stable installs once the final validation receipt is
complete. Continue to pin `v2.5.3` only when an appliance or fork needs the old
2.5 behavior and cannot move to the 2.6 line yet.

## Highlights

- Remote provider support now includes direct and SSH egress, policy checks,
  tunnel supervision, dashboard status, and peer ODS model operations.
- Model Switchboard gives apps a stable current-model route and propagates the
  selected context across runtimes and applications.
- NVIDIA and Linux AMD/ROCm GPU reassignment flows support larger model swaps
  with verified rollback.
- Linux rootless Docker installs can repair service bind-mount ownership inside
  the rootless namespace.
- Windows native llama-server launches now expose metrics and honor
  `LLAMA_REASONING`; stale Lemonade listener PIDs are handled safely.
- macOS OpenCode config compatibility, Perplexica Lemonade routing, Token Spy
  Postgres cursors, voice readiness, and model-memory estimates were corrected.
- Remote-provider direct egress now pins validated DNS resolutions to close
  DNS-rebinding/SSRF escape paths.

## Upgrade Notes

- `v2.6.0` is the new stable line. Stable hotfixes should target
  `release/2.6.x` first, then merge forward to `main`.
- `release/2.5.x` is superseded and should only receive critical old-stable
  continuity fixes.
- Operators using remote-provider direct routes should re-run route validation
  after upgrade so the new DNS pinning and TLS identity behavior is exercised.
- Rootless Docker operators with container-owned data directories should stop
  ODS, run `ods repair rootless-ownership`, then start ODS if a service reports
  permission errors under `data/`.
- Windows users relying on native llama-server fallback should restart the
  native runtime after upgrade so `--metrics` and `--reasoning-format` are
  present on the process command line.

## Validation Receipt

- Release tag: `v2.6.0` (pending)
- Candidate product commit: `e93d5434fc2a09dd0324e0f3df9ef5d6943cded9`
- Base product commit: `c292e00d5b60f6e4e6b331b2867346f9e9748a2c`
- Release-prep branch: `chore/release-2.6.0`
- Release-stamp commit: pending final merge
- GitHub Actions at candidate commit: all PR checks green on 2026-07-28
- Focused local validation at candidate commit:
  - Windows parser/resolver
  - llama runtime tunables, metrics, and reasoning contracts
  - env schema and uninstall scoping
  - installer context parity and rootless doctor
  - dashboard API focused regressions: `502 passed, 5 skipped`
  - Perplexica, remote-provider egress, and Token Spy cursor tests:
    `35 passed, 1 skipped`
  - Tower2 rootless ownership contract: `25 passed`
- Required before stable publication:
  - release-grade fleet run
  - zero-prereq bootstrap
  - distro lab
  - lifecycle checks: reinstall, restart, `ods doctor`
  - model-management release or explicitly documented substitute
  - skipped/deferred surfaces recorded in the final receipt

## Known Limits

- Windows native remains an installer/runtime path with targeted validation;
  WSL2 plus Docker Desktop remains the supported Windows appliance path.
- ODS Talk owner-card probes gate only when the owner-card surface and
  `ods-proxy` are enabled for the candidate install.
- Vision probes, AP mode, custom network topologies, and downstream forks need
  their own local validation receipts.

## Draft GitHub Release Body

```markdown
## ODS 2.6.0

ODS 2.6.0 updates the stable line with remote-provider support, Model
Switchboard and context selection, GPU reassignment rollback, rootless Linux
repair, Windows/macOS native-runtime fixes, dashboard polish, and security
hardening.

### Highlights

- Remote provider direct/SSH egress, tunnel supervision, dashboard status, and
  peer model operations.
- Model Switchboard stable routing and verified context propagation across LLM
  applications.
- Verified NVIDIA and Linux AMD/ROCm GPU reassignment with rollback.
- Rootless Docker bind-mount ownership repair for Linux installs.
- Windows native llama-server metrics and reasoning flags, plus safer Lemonade
  stale-PID handling.
- Remote-provider DNS-rebinding/SSRF hardening through validated address
  pinning with preserved TLS identity.

### Validation

- Release tag: `v2.6.0`
- Release-stamp commit: `TBD`
- Product candidate: `e93d5434fc2a09dd0324e0f3df9ef5d6943cded9`
- Base product commit: `c292e00d5b60f6e4e6b331b2867346f9e9748a2c`
- Gate result: `TBD after release-grade validation`
- Known skipped/deferred surfaces: `TBD`

See `ods/CHANGELOG.md` and `ods/docs/RELEASE_NOTES_2.6.0.md` for the full
release notes and validation receipt.
```
