# FRED / AAII Publisher-Aware Release Policy

Generated from official publisher metadata and the live read-only external-source
ledger on 2026-08-12. This report is evidence for Task 6; it does not change
scoring, routing, SLOs, feature flags, or canonical data.

## Decision

Replace weekday guesses for the four sources below with publisher evidence
carried by each successful or unchanged fetch. A source is instrumented only
when the fetch contains a verified publisher calendar or issue sequence.
Missing publisher metadata leaves the source `UNINSTRUMENTED`; it does not
weaken the existing age SLO or fail-closed canonical validation.

Expected-release reliability remains warning-only until at least five matured
expected releases exist for that source.

## Official Publisher Evidence

| Hermes source | Publisher identity | Exact calendar / issue evidence | Availability mapping |
|---|---|---|---|
| `dollar` | FRED series `DTWEXBGS`; release `17` (`H.10 Foreign Exchange Rates`) | FRED `series/release` plus `release/dates?include_release_dates_with_no_data=true`; Federal Reserve H.10 remains the value witness | A FRED US release date is eligible for the next Shanghai pre-daily run |
| `real_rate` | FRED series `DFII10`; release `18` (`H.15 Selected Interest Rates`) | Same FRED endpoints; returned dates are business-day and holiday aware | A FRED US release date is eligible for the next Shanghai pre-daily run |
| `fred_net_liquidity` | `WALCL` and `WTREGEN` use release `20` (`H.4.1`); `RRPONTSYD` uses release `379` (`Temporary Open Market Operations`) | Preserve the component release IDs and use the union of their official release calendars; do not collapse the mixed weekly/daily source to one guessed weekday | Any component release date is eligible for the next Shanghai pre-daily run |
| `aaii_sentiment` | AAII Insights RSS sentiment-survey items | The issue link/GUID is the publisher issue ID, `pubDate` is the observed publication date, and the content fingerprint is computed from the normalized sentiment issue rather than the mutable whole-feed XML | The next expected issue is derived from the verified sequence of issue IDs and publication dates; no hard-coded Thursday rule |

Official references:

- FRED series-to-release API: <https://fred.stlouisfed.org/docs/api/fred/series/series_release.html>
- FRED exact release-date API: <https://fred.stlouisfed.org/docs/api/fred/release_dates.html>
- AAII official Insights feed: <https://insights.aaii.com/feed>
- Federal Reserve H.10 witness: <https://www.federalreserve.gov/releases/h10/summary/jrxwtfb_nb.htm>

The FRED documentation explicitly notes that release dates come from data
publishers and may precede FRED availability. Hermes therefore keeps the
existing one-day operational grace and treats this new signal as warning-only.

## Holiday And Mixed-Frequency Checks

The FRED release calendar, queried for May-October 2026, contains publisher
holiday shifts that a weekday tuple cannot represent. Examples include H.10 on
2026-05-26 and 2026-09-08 (Tuesday after Monday holidays). H.15 omits US market
holidays rather than emitting a synthetic weekday expectation. H.4.1 is weekly,
while Temporary Open Market Operations is business-daily; net liquidity must
retain both component calendars.

## Existing Ledger Evidence

The live ledger was read without refresh or mutation. Its available history for
these sources starts on 2026-07-01, so it is shorter than 90 calendar days even
though the aggregation window is 90 days.

| Source | Attempts | OK | Canonical advances | Unchanged promotions | Latest certified observation | Channel |
|---|---:|---:|---:|---:|---|---|
| `dollar` | 95 | 94 | 4 | 21 | 2026-08-07 | `fred_api_with_fed_board_h10_witness` |
| `real_rate` | 94 | 94 | 17 | 8 | 2026-08-10 | `fred_api` |
| `fred_net_liquidity` | 95 | 93 | 17 | 8 | 2026-08-11 | `fred_graph_csv` |
| `aaii_sentiment` | 122 | 49 | 3 | 22 | 2026-08-01 | `official_insights_rss` |

The latest AAII feed observed on 2026-08-12 identifies the sentiment issue as
`https://insights.aaii.com/p/aaii-sentiment-survey-optimism-bounces`, published
2026-08-01T15:30:26Z. The full feed SHA changes as unrelated articles arrive,
so it is not a valid issue fingerprint. The normalized issue identity and
sentiment values are the stable evidence instead.

## Ledger Contract

Each instrumented run records:

- `publisher_release_id`: exact FRED release ID(s), or AAII issue GUID/link.
- `publisher_content_fingerprint`: SHA256 of release calendar evidence plus
  fetched series content for FRED, or normalized issue identity/date/values for
  AAII.
- `publisher_release_dates`: publication dates actually observed in the
  publisher calendar or issue sequence.
- `publisher_expected_release_dates`: exact FRED calendar dates, or AAII's
  next date inferred from a verified issue sequence. This field never claims
  that an inferred AAII issue has already been published.
- `publisher_calendar_status`: `VERIFIED` only when identity and dates pass
  validation; otherwise `UNAVAILABLE`.
- `publisher_recovery_evidence`: primary/fallback channel and prior failure for
  a successful fallback recovery.

The reliability layer converts expected publisher dates to eligible Shanghai
operating days, applies the existing grace, and reports expected-release
status as `ADVANCED`, `PENDING`, or `MISSED`. Separately,
`promotion_status=UNCHANGED` means the official publisher was checked and the
same release/issue remained current; it is not a canonical advance.

## Safety Boundary

- Publisher calendar failure cannot fail or promote a canonical by itself.
- Existing SLO, validation, witness, and evidence-drift checks remain binding.
- No historical weekday backfill is fabricated from the new contract.
- Sources without verified publisher evidence remain `UNINSTRUMENTED`.
- Expected-release evidence is advisory until five matured samples exist.
