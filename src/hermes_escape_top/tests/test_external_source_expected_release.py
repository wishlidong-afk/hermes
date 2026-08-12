from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd

from hermes_escape_top.core.data.external_sources.aaii import AaiiSentimentAdapter
from hermes_escape_top.core.data.external_sources.fred import FredNetLiquidityAdapter
from hermes_escape_top.core.data.external_sources.fred import FredPercentileAdapter
from hermes_escape_top.core.data.external_sources.ledger import (
    append_source_run,
    source_reliability,
)
from hermes_escape_top.core.data.external_sources.registry import ExternalSourceSpec
from hermes_escape_top.core.data.external_sources.runner import run_external_source_refresh


def _record(
    source_id: str,
    when: str,
    *,
    advanced: bool,
    release_dates: list[str] | None = None,
    release_id: str | None = None,
    fingerprint: str | None = None,
    calendar_status: str | None = None,
) -> dict:
    return {
        "source_id": source_id,
        "status": "OK",
        "started_at": when,
        "finished_at": when,
        "advanced": advanced,
        "publisher_release_dates": release_dates,
        "publisher_expected_release_dates": release_dates,
        "publisher_release_id": release_id,
        "publisher_content_fingerprint": fingerprint,
        "publisher_calendar_status": calendar_status,
    }


def test_fred_holiday_release_uses_exact_publisher_date_not_weekday_guess(tmp_path):
    archive = tmp_path / "archive"
    append_source_run(
        archive,
        _record(
            "dollar",
            "2026-05-27T06:45:00+08:00",
            advanced=True,
            release_dates=["2026-05-18", "2026-05-26"],
            release_id="FRED:17",
            fingerprint="calendar-and-content",
            calendar_status="VERIFIED",
        ),
    )

    result = source_reliability(archive, "dollar", today=date(2026, 5, 27))

    assert result["latest_expected_release_date"] == "2026-05-26"
    assert result["latest_expected_release_status"] == "ADVANCED"
    assert result["latest_expected_release_grace_status"] == "MATCHED"
    assert result["latest_publisher_release_id"] == "FRED:17"


def test_net_liquidity_preserves_mixed_daily_and_weekly_release_calendars():
    dates = pd.date_range("2026-06-01", periods=70, freq="D")

    def fetch_series(series_id, start="2015-01-01", end=None):
        base = {"WALCL": 8_000_000, "WTREGEN": 500_000, "RRPONTSYD": 1_000_000}[series_id]
        return pd.Series([base + idx for idx in range(len(dates))], index=dates)

    def fetch_calendar(release_ids, _config):
        assert release_ids == ("20", "379")
        return {
            "status": "VERIFIED",
            "release_dates_by_id": {
                "20": ["2026-07-02", "2026-07-09"],
                "379": ["2026-07-01", "2026-07-02", "2026-07-03"],
            },
        }

    raw = FredNetLiquidityAdapter(
        fetch_series=fetch_series,
        publisher_release_ids=("20", "379"),
        fetch_release_calendar=fetch_calendar,
    ).fetch_raw()

    evidence = raw["publisher_evidence"]
    assert evidence["calendar_status"] == "VERIFIED"
    assert evidence["release_id"] == "FRED:20,379"
    assert evidence["release_dates"] == [
        "2026-07-01",
        "2026-07-02",
        "2026-07-03",
        "2026-07-09",
    ]
    assert evidence["expected_release_dates"] == evidence["release_dates"]
    assert len(evidence["content_fingerprint"]) == 64


