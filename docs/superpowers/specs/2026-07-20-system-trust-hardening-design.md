# Hermes System Trust Hardening Design

> Approved by the user on 2026-07-20 after the strict 20-dimension review.

## Goal

Close the seven remaining trust gaps without changing live behavior implicitly:
approved runtime configuration, complete score persistence, source-role and
provider provenance, crash-recoverable history promotion, two one-shot research
experiments, and maintenance/CI cleanup.

## Safety Boundary

- No production order path is added; IBKR remains read-only.
- New strategy behavior is guarded by a repository-default-OFF flag.
- Each strategy experiment receives one pre-registered formal gate. A failed or
  neutral gate is recorded as Rejected and is not tuned or rerun.
- Deployment and live configuration changes are outside this implementation.
- Tests use isolated data roots and do not refresh live market, external-source,
  or IBKR data.

## Design

### 1. Approved Runtime Configuration

A committed policy artifact binds the semantic SHA256 of the approved repository
config, the semantic SHA256 of the approved live config, the exact boolean
feature diff, and safety invariants such as `ibkr.readonly=true`. Deployment
validates both configs against that policy before creating an attestation.
Morning acceptance validates the active config and release-local policy again.
An attestation therefore proves authorization as well as identity.

### 2. Complete Score Persistence

Soft data collection becomes pure until the score transaction is open. The
dated soft snapshot is atomically written inside the same recoverable journal as
the six existing score artifacts. Fault injection compares all seven artifacts
after every persistence checkpoint.

### 3. Source Role And Provenance

Every source policy declares an explicit decision role: `strategy`,
`hard_gate`, `auxiliary`, or `research`. Health maps failures to the declared
layer rather than inferring impact from `active` or point weight. Every adapter
returns one provenance contract with `source`, `primary_source`,
`primary_failure`, and `fallback_used`; the ledger records those fields.

### 4. History Promotion Journal

History refresh stages valid candidate CSVs, records old/new hashes and paths in
a persistent operation manifest, then promotes each target atomically. Startup
recovery restores all old bytes for an incomplete operation. The certified
market evidence is written only after the operation commits.

### 5. Route-Set Transition Candidate

The experiment targets transaction cost rather than score smoothing. With the
flag ON, small non-risk target legs below a fixed 2 percentage-point portfolio
weight are suppressed when their addition/removal is the only route-set change;
hard-valve exits and risk-leg reductions are never delayed. The pre-registered
gate requires positive WF and CPCV OOS deltas, no more than 1pp MaxDD worsening,
and strictly lower route-set turnover.

### 6. C/D Trend Ownership Candidate

Module C owns broad moving-average trend damage. With the flag ON, D1/D2 do not
add another MA200/MA220 vote; D retains symbol-specific drawdown, relative
strength, radar, and microstructure evidence. The flag is default OFF and goes
through one formal gate without threshold or weight retuning.

### 7. Maintenance Closure

Remove unreachable retired M4 server functions, use shared atomic writers for
IBKR and report artifacts, replace current operator documentation that describes
the retired deployment/baseline, and add minimal remote CI for unit tests,
governance, and compilation.

## Verification

Each item follows RED/GREEN TDD, focused regression, and a diff review before the
next begins. The final gate is the full test suite, governance consistency,
`compileall`, shell syntax checks, default-OFF four-date input-hash identity for
strategy flags, and a clean secret/live-data scan.
