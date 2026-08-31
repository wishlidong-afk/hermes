# Hermes Strict Ten-Pass / 20-Dimension Review

Date: 2026-08-30 (Asia/Shanghai)

Repository: `/Users/liweishi/Documents/github/hermes`

Audited repository commit: `028817ac00a71a36cc24a362d20110059c7a3568`

Audited live release: `028817a_20260828_221151`

Review mode: read-only. No live refresh, daily run, IBKR connection, config flip,
score mutation, formal gate, backtest, deployment, or production code edit was
performed during this review.

## 1. Executive verdict

**Strict consensus score: 8.0 / 10.**

Hermes is now strong at operational safety, fail-closed evidence handling,
transactional persistence, deployment rollback, and regression verification.
The current live service is usable: repository and live release agree, the latest
morning acceptance is `PASS`, `/livez` and `/readyz` return HTTP 200, the strategy
layer is `OK`, and the remaining Dollar and IBKR notices are correctly nonblocking.

The score is not higher because the review found one high-priority decision-evidence
contract gap and several material technical-debt clusters:

1. The same market `as_of` can receive multiple materially different official
   scheduled decisions without explicit revision/supersession semantics.
2. `input_hash` is a market snapshot hash, not a complete decision identity.
3. The implicit `latest` decision clock can ignore a missing required symbol and can
   fall back to the wall-clock date when every required history is absent.
4. A research-only BTC funding feed is effectively enabled by an implicit default,
   outside the explicit config/governance feature inventory.
5. The package data directory remains a default runtime target and currently holds
   602 MiB of ignored generated data inside the working tree.
6. The production surface contains 71 high-complexity functions, 190 non-severe
   Ruff findings, 246 broad exception handlers, 28 disabled flags, and multiple
   non-scoring placeholders.

No P0 issue was found. One P1 evidence-contract finding, seven P2 findings, and six P3
cleanup findings are recorded below.

## 2. Findings first

### P1-1: one `as_of` can silently acquire a second, different official decision

The natural scheduler runs every calendar day at 07:10; it has no weekday filter
(`ops/launchagents/com.hermes.daily.plist:13-19`). The decision clock selects the
minimum latest date among available gating histories
(`src/hermes_escape_top/core/data/decision_as_of.py:32-37`), so Saturday and Sunday
normally share Friday's `as_of`.

Every scheduled run then refetches a three-day overlap
(`src/hermes_escape_top/scripts/run_daily_package.py:181-189`). Backfill merges old
and downloaded frames and keeps the newly downloaded duplicate row
(`src/hermes_escape_top/scripts/backfill_history.py:396-400`). Market admission
checks candidate-versus-witness tolerances, but this path does not establish a
separate finality state for a previously certified canonical row.

This was observed in live evidence, not inferred:

| Scheduled run | `as_of` | `input_hash` | FNGU | MSTR | SOXL |
|---|---|---|---:|---:|---:|
| 2026-08-29 07:10 CST | 2026-08-28 | `047d042d...` | 27.1572 | 35.6833 | 50.4014 |
| 2026-08-30 07:10 CST | 2026-08-28 | `368fff20...` | 29.0850 | 37.8673 | 52.3776 |

Between those two official rows:

- 39 canonical-file evidence records changed while `latest_as_of` stayed
  `2026-08-28`;
- the scored snapshots had 522 value differences;
- AAPL alone changed open `317.0880 -> 316.8500` and volume
  `38,500,185 -> 38,609,800`;
- all three strategy scores moved by roughly two points.

The newer result may be a better late-finalized observation. The defect is not that
revision exists; the defect is that the evidence contract does not label the first
result provisional, the second result revised, or either record as superseding the
other. A user asking for the official decision for `2026-08-28` can receive two
different answers with no first-class revision reason.

**Required remediation:**

1. Add an immutable decision identity containing at least `as_of`, canonical market
   evidence hash, decision-bearing soft-data hash, config/policy hash, and scorer
   release hash.
2. Add `decision_revision`, `supersedes_decision_id`, `revision_reason`, and
   `bar_finality` (`PROVISIONAL` / `FINAL`) to scheduled audit evidence.
