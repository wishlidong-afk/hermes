# Phase 14 Report - Read-Only Web Snapshot

Date: 2026-06-01

## Scope

Phase 14 adds a read-only HTML dashboard renderer:

- Escape decisions.
- Current market regime from QQQ/VIX/VIX3M.
- Module score strip A/B/C/D.
- Volatility scaler.
- Missing weight / blind-spot / data-quality audit detail.
- Portfolio risk.
- Mirror reference.
- CLI command: `python3 -m hermes_escape_top.cli dashboard --as-of YYYY-MM-DD --output /path/to/dashboard.html`.

## Verification

- Renderer includes all core sections plus regime and audit-detail sections.
- Dashboard file writes successfully.

## Remaining Gaps

- Live read-only HTTP server is implemented in Phase 15.
- Existing production WebUI has not been replaced.
- IBKR integration remains outside this greenfield snapshot phase.
