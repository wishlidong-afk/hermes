# Hermes Five-Day Closure and Environment Reproducibility External Audit

Audit date: 2026-08-28
Repository: `/Users/liweishi/Documents/github/hermes`
Branch: `hermes-docs`
Baseline commit: `66bd598`

## Role

Act as an independent, read-only auditor. Do not trust generated summaries or
the implementer's reported test counts without reproducing them. Review the
working-tree changes against `66bd598`, inspect the underlying evidence, and
return a severity-ordered finding list followed by a deployment disposition.

## Safety Boundaries

- Do not run daily or any official/manual rerun.
- Do not refresh market data or external sources.
- Do not connect to or refresh IBKR.
- Do not modify live, repo data, config, feature flags, routes, scores, or
  baselines.
- Do not commit, push, deploy, clean, reset, or revert the working tree.
- Temporary isolated virtual environments under `/tmp` are allowed.
- Treat existing environment variables and credentials as secrets. Do not print
  their values; use a synthetic value when testing `FRED_API_KEY` isolation.

## Intended Change Set

The remediation should contain no production Python change and no dependency
version change. Review these implementation files:

1. `.github/workflows/ci.yml`
2. `src/hermes_escape_top/tests/test_ops_entrypoints.py`
3. `src/hermes_escape_top/tests/test_refresh_external_fred_vintage.py`
4. `docs/history/2026-08-28_market_health_five_day_observation_closure.md`

This audit prompt is documentation only and is not an implementation surface.
Flag every other changed or untracked file as scope drift unless it clearly
predates this batch.

## Claimed Remediation

### R1. Five-day natural-run observation closure

The closure document claims that acceptance reports from 2026-08-24 through
2026-08-28 show:

- overall `PASS` on all five days;
- `runtime_integrity=PASS` on all five days;
- `post_deploy_certification=CERTIFIED` on all five days;
- exactly one scheduled audit row per selected official run;
- each score transaction `COMMITTED`, with seven artifacts and no active
  transaction residue;
- 09:00 watchdog `PASS` on all five days;
- market-admission consecutive OK evidence increasing from 1 through 5;
- only explicitly non-blocking IBKR INFO and policy-scoped Dollar operations
  WARN conditions.

Independently read:

```text
/Users/liweishi/.hermes/logs/acceptance/morning_acceptance_2026-08-24.json
/Users/liweishi/.hermes/logs/acceptance/morning_acceptance_2026-08-25.json
/Users/liweishi/.hermes/logs/acceptance/morning_acceptance_2026-08-26.json
/Users/liweishi/.hermes/logs/acceptance/morning_acceptance_2026-08-27.json
/Users/liweishi/.hermes/logs/acceptance/morning_acceptance_2026-08-28.json
```

Verify every table row against the corresponding JSON. Confirm that the
document does not convert `strategy_decision=WARN` into a false all-green claim,
and that its reopen criteria preserve fail-closed behavior.

### R2. FRED test environment isolation

The production credential precedence intentionally allows process
`FRED_API_KEY` to override a config key. The affected adapter identity test is
supposed to test the no-runtime-override path, so it now deletes that environment
variable through pytest's `monkeypatch` fixture.

Confirm:

- production credential resolution code is unchanged;
- tests that explicitly verify process/file/config key precedence remain intact;
- an exported synthetic `FRED_API_KEY` no longer changes the adapter identity
  test;
- the fix does not globally suppress credentials for tests that intentionally
  exercise environment precedence.

### R3. CI dependency compatibility gate

The production runtime contract already pins:

- `numpy==2.0.2`
- `scipy==1.13.1`

The claimed fix does not alter these versions. It adds `python -m pip check`
after the hashed lock and editable development package are installed in CI, plus
a regression assertion that keeps that gate present.

Confirm:

- CI order is lock install, editable install, then `pip check`;
- `requirements.txt`, `requirements.lock`, and `src/pyproject.toml` are
  unchanged;
- a clean isolated reproduction resolves NumPy 2.0.2 and SciPy 1.13.1;
- compatibility check succeeds after editable installation;
- no evidence supports changing dependency versions in this batch.

