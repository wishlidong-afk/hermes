# Formal Gate Experiment Manifests

This directory holds pre-registered Hermes research experiments. A manifest is
an authorization boundary, not a convenience file.

## Required sequence

1. Write one manifest containing the complete candidate universe, target,
   declared trial count, validation design, and thresholds.
2. Commit the manifest before producing any equity artifact for that experiment.
3. Run every registered variant with `scripts/backtest_flag_sweep.py` at the same
   commit and data fingerprint.
4. Run `scripts/formal_gate.py` with the committed manifest.
5. Treat `CANDIDATE_GATE_PASSED` as awaiting a human flip. It never changes
   production configuration automatically.
6. Treat `REJECTED` as the experiment's one final result. `result.json` cannot be
   overwritten by a second run.

The CLI rejects untracked or modified manifests and uncommitted gate/config
code. Data and report directories may remain uncommitted because their hashes
are carried as experiment evidence. The CLI also blocks if any metrics artifact
is not cache v3 FRESH for the current commit, code, config, manifest,
soft-history, and replay window. Manifest and code state are checked again
immediately before the final result is committed.

## Manifest format

```json
{
  "schema": "hermes-formal-gate-v1",
  "experiment_id": "descriptive-hypothesis-v1",
  "created_at": "2026-07-10",
  "hypothesis": "The pre-specified target improves defensive OOS performance without worsening drawdown.",
  "artifacts_dir": "building/reports/flag_sweep",
  "baseline": "baseline",
  "target": "target_variant",
  "candidates": [
    "target_variant",
    "alternative_variant"
  ],
  "declared_trial_count": 3,
  "walk_forward": {
    "is_years": 2,
    "oos_months": 6,
    "step_months": 6,
    "label_horizon": 20,
    "embargo_pct": 0.02
  },
  "cpcv": {
    "n_groups": 6,
    "n_test": 2,
    "label_horizon": 20,
    "embargo_pct": 0.02
  },
  "thresholds": {
    "pbo_max": 0.5,
    "min_oos_delta": 0.0,
    "maxdd_tolerance": 0.01,
    "min_dsr": 0.0
  }
}
```

`candidates` must include every configuration inspected in the hypothesis
family, including variants later considered unattractive. `declared_trial_count`
must include the baseline and all related trials; it may be greater than the
number of available curves, but never smaller.

## Command

```bash
PYTHONPATH=src /Users/liweishi/.hermes-v3/.venv/bin/python \
  scripts/formal_gate.py research/experiments/<experiment_id>.json
```

Final evidence is written once to:

```text
building/reports/formal_gate/<experiment_id>/result.json
building/reports/formal_gate/<experiment_id>/REPORT.md
```

Exit codes are `0` for candidate-gate-passed, `1` for rejected, and `2` for
blocked or invalid evidence. A blocked precheck does not consume the one-shot
result.