3. Preserve the previous canonical row and archive vendor revisions; do not silently
   overwrite an already certified row.
4. Decide one explicit policy: delay final certification until the vendor-finality
   window, use Alpaca SIP as the canonical finalized row, or permit a revision only
   through an explicit recertification path.
5. Add a dashboard banner when the current official decision supersedes an earlier
   decision for the same `as_of`.

Completion proof must include a Friday-close/Weekend-finalization fixture showing
that both records remain auditable and that exactly one is marked current.

### P2-1: `input_hash` is not a complete decision identity

`payload["input_hash"]` is currently only `stable_hash(payload["snapshots"])`
(`src/hermes_escape_top/pipeline.py:382`). It omits config and approved live-policy
hashes, scorer release, market-admission operation, canonical evidence manifests,
source-ledger provenance, and revision state. Soft-input values are represented by
the `SOFT` snapshot, but the provenance of those values is not part of this identity.

The field is then used to bind health reports
(`src/hermes_escape_top/web/server.py:412-459`) and IBKR overlays
(`src/hermes_escape_top/web/refresh.py:122-134`). The complete audit `payload_hash`
does exist (`src/hermes_escape_top/core/data/audit.py:24-35`), but it includes volatile
run metadata and is not a stable semantic decision key.

**Remediation:** retain `input_hash` but rename/document it as `snapshot_hash`; add a
separate deterministic `decision_hash`. Bind reports, overlays, official revisions,
and decision lookups to the composite decision identity. Add a governance test that
changing a decision-bearing config key changes `decision_hash` even when snapshots
are identical.

### P2-2: implicit `latest` is fail-open when required histories are missing

`last_bar_dates` skips a missing/empty required history
(`src/hermes_escape_top/core/data/decision_as_of.py:21-28`). The common date is then
computed from whatever symbols remain, and if none remain, `resolve_decision_as_of`
returns today's wall-clock date
(`src/hermes_escape_top/core/data/decision_as_of.py:40-44`).

Direct reproduction in an isolated directory showed:

- SOXL absent while MSTR/FNGU/QQQ/SPY ended on 2026-08-28 -> `latest` resolved to
  `2026-08-28` instead of failing;
- all five required histories absent -> `latest` resolved to `2026-08-30`.

The scheduled daily wrapper has additional integrity checks, so this is not proof of
a current official-run failure. It is still a fail-open public scoring contract,
because `score_pipeline("latest")` calls this resolver directly
(`src/hermes_escape_top/pipeline.py:185-196`).

**Remediation:** require all gating symbols before returning a common date and raise
`DecisionClockUnavailable` when any are absent. Preserve explicit historical dates.
Add tests for one missing symbol, all missing, unequal dates, and explicit dates.

### P2-3: one default-on research source is outside explicit config governance

`btc_funding_basis` declares `feature_flag="data_btc_funding"` and
`feature_default=True` (`src/hermes_escape_top/core/data/external_sources/profiles.py:413-429`).
That key is absent from repo config, live config, `context.md`, and
`docs/FLAG_REGISTRY.md`. `effective_source_profile` therefore activates it through
the fallback default
(`src/hermes_escape_top/core/data/external_sources/profiles.py:474-500`). Live
precheck confirms that it is
running daily as a research source with weight zero.

It does not affect strategy scores, so this is not an alpha or safety bug. It is an
untracked operational dependency and the clearest example of unrelated data escaping
the explicit governance surface.

**Remediation:** make every source activation explicit. Either add a governed
`research_sources.data_btc_funding=false` entry or set the profile default to false.
Governance must fail when a profile's feature key is absent from config/policy. Keep
research feeds in the shadow lane and out of decision-source health totals.

### P2-4: runtime data can still default into the source package

Relative paths resolve under `PACKAGE_DIR` whenever `HERMES_DATA_DIR` is absent
(`src/hermes_escape_top/config.py:28-37`). Tests and live launchers set an isolated
root, but a developer or one-off CLI invocation can still write into the source tree.

The current clean repository working directory contains:

- 2,210 package-data files totaling 602.24 MiB;
- 2,131 ignored archive files totaling 586.81 MiB;
- 67 still-tracked data files totaling 11.72 MiB.