## Required Independent Checks

Use the repository's configured Python for tests:

```bash
cd /Users/liweishi/Documents/github/hermes

git status --short
git diff --check
git diff --stat
git diff -- config/config.json requirements.txt requirements.lock src/pyproject.toml
git diff -- 'src/hermes_escape_top/**/*.py' ':!src/hermes_escape_top/tests/**'

FRED_API_KEY=external-audit-synthetic-key \
  PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_refresh_external_fred_vintage.py \
  src/hermes_escape_top/tests/test_refresh_external_cli.py -q

FRED_API_KEY=external-audit-synthetic-key \
  PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests -q

PYTHONPATH=src \
  /Users/liweishi/.hermes-v3/.venv/bin/python \
  scripts/check_governance_consistency.py

/Users/liweishi/.hermes-v3/.venv/bin/python -m compileall -q \
  src/hermes_escape_top scripts ops
```

For the dependency reproduction, create a fresh unique directory under `/tmp`;
do not reuse the implementer's environment:

```bash
TMP="$(mktemp -d /tmp/hermes-dependency-external-audit.XXXXXX)"
/Users/liweishi/.local/bin/uv venv --python 3.11 "$TMP"
/Users/liweishi/.local/bin/uv pip sync \
  --python "$TMP/bin/python" requirements.lock
/Users/liweishi/.local/bin/uv pip install \
  --python "$TMP/bin/python" -e './src[dev]'
"$TMP/bin/python" -c \
  'import numpy, scipy; print(numpy.__version__, scipy.__version__)'
/Users/liweishi/.local/bin/uv pip check --python "$TMP/bin/python"
```

Also inspect for accidental safety-boundary changes:

```bash
git diff -- config/config.json
git diff -- requirements.txt requirements.lock src/pyproject.toml
git diff -- 'src/hermes_escape_top/**/*.py' ':!src/hermes_escape_top/tests/**'
git diff --name-only -- '*.csv' '*.db' '*.duckdb' '*.sqlite' '*.parquet'
rg -n 'placeOrder|submitOrder|transmit\s*=\s*True' \
  src/hermes_escape_top --glob '!tests/**'
```

## Audit Questions

Answer each directly:

1. Do the five source acceptance JSON files exactly support every closure-table
   row?
2. Did market admission naturally reach five consecutive OK observations?
3. Are Dollar and IBKR described without understating their limitations or
   falsely blocking strategy health?
4. Can an exported `FRED_API_KEY` still make the previously failing adapter test
   non-hermetic?
5. Did the remediation preserve intentional production environment-key
   precedence?
6. Does CI now detect dependency incompatibility after editable installation?
7. Does an isolated install retain NumPy 2.0.2 and SciPy 1.13.1 and pass the
   compatibility check?
8. Were config, production Python, dependency pins, scoring, routing, feature
   flags, IBKR policy, and live data untouched?
9. Are all tests and governance checks independently reproducible?
10. Is any generated report being accepted without checking its source data?

## Expected Evidence, Not Presumed Truth

The implementer reported:

- FRED-focused tests: `83 passed` with a synthetic exported key;
- full suite: `1382 passed` with a synthetic exported key;
- governance: `7/7 OK`;
- isolated dependency versions: NumPy 2.0.2 and SciPy 1.13.1;
- isolated compatibility check: all installed packages compatible;
- config, production Python, and dependency files: zero diff.

Reproduce these results. A mismatch is a finding, not something to explain away.

## Required Verdict

Report findings first, ordered P0 through P3, with file and line references.
Then provide:

1. disposition for the five-day closure;
2. disposition for the FRED isolation fix;
3. disposition for the CI compatibility gate;
4. exact commands and results;
5. config and production-safety findings;
6. residual risks;
7. one final decision:
   - `APPROVE COMMIT/PUSH`,
   - `REQUEST CHANGES`, or
   - `BLOCK`.

No R6 live deployment should be recommended for this batch because it contains
no production runtime change.
