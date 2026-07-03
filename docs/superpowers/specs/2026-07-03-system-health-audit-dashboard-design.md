# 8766 System Health Audit Dashboard Design

Generated on 2026-07-03.

## Goal

Expose the daily 20-dimension `system_health_<as_of>.json` report inside the
8766 dashboard so the user can see health evidence without opening report files.

## Scope

- Read-only WebUI change.
- No score, daily, config, refresh, or official-run writes.
- The dashboard continues to show the existing compact health summary first.
- The 20-dimension audit renders inside the existing "System Health" section as
  a default-collapsed evidence panel.

## Data Flow

1. `server.py` loads the score payload exactly as it does today.
2. `server.py` attaches `payload["system_health_report"]` from the best matching
   report file:
   - prefer `reports/system_health_<payload.as_of>.json`;
   - otherwise use the newest `reports/system_health_*.json`;
   - mark the attachment stale when the report `as_of` differs from the payload
     `as_of`.
   - in versioned live releases, also search sibling release package report
     directories so a dashboard deploy does not hide the daily report generated
     earlier by the previous release.
3. `render.py` renders only the report already attached to the payload.

## UI

The existing "系统状态 + 数据质量 / System Health" section gets a default-collapsed
panel titled "20 维系统自检 / System Health Audit".

The panel shows:

- report health level, report `as_of`, generated time, and stale marker;
- PASS/WARN/FAIL counts across the audit dimensions;
- a table of label, status, and detail for each dimension.

If no report exists, the panel shows a quiet empty state and does not affect the
main health banner.

## Testing

- Render smoke test: report attached, table and counts appear.
- Render stale test: report `as_of` mismatch is visibly marked stale.
- Server loader test: exact report wins over newest report.
- Server loader test: newest report attaches as stale when exact report is absent.

## Non-Goals

- No new HTTP endpoint.
- No JavaScript fetch.
- No health recomputation inside the renderer.
- No promotion of report WARN/FAIL into the live health banner; `compute_health`
  remains the source of live banner truth.
