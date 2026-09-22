# Soup Sieve security remediation

Date: 2026-09-22. Baseline: `8809a773f9044c5273d2c0ad42cb55b4eff1002a`.

## Scope and disposition

The only dependency/runtime input changed is `requirements.lock`: Soup Sieve
2.8.4 -> 2.9 and its two distribution hashes. No other pins, production Python,
config, flags, admission thresholds, identity logic, comparator, or deployment
script changed. Evidence and this document are additional review artifacts.

Local verification: PASS. Commit/push can proceed; cloud CI must be checked on
the resulting commit. This document does not assert that cloud CI has passed.
Live deployment is NOT performed or authorized by this dependency batch.
The three unrelated untracked 2026-09-05 planning documents remain untouched.

## Cause and precise security claim

The preceding commit's CI failed dependency audit:
[CI run 35673943535](https://github.com/wishlidong-afk/hermes/actions/runs/35673943535).
The old lock independently reproduces two findings (audit exit 1):

- CVE-2026-85999: [maintainer advisory](https://github.com/facelessuser/soupsieve/security/advisories/GHSA-j934-xhv5-fg8f).
- CVE-2026-86000: [maintainer advisory](https://github.com/facelessuser/soupsieve/security/advisories/GHSA-gjv8-xp57-g29c).

The maintainer's patched release is 2.9 (the audit database spells it 2.9.0).
These are selector-processing denial-of-service vulnerabilities. Do not confuse
untrusted HTML with attacker-controlled CSS selector strings, or claim a proven
Hermes exploit. Soup Sieve is transitively required through Beautiful Soup.
No unbounded exploit benchmark was run. The replacement lock audit exits 0 with
no known vulnerabilities as of this check, not a guarantee against unknown ones.

The lock was generated, not hand-pinned with invented hashes:

```sh
uv pip compile requirements.txt --generate-hashes --python-version 3.11 \
  --upgrade-package soupsieve==2.9 --output-file requirements.lock --quiet
```

Review confirmed exactly three replaced lines. uv revalidated two corrupted
local cache entries successfully; resolution itself completed normally.

## Verification

All installs used disposable environments, not the production environment.
Candidate: CPython 3.11.15, NumPy 2.0.2, pandas 2.3.3, SciPy 1.13.1,
Soup Sieve 2.9. Baseline: the same production dependency versions except
Soup Sieve 2.8.4. Candidate additionally includes development/test tools;
the evidence records both complete package inventories and checks every locked
production package is installed on both sides with only Soup Sieve differing.

| Check | Result |
| --- | --- |
| Hashed lock install, then editable dev install | PASS |
| pip check after editable install | No broken requirements |
| Old lock security audit | Expected FAIL: exactly the two CVEs above |
| New lock security audit | PASS: no known vulnerabilities |
| AAII/NAAIM/CBOE/FRED/market-soft/failure-drill focused tests | 108 passed |
| Full suite with synthetic FRED_API_KEY | 1481 passed in 184.07s |
| Governance | 8/8 OK, ibkr_readonly=true |
| CI severe Ruff selection | PASS |
| Exact CI mypy four-module command | PASS |
| Compile and diff whitespace check | PASS |
| Strict cross-environment scoring/persistence | 4/4 equal |

## Cross-environment evidence, not same-environment replay

`building/reports/dependency_security/2026-09-22/verify_dependencies.py` is an
evidence-only driver, not imported by production. It calls the unchanged
comparator's `_run_and_snapshot`, `_differences`, and `_summary` functions.
Both sides use a frozen `git archive` of baseline 8809a77 and its tracked seed
data. Each score executes sequentially in its own process and freshly isolated
data root, with `include_ibkr=False`; no live histories or state are used.

The old side uses a separate interpreter installed from the old lock, and the
new side uses a separate interpreter installed from the new lock. No new
normalizations or comparator exclusions were introduced. Existing volatile
timestamps, temporary roots and timestamp-derived audit payload hashes retain
the comparator's existing normalization; this is strict under that contract,
not a claim of raw SQLite byte equality.

| Date | Full normalized payload + input_hash + seven business artifacts |
| --- | --- |
| 2022-01-03 | Equal; zero strict differences |
| 2022-01-25 | Equal; zero strict differences |
| 2026-05-29 | Equal; zero strict differences |
| 2026-06-04 | Equal; zero strict differences |

`equivalence.json` binds source and seed manifests, both lock hashes,
comparator and driver hashes, interpreter evidence and package inventories.
Artifacts are four SQLite databases, two JSONL ledgers and the dated soft
adapter snapshot. Every artifact exists on both sides on every date.

To independently reproduce, create a fresh archive of baseline 8809a77, install
its lock in OLD_PY and the candidate lock plus dev extras in NEW_PY, then run:

```sh
PYTHONDONTWRITEBYTECODE=1 FRED_API_KEY=external-audit-synthetic-key \
  "$NEW_PY" building/reports/dependency_security/2026-09-22/verify_dependencies.py \
  --source "$FROZEN_SOURCE" --old-python "$OLD_PY" --new-python "$NEW_PY" \
  --old-lock "$FROZEN_SOURCE/requirements.lock" --new-lock requirements.lock \
  --output "$TEMP_OUTPUT/equivalence.json"
```

Run the full suite from the real repository (the test seeder uses git's tracked
file inventory), with NEW_PY, `PYTHONPATH=src:src/hermes_escape_top/tests` and a
synthetic FRED key. `pip-audit-before.json`, `pip-audit.json`, `full-suite.log`
and `governance.json` retain the local verification outputs.

## Self-review and remaining gates

- No broad dependency update, vulnerability ignore, CI bypass, new scoring
  behavior, or policy relaxation was used to make the security check pass.
- Four historical comparisons do not prove every possible parser input or a
  future live network response. Parsing-focused tests add bounded coverage.
- The old vulnerable environment exists only under a temporary test directory;
  it is not a deployment candidate. No live interpreter was installed into.
- After commit/push, wait for that exact commit's cloud CI, including audit and
  governance, instead of reusing the previous failed run or local results.
- CI green alone does not deploy the recorder or update live dependencies.
  Any later R6 release needs its own dependency-install/rollback review and
  explicit approval; keep live config, exclude active writers, avoid the daily
  window, and never rerun official daily to manufacture natural evidence.
- This batch does not close A1 or authorize Phase B. The diagnostic recorder
  still needs an approved deployment and subsequent natural-run observation.
