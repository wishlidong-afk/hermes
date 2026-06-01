# Phase 15 Report - Integration Dry Run

Date: 2026-06-01

## Scope

Phase 15 adds the first greenfield integration layer:

- Posterior ideal P/L for escape-top sizing.
- Posterior ideal P/L for mirror-reference decisions.
- Read-only HTTP dashboard server:
  - `/` HTML dashboard.
  - `/api/score` JSON payload.
  - `/health` health check.
- Structured audit log with replay hash validation.
- Persistent signal journal used by reentry time-lock calculation.
- CLI command:
  - `python3 -m hermes_escape_top.cli serve --as-of YYYY-MM-DD --port 8776`

## Safety

- No order generation.
- No IBKR write path.
- No real trade execution.
- Posterior P/L uses a default `$100,000` model portfolio and prior-close ideal sizing; it is for model audit only.

## Verification

- Known two-close posterior P/L test passes.
- Score payload includes posterior P/L for escape and mirror.
- Local read-only server responds on `/health`, `/api/score`, and `/`.
- Audit records can be hash-verified.
- Reentry now reads prior sell events from the greenfield signal journal.

## Remaining Gaps

- Existing production WebUI has not been switched over.
- IBKR position reconciliation remains outside this greenfield integration.
- Full transaction-level backtest and parameter sweep are still pending.
