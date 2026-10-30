# Dependency Security Remediation

Date: 2026-10-23. Local verification complete; independent review pending. **DEPLOY HOLD; A2 OPEN; Phase B not started.**

## 1. Candidate and Scope

Candidate: `/Users/liweishi/Documents/New project/hermes-daily-failure-remediation-2026-10-23`, branch `codex/daily-failure-evidence`, based on live commit `2db0cdc562309b6222a69aaee8dbdaf51c763b93`.

This increment changes only:

| File | Change |
|---|---|
| requirements.txt | Direct certifi pin: 2026.4.22 -> 2026.10.19 |
| requirements.lock | certifi as above; urllib3 2.7.0 -> 2.8.0; their four distribution hashes |

The complete candidate also includes the preceding daily-failure patch: one production wrapper and nine regression cases. Those source bytes did not change during this increment. They are separate review scopes, now tested together in a fresh updated environment. Do not describe the whole candidate as dependency-only.

The preceding incident handoff and equivalence JSON remain byte-for-byte unchanged. Its red dependency-audit result describes the pre-update lock; this follow-up supplies the new candidate's result without rewriting that history.

Main-directory A2 sources, its frozen packet and live were not modified. Thirteen A2 source/dependency bindings plus its packet manifest digest were rechecked. No stage, commit, push, deployment, official daily, financial-source refresh or real IBKR operation was performed. This independent clone's origin is a local path, not GitHub; no cloud CI result is claimed.

## 2. Why These Versions

