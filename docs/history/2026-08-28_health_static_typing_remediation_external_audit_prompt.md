# Hermes Health Static Typing Remediation External Audit

Audit date: 2026-08-28
Repository: `/Users/liweishi/Documents/github/hermes`
Branch: `hermes-docs`
Baseline commit: `f8a088d`

## Role and Safety Boundary

Act as an independent read-only auditor. Review the current working tree against
`f8a088d`. Do not commit, push, deploy, refresh data, run daily, connect to IBKR,
or modify live. Temporary isolated files and detached worktrees under `/tmp` are
allowed.

The implementation scope must contain exactly one production file:

- `src/hermes_escape_top/web/health.py`

This audit prompt is documentation only. Flag any other implementation change as
scope drift.

## Trigger

GitHub Actions run `33137092050` for commit `f8a088d` passed dependency
installation, the new `pip check`, and all 1382 tests, then failed the existing
static-safety mypy step with four errors:

```text
health.py:640: incompatible assignment from str | None to str
health.py:649: int() argument may be None
health.py:650: int() argument may be None
health.py:651: int() argument may be None
```

The same four errors are present in the earlier baseline CI run `32546233187`
for commit `66bd598`; they were not introduced by `f8a088d`.

## Claimed Fix

The change is intended to be runtime-equivalent:

1. `_market_admission_rejected_detail` supplies `""` as the default for a
   third-source support dictionary lookup. Both the old `None` and new empty
   string are false in the existing `if support` branch.
2. `_market_admission_is_component_only` stores the three count fields, rejects
   explicit/missing `None` values before conversion, then calls `int()` on the
   narrowed values. The old code caught `TypeError` from `int(None)` and returned
   `False`; the new code returns `False` before the conversion.
3. No health severity, label, threshold, market-admission rule, scoring path,
   routing path, config, flag, dependency, or live data is changed.

## Required Review Questions

Answer each directly:

1. Does the empty-string dictionary default preserve all rendered output and
   branch behavior?
2. Does explicit `None` rejection preserve the old fail-closed result for
   missing count metadata?
3. Are non-None values, including numeric strings, integers, zero, malformed
   strings, and booleans handled exactly as before?
4. Can malformed or legacy market-admission evidence now escape strategy
   degradation?
5. Can component-only evidence be reclassified without all three consistent
   counts and matching row metadata?
6. Does the exact CI mypy command now pass without ignores or exclusions?
7. Do health truth tests and the full suite pass?
8. Are four historical score payloads and all seven business persistence
   artifacts unchanged?
9. Are config, scoring, routing, flags, dependency pins, IBKR policy, and live
   data untouched?
10. Is any finding being dismissed merely because it predates this batch?

## Required Commands

```bash
cd /Users/liweishi/Documents/github/hermes

git status --short
git diff --check
git diff f8a088d -- src/hermes_escape_top/web/health.py
git diff f8a088d -- config/config.json requirements.txt requirements.lock \
  src/pyproject.toml pipeline.py

PY=/tmp/<independent-audit-venv>/bin/python
"$PY" -m ruff check src/hermes_escape_top scripts ops \
  --select E9,F63,F7,F82
"$PY" -m mypy --ignore-missing-imports --follow-imports=skip \
  src/hermes_escape_top/core/data/market_witness.py \
  src/hermes_escape_top/core/data/market_admission.py \
  src/hermes_escape_top/core/backtest/formal_gate.py \
  src/hermes_escape_top/web/health.py

PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_health_truth.py \
  src/hermes_escape_top/tests/test_phase14_web.py -q

PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests -q

PYTHONPATH=src \
  /Users/liweishi/.hermes-v3/.venv/bin/python \
  scripts/check_governance_consistency.py

/Users/liweishi/.hermes-v3/.venv/bin/python -m compileall -q \
  src/hermes_escape_top scripts ops
```

Use a fresh detached worktree at `f8a088d` and independently run
`scripts/compare_pipeline_persistence.py` for:

- 2022-06-30
- 2024-06-28
- 2026-05-29
- 2026-07-10

Require strict `all_equal=true`, `equal=true` for every date, zero differences,
and equality of all seven business persistence artifacts. Inspect the comparator
before trusting its output.

## Implementer Evidence to Reproduce

- exact CI mypy command: success, no issues in four files;
- Ruff severe rules: all checks passed;
- focused health/Web tests: `53 passed`;
- full suite: `1382 passed`;
- governance: `7/7 OK`;
- compile and `git diff --check`: clean;
- strict four-date/seven-artifact comparison: `all_equal=true`, four dates equal,
  zero differences;
- config, dependency files, scoring, routing, flags, and live data: zero diff.

These are claims, not independent proof. Reproduce them.

## Required Verdict

Report findings first, ordered P0 through P3, with exact file and line evidence.
Then provide:

1. behavior-equivalence disposition;
2. static-safety disposition;
3. exact command results;
4. production safety and config findings;
5. residual risks;
6. one final decision: `APPROVE COMMIT/PUSH`, `REQUEST CHANGES`, or `BLOCK`;
7. a separate live-deployment recommendation. A production file changed, even
   though the intended behavior is identical, so do not silently conflate commit
   approval with deployment approval.
