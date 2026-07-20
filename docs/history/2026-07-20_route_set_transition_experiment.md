# Route-Set Transition Buffer Pre-Registration

## Status

`Candidate`, repository default is explicit OFF. Live behavior is not changed by
this registration. Only the isolated gate config sets
`features.use_route_set_transition_buffer=true`.

## Fixed Mechanism

- Compare today's final portfolio route set with the prior decision day's set.
- Exclude the risk legs `MSTR`, `FNGU`, and `SOXL`, and the cash reservoir
  `BOXX`, from the route-set comparison.
- Act only when exactly one non-risk route leg was added or removed.
- Act only when that leg's absolute portfolio weight is strictly below `0.02`.
- Suppress an addition by moving its weight to `BOXX`; suppress a removal by
  retaining its prior weight and funding it from `BOXX`.
- Never alter a risk-leg weight. Hard-valve exits and risk reductions therefore
  remain immediate.
- No threshold search, alternate reservoir, symbol exception, or second run is
  permitted after seeing the result.

## Pre-Registered Acceptance

The candidate is accepted only if every formal-gate check passes and the
supplemental turnover check passes:

1. walk-forward OOS delta is strictly positive;
2. CPCV OOS delta is strictly positive;
3. both PBO values are below `0.5`;
4. MaxDD worsens by no more than `0.01` absolute;
5. DSR is non-negative; and
6. candidate route-set turnover is strictly lower than baseline.

Route-set turnover is fixed before the run as full-portfolio L1 weight turnover
on days where the positive non-risk, non-BOXX route set changes. The initial
backtest day is excluded. The metric is written to each flag-sweep artifact as
`route_set_turnover`.

If either the formal result or the supplemental turnover check fails, the
experiment is `Rejected`, remains OFF, and is not retuned or rerun.

## Evidence Paths

- Manifest: `research/experiments/route-set-transition-buffer-v1.json`
- Flag artifacts: `building/reports/flag_sweep/baseline.json` and
  `building/reports/flag_sweep/route_set_transition_buffer.json`
- Formal result: `building/reports/formal_gate/route-set-transition-buffer-v1/`
- OFF equivalence: `building/reports/persistence/ROUTE_TRANSITION_OFF_EQUIVALENCE_2026_07_20.json`