def test_unavailable_fred_calendar_is_advisory_and_does_not_block_promotion(tmp_path):
    def fetch_frame(*_args, **_kwargs):
        return pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-07-01"]),
                "publish_date": pd.to_datetime(["2026-07-02"]),
                "value": [1.0],
            }
        )

    run = run_external_source_refresh(
        ExternalSourceSpec(
            source_id="real_rate",
            target_path=tmp_path / "real_rate.csv",
            required_columns=(
                "date",
                "publish_date",
                "real_rate_10y",
                "real_rate_10y_pctl",
            ),
        ),
        FredPercentileAdapter(
            series_id="DFII10",
            field="real_rate_10y",
            min_periods=1,
            fetch_frame=fetch_frame,
            publisher_release_ids=("18",),
            fetch_release_calendar=lambda *_args: {
                "status": "UNAVAILABLE",
                "release_dates_by_id": {},
            },
        ),
        tmp_path / "archive",
    )

    assert run.status == "OK"
    assert run.publisher_calendar_status == "UNAVAILABLE"
    reliability = source_reliability(
        tmp_path / "archive",
        "real_rate",
        today=date(2026, 7, 3),
    )
    assert reliability["latest_expected_release_status"] == "UNINSTRUMENTED"


def test_unchanged_official_release_keeps_publisher_identity_without_fake_advance(tmp_path):
    class Adapter:
        def fetch_raw(self):
            return {
                "rows": [{"date": "2026-05-26", "value": 1.0}],
                "publisher_evidence": {
                    "calendar_status": "VERIFIED",
                    "release_id": "FRED:17",
                        "release_dates": ["2026-05-26"],
                        "expected_release_dates": ["2026-05-26"],
                    "content_fingerprint": "same-release",
                },
            }

        def parse(self, raw):
            return pd.DataFrame(raw["rows"])

    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=tmp_path / "dollar.csv",
        required_columns=("date", "value"),
    )
    archive = tmp_path / "archive"
    first = run_external_source_refresh(
        spec,
        Adapter(),
        archive,
        now=datetime(2026, 5, 27, tzinfo=timezone.utc),
    )
    second = run_external_source_refresh(
        spec,
        Adapter(),
        archive,
        now=datetime(2026, 5, 28, tzinfo=timezone.utc),
    )

    assert first.advanced is True
    assert second.advanced is False
    assert second.promotion_status == "UNCHANGED"
    assert second.publisher_release_id == "FRED:17"
    assert second.publisher_content_fingerprint == "same-release"
    assert second.publisher_calendar_status == "VERIFIED"
    assert second.publisher_expected_release_dates == ("2026-05-26",)


def _aaii_feed() -> str:
    issues = [
        ("2026-07-18", "Sat, 18 Jul 2026 15:30:26 GMT", "30.0", "30.0", "40.0"),
        ("2026-07-25", "Sat, 25 Jul 2026 15:30:26 GMT", "31.0", "29.0", "40.0"),
        ("2026-08-01", "Sat, 01 Aug 2026 15:30:26 GMT", "32.0", "28.0", "40.0"),
    ]
    items = "".join(
        f"""
        <item>
          <title>AAII Sentiment Survey: Issue {issue_date}</title>
          <link>https://insights.aaii.com/p/sentiment-{issue_date}</link>
          <guid>https://insights.aaii.com/p/sentiment-{issue_date}</guid>
          <pubDate>{published}</pubDate>
          <content:encoded><![CDATA[
            <p>This week's Sentiment Survey results:</p>
            <p>Bullish: {bull}% Neutral: {neutral}% Bearish: {bear}%</p>
            <p>Historical averages: Bullish: 37.5% Neutral: 31.5% Bearish: 31.0%</p>
          ]]></content:encoded>
        </item>
        """
        for issue_date, published, bull, neutral, bear in issues
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss xmlns:content="http://purl.org/rss/1.0/modules/content/" version="2.0">'
        f"<channel>{items}</channel></rss>"
    )


def test_delayed_aaii_issue_is_measured_from_issue_sequence_not_fetch_age(tmp_path):
    def fetch(url: str) -> str:
        if "insights.aaii.com" in url:
            return _aaii_feed()
        return "<title>Pardon Our Interruption</title>"

    raw = AaiiSentimentAdapter(
        seed_path=tmp_path / "aaii.csv",
        fetch_text=fetch,
        today=date(2026, 8, 12),
    ).fetch_raw()
    evidence = raw["publisher_evidence"]
    assert evidence["release_id"] == "https://insights.aaii.com/p/sentiment-2026-08-01"
    assert evidence["release_dates"][-1] == "2026-08-01"
    assert evidence["expected_release_dates"][-1] == "2026-08-08"

    archive = tmp_path / "archive"
    append_source_run(
        archive,
        _record(
            "aaii_sentiment",
            "2026-08-12T06:45:00+08:00",
            advanced=True,
            release_dates=evidence["expected_release_dates"],
            release_id=evidence["release_id"],
            fingerprint=evidence["content_fingerprint"],
            calendar_status=evidence["calendar_status"],
        ),
    )

    reliability = source_reliability(
        archive,
        "aaii_sentiment",
        today=date(2026, 8, 12),
    )
    assert reliability["latest_expected_release_date"] == "2026-08-08"
    assert reliability["latest_expected_release_status"] == "MISSED"
    assert reliability["latest_expected_release_grace_status"] == "EXPIRED"


