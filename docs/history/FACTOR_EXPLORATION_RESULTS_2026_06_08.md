# Factor Exploration — Results & Decision (2026-06-08)

After deploying A10/A11/A15 we ran three further experiments to push "accuracy."
**All three failed to beat the deployed system.** This documents them so we don't
repeat them, and records the structural conclusion.

## Baseline (deployed, live)

A10 real_rate + A11 dollar + A15 defensive_rotation, combo **E75_D70_R50**.
Full-window 2018–2026 (same pipeline, full-proxy): **CAGR 16.9%, MaxDD −16.3%,
Sharpe 1.07, Calmar 1.04**. next3_pass=true. This is the bar to beat.

## Experiment results (all vs that baseline)

| Experiment | What | Calibrated full-window | Gate | Verdict |
|---|---|---|---|---|
| **batch-2** | + MOVE(A18) + NDX-conc(A19) + NAAIM-tighten | CAGR 13.1% / MaxDD −21.2% / Sharpe 0.95 (E75_D60) | PBO pass | ❌ **worse on every metric** |
| **A: NAAIM-tighten alone** | tighten loose tier (pctl 75→85) | CAGR 16.3% / MaxDD −17.7% / Sharpe 1.04 (E75_D70_R55) | PBO pass | ➖ **neutral-to-worse** (Sharpe ~flat, no edge) |
| **B: arm-then-fire** | leading factors ease thresholds when armed | not completed (low-EV + design flaw, see below) | — | ⏸ **deferred** |

## Two lessons that earned their keep

1. **Incremental ≠ standalone (both directions).** MOVE & A19 looked good
   *standalone* (edge60 −2.5pp, 58–81% crash recall) and passed PBO in isolation,
   yet added **negative** marginal value on the already-deployed macro factors.
   Conversely NAAIM-tighten *improved* the standalone edge (−3.4→−5.4pp) but was
   **neutral in-system** — its frequent-but-weak firing was contributing some
   aggregate defense that tightening removed. The PBO gate alone waves these
   through; only the **comparison to the incumbent** catches them.

2. **The A-module is saturated → factor-tweaking is exhausted.** A is capped at 20
   and A10/A11/A15 already saturate it often. Adding more leading/macro factors as
   additive points just causes **whipsaw** (the calibrator drops DEFENSIVE_EXIT to
   compensate → turnover spikes → worse drawdown). The deployed system is a **local
   optimum** for this approach.

## Why arm-then-fire (B) was deferred, not killed

It is *built* and flag-gated OFF. But the current design has a **double-count
flaw**: it arms off real_rate/dollar, which are *also* additive score factors —
so in stress those signals both add points AND ease thresholds (counted twice).
A clean test needs the arming inputs to be **leading-data-only** (modulate
sensitivity, never score), a separate refactor. Running it as-is would be a
polluted, low-EV test, consistent with the same saturation/whipsaw dynamic.

## Decision

- **Stop factor-tweaking.** Live stays on the deployed A10/A11/A15. Nothing to roll
  back — batch-2 / NAAIM / arm-then-fire all lived only in calibration sandboxes.
- A17/A18/A19 + arm-then-fire remain **built + flag-gated OFF** (documented negative
  results; cheap to revisit).
- **Over-iteration risk:** every extra calibration round on a 6-yr window fits more
  noise. We have a gate-passing, drawdown-halving deployed system — consolidate.

## The only genuinely-new directions left (not "more factors in a saturated module")

1. **Axis D — MSTR on-chain** (CoinMetrics community, free, backfillable): the one
   data axis truly *orthogonal* to the macro space we've now saturated. Real work,
   MSTR-sleeve only, but it's where untapped signal actually is.
2. **Clean arm-then-fire refactor**: separate arming inputs (leading-data-only) from
   the additive factor set, then test the modulation mechanism honestly.
3. **Real CBOE PCR** (unblock the proxy) and a **broad-market breadth feed**
   (%>200DMA / A-D / McClellan) — both currently data-blocked; need manual/paid feeds.