The `.gitignore` itself says runtime histories should be untracked and even records
the unfinished `git rm --cached` commands (`.gitignore:29-45`). This is a demonstrated
boundary leak, not a hypothetical concern.

**Remediation:** writers must require an explicit runtime data root. Use a small,
immutable `tests/fixtures/data` seed for tests and backtests; make package-data mode
read-only; move or remove ignored runtime artifacts after a verified backup; untrack
runtime history only after the fixture/baseline consumers are migrated.

### P2-5: high-risk decision code remains concentrated in very complex functions

Ruff's C901 scan reports 71 functions over complexity 10. The largest operational
hotspots include:

- `web/server.py::make_handler` complexity 58;
- `web/server.py::do_POST` complexity 39;
- `market_admission.py::_validate_market_admission_v2` complexity 32;
- `sizing_optimizer.py::optimize_targets` complexity 31;
- `formal_gate.py::from_dict` complexity 30;
- `run_daily_package.py::_execute_daily` complexity 29;
- `hard_valves.py::evaluate_hard_valves` complexity 27;
- `fred.py::_reconcile_federal_reserve_h10_history` complexity 26.

The full Ruff scan reports 190 findings, and an AST inventory found 246 broad
`Exception`/`BaseException` handlers across production, scripts, and ops paths
(excluding tests/research). Many are legitimate operational boundaries, but the
concentration makes it harder to prove that an error is surfaced rather than turned
into an empty fallback. `web/server.py` alone has 32 broad catches.

**Remediation:** refactor one risk cluster per release, under behavior-equivalence
tests. Start with route dispatch in `web/server.py`, then admission validation,
sizing constraints/objective/fallback, hard-valve evaluators, and the daily step
runner. Add a changed-file full-Ruff ratchet and expand mypy beyond the current four
files.

### P2-6: scoring capacity and retired experiments enlarge the state space

The generated capacity inventory shows module A defines and can reach 50 points but
is capped at 20 for all three sleeves. Sixty percent of reachable A points can be
clipped. This means additional correlated macro/sentiment factors often cannot alter
the final module score and can instead change which evidence reaches the cap.

Repo config also contains 44 feature flags, 28 of them false. Several are permanently
rejected or unimplemented (`use_decision_stabilizer`, `use_status_hysteresis`,
`use_close_confirmation`, `use_hm2_buffer`, `data_gex`, `use_meta_label`) but remain
inside production config and code branches. The factor inventory also retains
non-scoring placeholders for CNN fear/greed, social euphoria, and two MSTR D factors.

**Remediation:** do not add factors. Move rejected experiments and stubs to a
research/legacy namespace, preserve only their evidence cards, and remove their
production config branches after a deprecation release. Hide zero-point placeholders
from operational factor tables. Any A-module redesign must be pre-registered and pass
the formal gate; it is not a cleanup refactor.

### P2-7: morning acceptance still mixes nonblocking operations into `strategy_decision`

Morning acceptance defines only two readiness buckets: runtime integrity and strategy
decision (`ops/morning_acceptance.py:31-42`). Both bound-health and dashboard-health
aggregate strategy, positions, operations, and auxiliary warnings
(`ops/morning_acceptance.py:1104-1117`). Therefore current reports say
`strategy_decision=WARN` solely because Dollar is publisher-late and IBKR is stale,
even while `/readyz` reports `strategy_level=OK`.

The warnings are correctly nonblocking, but the label is semantically misleading and
has repeatedly made operational status harder to read.

**Remediation:** make acceptance mirror the four health layers:
`strategy_decision`, `operations`, `position_reconciliation`, and `auxiliary_flows`.
Only the strategy layer may set `strategy_decision=WARN/FAIL`; Dollar policy lag and
IBKR stale remain in their own fields.

### P3 residual findings

1. The scheduled receipt is finalized `OK` before the system-health report is written
   (`src/hermes_escape_top/scripts/run_daily_package.py:1608-1621`). Normal
   exceptions overwrite it with `FAILED`,
   but kill/power-loss in that narrow window can leave a green receipt with missing
   bound evidence. Write health first, or commit both through one final receipt state.