- urllib3 2.8.0 fixes PYSEC-2026-4175/4176/4177. Its [official changelog](https://urllib3.readthedocs.io/en/stable/changelog.html) also warns that configurations relying on destination TLS settings overriding proxy TLS settings may require changes.
- certifi 2026.10.19 addresses PYSEC-2026-4320 / GHSA-6q48-6c7w-9gw2. The [maintainer advisory](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2) initially names 2026.10.18; the updated [OSV record](https://osv.dev/vulnerability/PYSEC-2026-4320) recommends 2026.10.19 after unaffected roots were restored. This candidate intentionally selects 2026.10.19.

Both versions' PyPI JSON metadata was fetched directly. Wheels and sdists were downloaded to a temporary directory and all four actual SHA256 digests matched the metadata and candidate lock. Neither release was yanked. Metadata and download checks are retained in the evidence packet; binary distributions are not copied into the repository.

## 3. Lock Integrity and Installation

The package graph remains 32 production packages. Structured parsing verifies that exactly certifi and urllib3 changed; the other 30 requirement/version/hash records are identical. Updating requirements.txt as well prevents future resolution from restoring the old direct certifi pin.

The original lock header is a historical generic generation command, not a claim that unconstrained resolution reproduces this candidate today. The actual verification command was:

```sh
uv pip compile requirements.txt --constraint requirements.lock --generate-hashes --python-version 3.11 --no-header --output-file <temporary>/constrained-regeneration.lock --quiet
```

The regenerated lock was preserved and matched the candidate's structured requirements and complete hash sets; header/comments are not claimed byte-identical. Free re-resolution can change unrelated transitive dependencies and is not the candidate verification method.

Two separate Python 3.11.15 environments were created, using uv 0.11.7:

- Baseline: `uv pip sync --require-hashes` from the preserved old lock.
- Candidate: `uv pip sync --require-hashes` from the new lock, followed by editable dev installation constrained by the new lock; pytest was held at 9.1.1, Ruff at 0.15.22 and mypy at 2.3.0.

Every installed candidate production version was checked against all 32 pins after dev installation. NumPy 2.0.2 and SciPy 1.13.1 remain installed and compatible. This is a fresh hash-checked production installation, not a fully hermetic archived interpreter/dev environment.

## 4. Behavior and Regression Evidence

The offline probe imports no Hermes modules. It forbids socket connections, parses an in-memory chunked response with a 70,000-byte zero-length line, and loads only the installed certifi CA bundle into a verification-enabled TLS client context.

| Check | Old environment | New environment |
|---|---|---|
| Oversized chunk line | Accepted | Rejected with the expected maximum-length error |
| Affected emSign ECC Root CA - G3 | Present | Absent |
| TLS certificate/hostname verification | Enabled | Enabled |
| Probe network attempts | 0 | 0 |
| Probe status / exit | FAIL / 1 | PASS / 0 |
| Locked-production dependency audit | 4 advisories / exit 1 | 0 known advisories / exit 0 |

The initial probe fixture omitted the HTTP request method and failed before exercising the parser. It was corrected to GET before the recorded old/new behavior comparison. That fixture error is not used as the expected baseline rejection.

| Final validation | Result |
|---|---|
| Incident-focused combination in new environment | 75 passed in 17.62s |
| Full combined candidate suite | 1490 passed in 158.89s |
| Governance | 8/8 OK; ibkr_readonly=true |
| Installed-environment pip check | No broken requirements |
| CI severe Ruff; offline probe full Ruff | PASS |
| Exact four-module CI mypy | PASS |
| Compile / diff whitespace | PASS |
| Unchanged comparator, old runtime | Four-date strict all_equal=true |
| Unchanged comparator, new runtime | Four-date strict all_equal=true |
| Cross-runtime verification | Full normalized payload and all seven business-artifact SHA256 summaries match for every date |

The four dates are 2022-01-03, 2022-01-25, 2026-05-29 and 2026-06-04. Both comparator runs use a fresh git archive of the live base and its tracked data seed. Comparing the old/new report summaries explicitly checks dependency-runtime changes; it is not merely a single-environment source comparison. The comparator and its normalization rules were not edited. Equality concerns normalized business content, not raw SQLite bytes or every possible market date.

## 5. Frozen Bindings

Evidence: `building/reports/dependency_security/2026-10-23/`, 19 files including the manifest. SHA256SUMS.json binds the other 18 files and has SHA256:

`fdf26f21c0e7370e056a291e370463370548ca1294855c69aa5e78b8549c9069`

| Current artifact | SHA256 |
|---|---|
| requirements.txt | 037be4f24a13220684ec36939d37a7f11659a8711b281f2004d5148454f77931 |
| requirements.lock | 71fc586a3909e80ae3c3fcc600e17d1082f39bae7ececed59a1c32038ba73e62 |
| Offline security probe | 9bcd9a70bf43bb0321108f6375c82a9c747e652483dd8d35607ac55e5d5eccc8 |
| Unchanged daily wrapper | abb69acb5778c20159844863d6fb94499794bde31f85f4de124b43d59191315b |
| Unchanged incident tests | 362b877b028a14a0da2d3baa75ec9e94e645141b4146fa4ec23b14af52976a26 |
| Unchanged comparator | 19540147b21004355d0f54eb14c0455301bddb870b47a370b0a753178d5bd76d |

These are reproducibility bindings, not independent approval or signatures. The old incident report/equivalence and main A2 packet were not overwritten. Environment package inventories, both audit JSONs, both behavior JSONs, both runtime equivalence reports, cross-runtime verification, full-suite log and governance output are included.

## 6. Boundaries and Next Step

The probe demonstrates two concrete offline behaviors, not real proxy connectivity or universal TLS security. The production-source scan found no custom Python proxy TLS configuration; deployed proxy environment settings were not inspected. Updating certifi does not replace OS, JVM/IBKR or all native clients' trust stores. No TLS verification was disabled.

The local candidate's dependency findings are cleared as of this scan. This does not update installed live packages, certify the main A2 candidate or prove that SOXL's old highest-price discrepancy was repaired. The A2 packet still binds its earlier lock; a future integration must declare the new dependency bytes rather than retag old evidence.

Next engineering slice: unique-conflict versus retry-attempt presentation, retaining raw admission rows and existing thresholds. Backup market candidates remain offline research. Independent review, release-combination CI, explicit deployment authorization and natural scheduled observation remain required; A1/A2/Phase B gates are unchanged.

## 7. Review Checklist

1. Compare only requirements.txt and requirements.lock against preserved before files for this slice; separately inspect the earlier wrapper/test patch for the combined candidate.
2. Recompute the manifest, the two new pin blocks and official wheel/sdist hashes. Verify all other 30 records and installed versions remain unchanged.
3. Run the same offline probe under the two recorded environments; expected exits are 1 and 0, with zero network attempts and verification enabled.
4. Reproduce old/new lock audits, current full suite, governance and exact static scopes. Do not interpret zero known package advisories as a universal security proof.
5. Recompute both strict comparison reports and their cross-runtime normalized payload/artifact summaries without adding comparator exclusions.
6. Keep correctness, commit/push eligibility and deployment/A2 closure as separate decisions. Current author disposition is local verification complete, independent review pending, no Git publication or deployment authorized/performed.
