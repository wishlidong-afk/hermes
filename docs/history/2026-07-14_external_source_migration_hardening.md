# External Source Migration Hardening - 2026-07-14

## Scope

This batch completed three sequential items:

1. harden NAAIM workbook discovery and subscription-migration fallback;
2. remove AAII's public results page as a single automation point;
3. define a separate governance lane for PIT data-correctness migrations.

No scoring formula, routing rule, `pipeline.py`, `config.json`, or live canonical
file was modified during implementation or verification.

## NAAIM

The official NAAIM page currently states that the Exposure Index will move to a
subscription model on 2026-08-01. The current public workbook is
`USE_Data-since-Inception_2026-07-08.xlsx`.

Changes:

- parse `href`, `data-href`, and `data-url` workbook links;
- accept only `naaim.org` and its subdomains;
- prefer since-inception workbooks and choose the latest embedded issue date;
- preserve the certified canonical byte-for-byte on fetch failure;
- prove direct official download and official-file import produce identical
  canonical CSV bytes and bind the same workbook SHA-256.

Isolated live-network drill:

| Evidence | Result |
|---|---|
| Direct official route | `OK` |
| Official-file import route | `OK` |
| Workbook | `USE_Data-since-Inception_2026-07-08.xlsx` |
| Latest issue | `2026-07-08` |
| Parsed rows | 1044 |
| Workbook SHA equality | true |
| Canonical byte equality | true |

The subscription credential and license remain an operator responsibility.
After a loss of authorized access, Hermes freezes the last certified canonical
and reports the source failure; it does not substitute a mirror.

## AAII

AAII's old results endpoint can be blocked by Imperva for one interpreter or
network path while AAII's own `https://insights.aaii.com/feed` remains public.
The adapter now tries:

1. AAII results page;
2. AAII official Insights RSS;
3. official `sentiment.xls` import through ExternalSourceRunner.

The RSS parser accepts only AAII Sentiment Survey posts and only the labeled
`This week's Sentiment Survey results` block. It validates Bullish, Neutral and
Bearish shares before promotion. The RSS artifact's own `pubDate` is the PIT
availability date; it is never backfilled to the earlier survey/result date.
The immutable RSS XML, publication timestamp, URL and SHA-256 remain in raw
evidence.

Isolated live-network drills:

| Runtime/path | Result |
|---|---|
| Hermes venv, results page blocked | RSS fallback `OK`, latest `2026-07-11` |
| `/usr/bin/python3`, results page available | primary page `OK`, latest `2026-07-09` |
| RSS source URL in ledger | `https://insights.aaii.com/feed` |
| RSS artifact | `aaii_insights_feed.xml`, SHA-256 recorded |

This improves unattended operation without using a third-party mirror or
bypassing a login wall. If both official publication surfaces fail, the existing
manual official-file path remains the only promotion fallback.

## PIT Governance

[`ADR-001`](../adr/ADR-001-pit-data-correctness-migrations.md) separates:

- alpha experiments, which require positive formal-gate evidence; and
- replacements of an approximate representation with a more authoritative PIT
  representation, which require correctness, replay, persistence, impact,
  rollback and human-approval evidence but not positive alpha.

The ADR is prospective. `fred-vintage-pit-v1` remains `Rejected / NO_FLIP` and
cannot be renamed, retuned, rerun, or retroactively authorized. Any future exact
FRED production migration needs a new migration ID and manifest.

Formal-gate v1 manifests remain immutable alpha experiments. Formal-gate v2
requires an explicit `governance_lane`; a data-correctness run records impact as
`MIGRATION_IMPACT_RECORDED / NO_FLIP` and still waits for the ADR's correctness
evidence and human approval.

## Verification

- NAAIM/AAII/runner/profile/formal-gate/governance focused set: 77 passed.
- Repository governance checker: all four checks `OK`.
- `git diff --check`: passed.
- Python compileall: passed.
- Full suite after review remediation: **1004 passed**.

## Residual Risks

1. NAAIM's 2026-08-01 subscription contract may change the authenticated file
   URL or format. The code fails closed, but authorized access still needs a
   human owner.
2. AAII may change the wording or XML shape of its official feed. Validation and
   canonical freeze prevent silent corruption; they cannot guarantee delivery.
3. The AAII RSS route is deliberately conservative and may make a weekly value
   available about two days later than the results page. This is an automation
   latency cost, not a reason to backdate the RSS evidence.
4. Source URL precedence now records the actual raw route before the static spec
   URL. All source tests pass, and raw evidence retains both route-specific
   metadata and immutable artifacts.