2. API evidence errors are returned with HTTP 200 for manifest, external-source, and
   health endpoints (`src/hermes_escape_top/web/server.py:819-843`). Keep dashboard
   fallback behavior, but
   return 5xx for API exceptions. The POST path also reads unbounded `Content-Length`
   (`src/hermes_escape_top/web/server.py:885-892`); add a small local request limit
   and 413.
3. `atomic_write_csv` uses same-directory `os.replace` but does not fsync the file
   (`src/hermes_escape_top/core/safe_io.py:147-170`). Atomic visibility is correct;
   crash durability is
   weaker than `atomic_write_text`. Decide explicitly whether CSV power-loss
   durability is required, then document or align the implementations.
4. The persistence comparator fingerprints only `src/hermes_escape_top`
   (`scripts/compare_pipeline_persistence.py:36`). It cannot prove equivalence for
   `ops/` or top-level `scripts/` changes. Add declared source roots or an explicit
   out-of-scope assertion.
5. `next_scheduled_at` in a `CERTIFIED` health payload is the first natural run after
   deployment, not the next future run (`src/hermes_escape_top/web/health.py:106-137`).
   Rename it to
   `certification_scheduled_at` or clear it after certification.
6. `docs/FLAG_REGISTRY.md:107` still names the live combo and rollback path as GLD,
   while config and context use IAU. Preserve GLD as historical gate evidence, but
   make the current execution and rollback symbol IAU explicit.

## 3. Ten independent review passes

The ten passes were complementary, not ten copies of one checklist. Scores are
ordinal engineering judgments, not statistical estimates.

| Pass | Primary lens | Score | Main result |
|---:|---|---:|---|
| 1 | Live/repo/runtime evidence | 8.8 | Repo and live align; current acceptance PASS; strategy ready |
| 2 | Official audit chronology | 7.4 | Same-`as_of` official revisions lack supersession identity |
| 3 | Market-source admission | 8.5 | Dual-source and fail-closed checks are strong; canonical finality remains open |
| 4 | External-source automation | 8.6 | AAII/NAAIM automatic; Dollar warning honest; one implicit research feed |
| 5 | PIT and decision clock | 6.8 | Historical PIT is strong; implicit latest and revision finality need hardening |
| 6 | Scoring/factors/routing | 7.4 | Caps and hard valves are explicit; A saturation and branch inventory are high |
| 7 | Persistence/concurrency | 9.0 | Capability lock, transaction manifest, recovery, and seven artifacts are strong |
| 8 | Deploy/health/Web API | 8.0 | R6 and layered health are strong; API/error and readiness naming debt remains |
| 9 | Tests/static/dependencies | 7.5 | 1,392 tests and governance pass; static enforcement is intentionally narrow |
| 10 | Repository hygiene/governance | 7.3 | Governance is strong; data/report volume and rejected feature surface remain |

Ten-pass mean: **7.93**, rounded consensus: **8.0 / 10**.

## 4. Twenty-dimension scorecard

