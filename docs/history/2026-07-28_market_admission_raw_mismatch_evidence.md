# Market Admission Raw Mismatch Evidence

Date: 2026-07-28

Status: implemented and locally verified; not committed, pushed, or deployed.

## Objective

Make a Yahoo-versus-Alpaca market-admission mismatch independently auditable without
changing the admission decision. A rejected row now retains the exact normalized OHLCV
values used by the comparator, safe source metadata, and hashes of those normalized values.

## Behavior Contract

- `MATCH` rows keep their previous shape and do not receive `raw_comparison`.
- `NO_WITNESS`, `DATE_MISMATCH`, `PRICE_MISMATCH`, and `VOLUME_MISMATCH` rows receive
  `raw_comparison` evidence.
- Candidate evidence is limited to `date/open/high/low/close/volume`.
- Alpaca evidence is limited to `date/timestamp/open/high/low/close/volume`.
- The witness source records `ALPACA_SIP_1DAY`, the official data endpoint, `1Day`,
  `feed=sip`, and `adjustment=raw`.
- Session provenance records fetch time, requested range, completed-session cutoff,
  symbols, row counts, and a SHA256 over normalized bars.
- The final payload boundary applies an explicit provenance-field allowlist. API keys,
  secrets, headers, arbitrary response fields, and nested caller metadata are discarded.
- Main market-admission schema versions remain v1/v2. Thresholds, status rules, canonical
  promotion, config, flags, score payload, and production state are unchanged.

## Changed Code

- `src/hermes_escape_top/core/data/market_witness.py`
  - Normalizes and hashes candidate/witness bars.
  - Attaches raw evidence only to non-match outcomes.
- `src/hermes_escape_top/core/data/market_admission.py`
  - Carries mismatch evidence into the admission archive.
  - Adds safe Alpaca session provenance and enforces the final allowlist.
- `src/hermes_escape_top/tests/test_market_witness.py`
  - Proves independent recomputation, normalized hashes, field allowlisting, and lean
    `MATCH` rows.
- `src/hermes_escape_top/tests/test_market_admission.py`
  - Proves decision fields are unchanged, evidence is propagated, generated provenance
    excludes credentials, and injected metadata is filtered at serialization.

## Verification

- Focused witness/admission/backfill/history suite: `92 passed`.
- Full suite: `1204 passed in 121.52s`.
- Governance: `7/7 OK`.
- Ruff: passed.
- `compileall`: passed.
- `git diff --check`: passed.

Four-date score and seven-artifact persistence equivalence:

| as_of | Equal | input_hash |
|---|---:|---|
| 2022-06-30 | yes | `cec545d25b63688c07d2536214c0be4daef1c8b5547766dd83b3c4e1c7e98428` |
| 2024-06-28 | yes | `68f631b24b6b9c3cd15196fed0b54c787ea0b061ebcceccb0749f3c52a5e620f` |
| 2026-05-29 | yes | `0f910bfaa76b27a558a1a23820578ba0b695c5f82f841900635aff790c94e9a3` |
| 2026-07-10 | yes | `18ffe225053fc71844fcdd06408478aabe25d9da279c19805b854aceb0c5ef9c` |

Evidence file:

`building/reports/data_quality/MARKET_ADMISSION_RAW_EVIDENCE_EQUIVALENCE_2026_07_28.json`

SHA256:

`ced57d929fab5159a59e166fa0df1f0e4db51bf959dd6589a4936e9fd7a68588`

## Review Checklist

1. Confirm all pre-existing decision fields are byte-for-byte unchanged for the same bars.
2. Recompute close and volume differences solely from `raw_comparison`.
3. Confirm the normalized-bar SHA256 values match the serialized normalized bars.
4. Inject credential-shaped keys into bars and provenance; confirm none survive serialization.
5. Confirm `MATCH` rows do not contain `raw_comparison`.
6. Confirm no config, feature flag, scoring, routing, canonical promotion, or live path changed.
7. Re-run the four-date equivalence report and require `all_equal=true`.

## Release Boundary

This batch is intentionally not deployed. The currently deployed release remains `cb9c99a`.
The next natural scheduled run should be observed before this evidence-only change is bundled
into a later reviewed deployment. Deployment must not trigger an extra official daily run.