def test_aaii_rss_fallback_records_publisher_recovery_evidence(tmp_path):
    seed = tmp_path / "aaii.csv"
    pd.DataFrame(
        [
            {
                "date": "2026-07-11",
                "publish_date": "2026-07-11",
                "aaii_bull": 0.30,
                "aaii_bear": 0.40,
                "aaii_bull_bear_spread": -0.10,
                "aaii_bull_pctl": 50.0,
                "aaii_spread_pctl": 50.0,
            }
        ]
    ).to_csv(seed, index=False)

    def fetch(url: str) -> str:
        if "insights.aaii.com" in url:
            return _aaii_feed()
        return "<title>Pardon Our Interruption</title>"

    run = run_external_source_refresh(
        ExternalSourceSpec(
            source_id="aaii_sentiment",
            target_path=seed,
            required_columns=(
                "date",
                "publish_date",
                "aaii_bull",
                "aaii_bear",
                "aaii_bull_bear_spread",
                "aaii_bull_pctl",
                "aaii_spread_pctl",
            ),
        ),
        AaiiSentimentAdapter(
            seed_path=seed,
            fetch_text=fetch,
            today=date(2026, 8, 12),
            min_periods=1,
        ),
        tmp_path / "archive",
        now=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )

    assert run.status == "OK"
    assert run.publisher_calendar_status == "VERIFIED"
    assert run.publisher_recovery_evidence == {
        "status": "RECOVERED_VIA_FALLBACK",
        "source_channel": "official_insights_rss",
        "primary_source": "public_html",
        "primary_failure": "blocked",
    }


def test_unverified_profile_weekday_does_not_create_expected_release_evidence(tmp_path):
    archive = tmp_path / "archive"
    append_source_run(
        archive,
        _record(
            "aaii_sentiment",
            "2026-07-10T06:45:00+08:00",
            advanced=True,
        ),
    )

    reliability = source_reliability(
        archive,
        "aaii_sentiment",
        today=date(2026, 7, 12),
    )

    assert reliability["latest_expected_release_status"] == "UNINSTRUMENTED"
    assert reliability["latest_expected_release_date"] is None


def test_expected_release_needs_five_matured_samples_for_sufficient_evidence(tmp_path):
    archive = tmp_path / "archive"
    release_dates = [
        "2026-06-01",
        "2026-06-08",
        "2026-06-15",
        "2026-06-22",
        "2026-06-29",
    ]
    for release_date in release_dates:
        operating_day = (pd.Timestamp(release_date) + pd.Timedelta(days=1)).date()
        append_source_run(
            archive,
            _record(
                "dollar",
                f"{operating_day.isoformat()}T06:45:00+08:00",
                advanced=True,
                release_dates=release_dates,
                release_id="FRED:17",
                fingerprint=f"content-{release_date}",
                calendar_status="VERIFIED",
            ),
        )

    four = source_reliability(archive, "dollar", today=date(2026, 6, 30))
    five = source_reliability(archive, "dollar", today=date(2026, 7, 2))

    assert four["expected_release_samples_90d"] == 4
    assert four["expected_release_evidence_status_90d"] == "INSUFFICIENT_EVIDENCE"
    assert five["expected_release_samples_90d"] == 5
    assert five["expected_release_evidence_status_90d"] == "SUFFICIENT"
    assert five["expected_release_evidence_status_30d"] == "INSUFFICIENT_EVIDENCE"
