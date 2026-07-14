from __future__ import annotations

import json
import subprocess
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from hermes_escape_top.core.data.external_sources.aaii import (
    AAII_INSIGHTS_FEED_URL,
    AaiiSentimentAdapter,
    AaiiSentimentImportAdapter,
    parse_aaii_insights_feed,
    parse_aaii_public_rows,
    aaii_sentiment_spec,
    _read_aaii_import_table,
)
from hermes_escape_top.core.data.external_sources.ledger import latest_source_run
from hermes_escape_top.core.data.external_sources.profiles import latest_import_file, profile_for
from hermes_escape_top.core.data.external_sources.runner import run_external_source_refresh


def _seed_aaii(path, *, end: str = "2026-06-18", rows: int = 60) -> None:
    end_day = date.fromisoformat(end)
    start_day = end_day - timedelta(days=7 * (rows - 1))
    records = []
    for idx in range(rows):
        day = start_day + timedelta(days=7 * idx)
        bull = 0.30 + (idx % 10) / 100.0
        bear = 0.40 - (idx % 8) / 100.0
        records.append(
            {
                "date": day.isoformat(),
                "publish_date": day.isoformat(),
                "aaii_bull": round(bull, 3),
                "aaii_bear": round(bear, 3),
                "aaii_bull_bear_spread": round(bull - bear, 3),
                "aaii_bull_pctl": 50.0,
                "aaii_spread_pctl": 50.0,
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(records).to_csv(path, index=False)


def test_parse_aaii_public_rows_supports_plain_rendered_table():
    html = """
    Reported Date Bullish Neutral Bearish
    Jun 24 44.9% 25.0% 30.1%
    Jun 17 36.6% 24.0% 39.4%
    Jan 1 42.0% 31.0% 27.0%
    Dec 25 37.4% 27.8% 34.8%
    """

    rows = parse_aaii_public_rows(html, today=date(2026, 7, 2))

    assert rows[0] == {"reported": date(2026, 6, 24), "bull": 0.449, "neutral": 0.25, "bear": 0.301}
    assert rows[1]["reported"] == date(2026, 6, 17)
    assert rows[-1]["reported"] == date(2025, 12, 25)


def _aaii_insights_feed() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
    <rss xmlns:content="http://purl.org/rss/1.0/modules/content/" version="2.0">
      <channel>
        <item>
          <title>AAII Sentiment Survey: Pessimism Drops</title>
          <link>https://insights.aaii.com/p/aaii-sentiment-survey-pessimism-drops</link>
          <pubDate>Sat, 11 Jul 2026 15:30:22 GMT</pubDate>
          <content:encoded><![CDATA[
            <p>This week’s Sentiment Survey results:</p>
            <p>Bullish: 36.3%, up 4.9 points<br>Neutral: 26.5%, up 0.1 points<br>Bearish: 37.2%, down 5.1 points</p>
            <p>Historical averages: Bullish: 37.5% Neutral: 31.5% Bearish: 31.0%</p>
          ]]></content:encoded>
        </item>
        <item>
          <title>Unrelated AAII article</title>
          <pubDate>Mon, 13 Jul 2026 15:30:34 GMT</pubDate>
          <content:encoded><![CDATA[<p>Bullish: 99% Neutral: 0% Bearish: 1%</p>]]></content:encoded>
        </item>
      </channel>
    </rss>"""


def test_parse_aaii_insights_feed_uses_official_weekly_issue_date():
    rows = parse_aaii_insights_feed(_aaii_insights_feed())

    assert rows == [
        {
            "reported": date(2026, 7, 8),
            "publish_date": date(2026, 7, 11),
            "bull": 0.363,
            "neutral": 0.265,
            "bear": 0.372,
        }
    ]


def test_aaii_adapter_merges_public_rows_with_seed_history(tmp_path):
    seed_path = tmp_path / "soft_history" / "aaii_sentiment.csv"
    _seed_aaii(seed_path, end="2026-06-18", rows=80)
    html = """
    <td align="left" class="tableTxt">Jun 24</td>
    <td align="right" class="tableTxt">44.9% </td>
    <td align="right" class="tableTxt">25.0%</td>
    <td align="right" class="tableTxt">30.1% </td>
    <td align="left" class="tableTxt">Jun 17</td>
    <td align="right" class="tableTxt">36.6% </td>
    <td align="right" class="tableTxt">24.0%</td>
    <td align="right" class="tableTxt">39.4% </td>
    """
    adapter = AaiiSentimentAdapter(
        seed_path=seed_path,
        fetch_text=lambda _url: html,
        today=date(2026, 7, 2),
        percentile_window=10,
        min_periods=1,
    )
    spec = aaii_sentiment_spec(target_path=seed_path, min_rows=60)

    run = run_external_source_refresh(spec, adapter, tmp_path / "archive")

    out = pd.read_csv(seed_path)
    latest = out.iloc[-1]
    assert run.status == "OK"
    assert run.latest_promoted_as_of == "2026-06-25"
    assert latest["date"] == "2026-06-25"
    assert latest["publish_date"] == "2026-06-25"
    assert latest["aaii_bull"] == 0.449
    assert latest["aaii_bear"] == 0.301
    assert round(float(latest["aaii_bull_bear_spread"]), 3) == 0.148
    ledger = latest_source_run(tmp_path / "archive", "aaii_sentiment")
    assert ledger["status"] == "OK"
    assert ledger["official_file_name"] == "sent_results.html"
    assert ledger["official_file_sha256"]
    assert ledger["official_issue_as_of"] == "2026-06-25"
    assert ledger["pit_rule"] == "official_publish_date_or_reported_plus_one_day"
    assert ledger["source_url"] == "https://www.aaii.com/sentimentsurvey/sent_results"


@pytest.mark.parametrize(
    ("column", "value", "error_fragment"),
    [
        ("aaii_bull", 1.1, "share"),
        ("aaii_bear", -0.1, "share"),
        ("aaii_bull_bear_spread", 0.9, "spread"),
        ("aaii_bull_pctl", 101.0, "percentile"),
        ("publish_date", "2026-06-19", "date/publish"),
    ],
)
def test_aaii_semantic_validator_checks_every_normalized_row(
    tmp_path,
    column,
    value,
    error_fragment,
):
    seed_path = tmp_path / "aaii.csv"
    _seed_aaii(seed_path, rows=60)
    frame = pd.read_csv(seed_path)
    frame.loc[0, column] = value
    validator = aaii_sentiment_spec(target_path=seed_path, min_rows=1).semantic_validator

    assert validator is not None
    assert error_fragment in str(validator(frame)).lower()


def test_aaii_corrupt_seed_is_not_recertified_by_valid_public_row(tmp_path):
    seed_path = tmp_path / "soft_history" / "aaii_sentiment.csv"
    _seed_aaii(seed_path, end="2026-06-18", rows=80)
    frame = pd.read_csv(seed_path)
    frame.loc[0, "aaii_bull_bear_spread"] = 0.9
    frame.to_csv(seed_path, index=False)
    before = seed_path.read_bytes()
    html = "Jun 24 44.9% 25.0% 30.1%"
    adapter = AaiiSentimentAdapter(
        seed_path=seed_path,
        fetch_text=lambda _url: html,
        today=date(2026, 7, 2),
        percentile_window=10,
        min_periods=1,
    )

    run = run_external_source_refresh(
        aaii_sentiment_spec(target_path=seed_path, min_rows=60),
        adapter,
        tmp_path / "archive",
    )

    assert run.status == "VALIDATION_ERROR"
    assert "spread" in str(run.error_message).lower()
    assert seed_path.read_bytes() == before


def test_aaii_adapter_records_fetch_error_on_challenge_page(tmp_path):
    seed_path = tmp_path / "soft_history" / "aaii_sentiment.csv"
    _seed_aaii(seed_path, end="2026-06-18", rows=80)
    before = seed_path.read_bytes()
    adapter = AaiiSentimentAdapter(
        seed_path=seed_path,
        fetch_text=lambda _url: "<title>Pardon Our Interruption</title>",
        today=date(2026, 7, 2),
    )

    run = run_external_source_refresh(
        aaii_sentiment_spec(target_path=seed_path, min_rows=60),
        adapter,
        tmp_path / "archive",
    )

    assert run.status == "FETCH_ERROR"
    assert run.error_type == "ValueError"
    assert "blocked" in str(run.error_message).lower()
    assert seed_path.read_bytes() == before


def test_aaii_adapter_falls_back_to_official_insights_rss(tmp_path):
    seed_path = tmp_path / "soft_history" / "aaii_sentiment.csv"
    _seed_aaii(seed_path, end="2026-07-02", rows=80)

    def fetch(url: str) -> str:
        if url == AAII_INSIGHTS_FEED_URL:
            return _aaii_insights_feed()
        return "<title>Pardon Our Interruption</title>"

    adapter = AaiiSentimentAdapter(
        seed_path=seed_path,
        fetch_text=fetch,
        today=date(2026, 7, 14),
        percentile_window=10,
        min_periods=1,
    )

    run = run_external_source_refresh(
        aaii_sentiment_spec(target_path=seed_path, min_rows=60),
        adapter,
        tmp_path / "archive",
    )

    out = pd.read_csv(seed_path)
    raw = json.loads((tmp_path / "archive" / "external_sources" / "aaii_sentiment" / run.run_id / "raw.json").read_text())
    assert run.status == "OK"
    assert run.latest_promoted_as_of == "2026-07-11"
    assert out.iloc[-1]["date"] == "2026-07-11"
    assert out.iloc[-1]["publish_date"] == "2026-07-11"
    assert out.iloc[-1]["aaii_bull"] == 0.363
    assert out.iloc[-1]["aaii_bear"] == 0.372
    assert raw["source"] == "official_insights_rss"
    assert raw["primary_failure"] == "blocked"
    assert run.official_file_name == "aaii_insights_feed.xml"
    assert run.source_url == AAII_INSIGHTS_FEED_URL


def test_aaii_invalid_public_rows_fall_back_to_official_insights_rss(tmp_path):
    seed_path = tmp_path / "soft_history" / "aaii_sentiment.csv"
    _seed_aaii(seed_path, end="2026-07-02", rows=80)

    def fetch(url: str) -> str:
        if url == AAII_INSIGHTS_FEED_URL:
            return _aaii_insights_feed()
        return "Jul 8 90.0% 90.0% 90.0%"

    run = run_external_source_refresh(
        aaii_sentiment_spec(target_path=seed_path, min_rows=60),
        AaiiSentimentAdapter(
            seed_path=seed_path,
            fetch_text=fetch,
            today=date(2026, 7, 14),
            percentile_window=10,
            min_periods=1,
        ),
        tmp_path / "archive",
    )

    raw = json.loads(Path(run.raw_path).read_text(encoding="utf-8"))
    assert run.status == "OK"
    assert run.latest_promoted_as_of == "2026-07-11"
    assert raw["source"] == "official_insights_rss"
    assert raw["primary_failure"] == "invalid_rows"


def test_aaii_import_adapter_promotes_official_file_through_ledger(tmp_path):
    seed_path = tmp_path / "soft_history" / "aaii_sentiment.csv"
    _seed_aaii(seed_path, end="2026-06-18", rows=80)
    import_path = tmp_path / "sentiment.csv"
    import_path.write_text(
        "\n".join(
            [
                "Reported,Bullish,Neutral,Bearish,Bull-Bear",
                "2026-06-25,44.9,25.0,30.1,14.8",
                "2026-07-02,38.2,28.0,33.8,4.4",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    adapter = AaiiSentimentImportAdapter(
        seed_path=seed_path,
        import_path=import_path,
        percentile_window=10,
        min_periods=1,
    )

    run = run_external_source_refresh(
        aaii_sentiment_spec(target_path=seed_path, min_rows=60),
        adapter,
        tmp_path / "archive",
    )

    out = pd.read_csv(seed_path)
    latest = out.iloc[-1]
    ledger = latest_source_run(tmp_path / "archive", "aaii_sentiment")
    assert run.status == "OK"
    assert run.latest_promoted_as_of == "2026-07-02"
    assert latest["date"] == "2026-07-02"
    assert latest["publish_date"] == "2026-07-02"
    assert latest["aaii_bull"] == 0.382
    assert latest["aaii_bear"] == 0.338
    assert round(float(latest["aaii_bull_bear_spread"]), 3) == 0.044
    assert ledger["status"] == "OK"
    raw = json.loads((tmp_path / "archive" / "external_sources" / "aaii_sentiment" / run.run_id / "raw.json").read_text())
    assert raw["file_name"] == "sentiment.csv"
    assert raw["source"] == "manual_official_file"
    assert ledger["official_file_name"] == "sentiment.csv"
    assert ledger["official_file_sha256"] == raw["content_sha256"]
    assert ledger["official_issue_as_of"] == "2026-07-02"


def test_aaii_import_adapter_rejects_import_older_than_seed(tmp_path):
    seed_path = tmp_path / "soft_history" / "aaii_sentiment.csv"
    _seed_aaii(seed_path, end="2026-07-02", rows=80)
    import_path = tmp_path / "sentiment.csv"
    import_path.write_text(
        "\n".join(
            [
                "Reported,Bullish,Neutral,Bearish,Bull-Bear",
                "2026-06-25,44.9,25.0,30.1,14.8",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    adapter = AaiiSentimentImportAdapter(
        seed_path=seed_path,
        import_path=import_path,
        percentile_window=10,
        min_periods=1,
    )

    run = run_external_source_refresh(
        aaii_sentiment_spec(target_path=seed_path, min_rows=60),
        adapter,
        tmp_path / "archive",
    )

    out = pd.read_csv(seed_path)
    ledger = latest_source_run(tmp_path / "archive", "aaii_sentiment")
    assert run.status == "PARSE_ERROR"
    assert "older than current AAII seed" in str(run.error_message)
    assert out.iloc[-1]["date"] == "2026-07-02"
    assert ledger["status"] == "PARSE_ERROR"
    assert ledger["official_file_name"] == "sentiment.csv"
    assert ledger["official_file_sha256"]
    assert ledger["official_issue_as_of"] is None


def test_aaii_xls_import_uses_helper_when_excel_engine_missing(monkeypatch):
    def missing_engine(*_args, **_kwargs):
        raise ImportError("Missing optional dependency 'xlrd'")

    calls = []

    def fake_run(command, check, capture_output, text, timeout):
        calls.append((command, check, capture_output, text, timeout))
        return SimpleNamespace(
            stdout="Reported,Bullish,Neutral,Bearish,Bull-Bear\n2026-07-02,38.2,28.0,33.8,4.4\n",
            stderr="",
        )

    monkeypatch.setenv("HERMES_AAII_XLS_HELPER_PYTHON", "/usr/bin/helper-python")
    monkeypatch.setattr(pd, "read_excel", missing_engine)
    monkeypatch.setattr(subprocess, "run", fake_run)

    frame = _read_aaii_import_table(b"fake xls bytes", "sentiment.xls")

    assert calls
    assert calls[0][0][:2] == ["/usr/bin/helper-python", "-c"]
    assert calls[0][0][2].startswith("import pandas as pd, sys")
    assert list(frame.columns) == ["Reported", "Bullish", "Neutral", "Bearish", "Bull-Bear"]
    assert frame.iloc[0]["Reported"] == "2026-07-02"


def test_aaii_latest_import_file_checks_hermes_external_imports(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    import_dir = tmp_path / ".hermes" / "external_imports"
    import_dir.mkdir(parents=True)
    official = import_dir / "sentiment.xls"
    official.write_text("official", encoding="utf-8")

    assert latest_import_file(profile_for("aaii_sentiment")) == official
