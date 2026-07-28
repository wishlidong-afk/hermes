# Market Admission External Audit Remediation

Date: 2026-07-28

Status: external findings reviewed and locally remediated; not committed, pushed, or deployed.

## Disposition

| Item | Disposition | Change |
|---|---|---|
| F-1: source manifest included absolute paths | Fixed | Manifest entries now retain only the dated artifact filename. Identical artifacts under different archive roots produce the same manifest SHA256. |
| F-2: first artifact per session can look conservative | Contract clarified | The algorithm remains intentional: it measures whether the first observed official artifact for a completed session was blocked. The machine-readable report now records `FIRST_ARTIFACT_PER_COMPLETED_THROUGH`, and the review explains that it is not an end-of-session success rate. |
| RR-3: no direct raw-evidence tests for early-return paths | Fixed | Added explicit `NO_WITNESS` and `DATE_MISMATCH` tests asserting candidate/witness bar presence and normalized hashes. |
| B5 evidence overstatement | Fixed | The prior audit said max OHLC was independently recomputed, but the test only recomputed close and volume. The test now independently recomputes all four OHLC differences and verifies their maximum. |
| RR-4: combined Alpaca/Coinbase credential injection | Accepted residual P3 | Alpaca provenance is filtered at the final serializer; Coinbase provenance is a separate public-source contract with no authentication headers. Existing partial-failure tests remain green. |

## Reproducibility Evidence

The reliability source manifest changed from machine-specific absolute paths to portable dated
filenames. Regeneration from the same 15 live artifacts produced:

- artifact manifest SHA256: `7451001a0c44db3b43373d60117665cf3dc0a6adcf48996b40ed96ada4edd901`;
- available sessions: `11/30`;
- blocked sessions: `5/11` (`45.45%`);
- blocking events: 7 total, 5 matured and recovered, 2 pending;
- policy: `HOLD_FAIL_CLOSED_POLICY`.

Only the manifest identity representation changed. Study conclusions and admission policy did not.

## Verification

- Focused external-audit scope: `92 passed in 0.51s`.
- Full suite: `1204 passed in 121.52s`.
- No config, scoring, routing, canonical-promotion, threshold, or live-state change.
- Raw-evidence four-date/seven-artifact report remains `all_equal=true`.

## Release Boundary

The independent audit approved commit/push only and required the first natural 07:10 scheduled run
under live `cb9c99a` before deployment consideration. These P3 remediations do not change that gate.