| # | Dimension | Score | Strict assessment | Highest-value improvement |
|---:|---|---:|---|---|
| 1 | Read-only/order safety boundary | 9.5 | IBKR readonly and no production order path; token/loopback policy explicit | Keep invariant tests and audit every new endpoint |
| 2 | Source authenticity | 8.7 | Official/FRED/CBOE/AAII/NAAIM evidence is strong | Make all active source identities config-explicit |
| 3 | Market redundancy/admission | 8.5 | Yahoo + Alpaca SIP, Coinbase BTC, CBOE official paths fail closed | Add canonical finality and revision evidence |
| 4 | Freshness/calendar semantics | 8.0 | Trading-day and publisher-calendar handling is mature | Separate publisher lag from stale observation everywhere |
| 5 | Historical revision and PIT | 6.0 | FRED/VIX3M controls are strong; general OHLC overlap can rewrite certified rows | Implement revision quarantine/finality for market history |
| 6 | External automation | 8.8 | AAII/NAAIM now automatic with fallback and ledger | Remove implicit default-on research work |
| 7 | Provenance/ledger/traceability | 9.0 | Raw, normalized, validation, SHA, promotion and reliability evidence are rich | Bind canonical revision and decision IDs end-to-end |
| 8 | Decision identity/reproducibility | 6.2 | Full payload hash exists, but `input_hash` is incomplete and same-date revisions are unlabeled | Add stable composite `decision_hash` |
| 9 | Factor architecture/orthogonality | 6.5 | Registry and capacity inventory are excellent; A cap saturation remains structural | Retire placeholders/failed flags; redesign only through formal gate |
| 10 | Missing-data/confidence semantics | 8.6 | No-advice, weighted missingness, and confidence spine are explicit | Add missing-gating-symbol decision-clock rejection |
| 11 | Hard valves/fail-closed behavior | 8.8 | Structured candidates, suspect guard, and evidence-driven blocking are strong | Split per-valve evaluators to reduce complexity |
| 12 | Routing/sizing/portfolio risk | 7.4 | DEFCON and stress evidence are explicit; optimizer is a complexity hotspot | Separate constraints, objective, fallback; add property tests |
| 13 | Baseline/formal-gate evidence | 8.8 | Current next-open baseline, provenance, cost and timing evidence are strong | Extend comparator source-scope declaration |
| 14 | Persistence/atomicity | 9.1 | Seven-artifact transaction and recovery are strong | Close receipt/health finalization window |
| 15 | Concurrency/recovery | 9.0 | Single lease, capability token, 409 BUSY, deploy lock and rollback are strong | Keep all future writers behind the transaction boundary |
| 16 | Deployment/config governance | 7.8 | R6 atomic release and attestation are strong; repo/live config split adds cognitive load | Replace interactive config choice with versioned approved overlay |
| 17 | Health/acceptance observability | 8.6 | Four health layers and independent cron evidence work | Split acceptance readiness into the same four layers |
| 18 | Web/API truthfulness | 7.2 | Dashboard is evidence-rich and current | Return real API error codes and decompose handler routing |
| 19 | Tests/static/dependencies | 7.6 | 1,392 tests, 8/8 governance, compatible deps, no known CVEs | Ratchet full Ruff and expand mypy by risk |
| 20 | Architecture/repo hygiene/docs | 5.8 | Very large modules, stale branches, package runtime data, and report bloat remain | Explicit data root, fixture migration, experiment retirement |

Arithmetic mean: **7.99 / 10**.

## 5. Technical-debt inventory

### Code shape

- 212 non-test Python files across `src/hermes_escape_top`, `scripts`, and `ops`.
- 58,899 physical lines; 51,565 nonblank/non-comment lines.
- Largest files: `web/render.py` 5,107; `run_daily_package.py` 1,821;
  `pipeline.py` 1,431; `morning_acceptance.py` 1,335;
  `refresh_external.py` 1,251; `web/server.py` 1,143; `web/health.py` 1,014.
- 71 C901 findings.
- 190 full-Ruff findings: 53 unused imports, 37 late imports, 37 placeholder
  f-strings, 36 one-line compound statements, 11 unused variables, and smaller
  categories.
- CI Ruff currently gates severe correctness classes only. CI mypy covers exactly
  four files (`.github/workflows/ci.yml`).

### Branch/state inventory

- 44 repo feature flags: 16 true, 28 false.
- Live has 19 true flags and three intentional repo/live semantic differences:
  market admission, CBOE official indices, and BTC spot witness.
- Four missing live keys are semantically false, so they do not change behavior, but
  config shape still differs.
- Rejected experiments remain in production branches after their evidence cards have
  reached terminal state.

### Data and repository inventory

- Tracked checkout: 926 files, 109.59 MiB.
- `building/reports`: 273 tracked files, 92.92 MiB, including a 72 MiB uncompressed
  legacy backtest JSON and an 8.2 MiB compressed current baseline source.
- Package data: 67 tracked files, 11.72 MiB.
- Ignored generated package data currently present: 602.24 MiB.
- Live shared runtime: about 865 MiB; external-source evidence accounts for about
  671 MiB. Runtime retention is currently healthy, so this is capacity debt rather
  than an incident.

### Unrelated/non-decision data

The following should not share the same operational prominence as decision inputs:

1. `btc_funding_basis`: active daily research feed, weight zero, implicit default-on.
2. `occ_equity_pcr`: inactive research history; useful evidence, not decision health.
3. COT and on-chain/mNAV research artifacts while their production flags remain off.
4. Zero-point CNN/social/MSTR placeholders in operational factor views.
5. Rejected feature implementations retained in the production configuration matrix.

