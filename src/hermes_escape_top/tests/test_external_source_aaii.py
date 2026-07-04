from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd

from hermes_escape_top.core.data.external_sources.aaii import (
    AaiiSentimentAdapter,
    AaiiSentimentImportAdapter,
    parse_aaii_public_rows,
    aaii_sentiment_spec,
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


def test_aaii_adapter_records_fetch_error_on_challenge_page(tmp_path):
    seed_path = tmp_path / "soft_history" / "aaii_sentiment.csv"
    _seed_aaii(seed_path, end="2026-06-18", rows=80)
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


def test_aaii_latest_import_file_checks_hermes_external_imports(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    import_dir = tmp_path / ".hermes" / "external_imports"
    import_dir.mkdir(parents=True)
    official = import_dir / "sentiment.xls"
    official.write_text("official", encoding="utf-8")

    assert latest_import_file(profile_for("aaii_sentiment")) == official