The recommendation is not to delete historical evidence. It is to move research,
rejected experiments, and placeholders out of the production decision surface while
keeping immutable evidence in a dedicated research registry.

## 6. Verification performed

| Check | Result |
|---|---|
| Repo branch/clean/sync | `hermes-docs`, clean, equal to `origin/hermes-docs` |
| Repo HEAD / live VERSION | `028817a` / `028817a_20260828_221151` |
| Latest morning acceptance | PASS; runtime PASS; certification CERTIFIED |
| Live liveness/readiness | `/livez` 200; `/readyz` 200; strategy level OK |
| Full tests | **1,392 passed in 133.62s** |
| Governance | **8/8 OK**, `ibkr_readonly=true` |
| Severe Ruff gate | PASS |
| Exact CI mypy scope | PASS, 4 files |
| Full Ruff inventory | 190 findings; recorded as debt, not hidden |
| C901 inventory | 71 functions over threshold |
| Compile | PASS |
| Dependency compatibility | PASS, 32 packages compatible |
| Dependency vulnerability audit | No known vulnerabilities |
| Current external source readiness | ready; Dollar policy warning only; no blocker |
| Current market admission streak | 6 consecutive OK, mature |

No full backtest or formal gate was run. There was no scoring or routing change to
evaluate, and starting a new alpha experiment would violate the scope of this audit.
The committed current baseline and governance evidence were checked instead.

## 7. Recommended execution plan

### Release A: decision-evidence identity (highest priority)

1. Add canonical revision evidence without changing scoring behavior.
2. Add `snapshot_hash`, `policy_hash`, and composite `decision_hash`.
3. Add same-`as_of` revision/supersession metadata and dashboard disclosure.
4. Make implicit `latest` fail closed on any missing gating symbol.

Verification: focused identity/finality tests, two-day vendor-revision fixture,
same-date audit chronology test, full suite, governance, four-date strict persistence
equivalence. No config flip.

### Release B: governance and data-root closure

1. Require every effective source flag to exist in config/policy.
2. Default BTC funding research OFF or move it to an explicit research manifest.
3. Require an explicit writable `HERMES_DATA_DIR` outside tests/live launchers.
4. Build a minimal immutable test seed, then remove tracked runtime histories and
   clean ignored package artifacts after backup.

Verification: config/profile completeness gate, writer-without-data-root rejection,
fresh-clone test run, baseline provenance check, and repo-size report.

### Release C: reduce production state space

1. Retire terminal rejected flags from production config and code paths.
2. Move stubs/placeholders to the research registry and hide them in operational UI.
3. Split `web/server.py` routing and error handling.
4. Split market-admission validation, sizing, hard valves, and daily orchestration in
   separate behavior-preserving releases.
5. Add changed-file full Ruff and expand mypy in risk order.

Verification: one module per change, focused tests first, full suite, governance,
strict persistence equivalence, and external review before deployment.

### Release D: health/API semantics

1. Mirror the four health layers in morning acceptance.
2. Return 5xx for API evidence failures, 413 for oversized local POSTs, and preserve
   HTML fallback behavior.
3. Finalize receipt only after bound health evidence is durable.
4. Rename certification schedule fields and correct GLD/IAU registry wording.

Verification: HTTP-level tests, kill/fault injection around receipt finalization,
morning-acceptance fixtures, full suite, then one natural-run observation.

### Strategy work remains paused

Do not add new factors, revive rejected experiments, or alter caps/routing until
Releases A and B are complete and observed in natural runs. If module A is later
redesigned, pre-register ownership and cap semantics and run the formal gate once.

## 8. Final recommendation

The system does not need emergency shutdown. It is operationally healthy and much
safer than its earlier versions. The next work should be **decision evidence and
subtraction**, not alpha expansion:

1. close same-date official revision identity;
2. make the decision clock fail closed;
3. make every active source explicit;
4. move runtime/test data out of the package;
5. retire dead branches and split the most complex operational entry points.

Those changes improve trust, auditability, and maintainability without changing the
strategy itself.
