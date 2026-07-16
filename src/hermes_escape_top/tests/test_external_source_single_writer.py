from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.macro import FredNetLiquiditySource
from hermes_escape_top.core.data.risk_signals import FredPercentileSource
from hermes_escape_top.core.data.sentiment import AaiiSource


ROOT = Path(__file__).resolve().parents[3]
LEGACY_WRITER_PATHS = (
    "src/hermes_escape_top/core/data/macro.py",
    "src/hermes_escape_top/core/data/sentiment.py",
    "src/hermes_escape_top/core/data/risk_signals.py",
    "src/hermes_escape_top/scripts/backfill_crypto_micro.py",
    "src/hermes_escape_top/scripts/backfill_naaim.py",
    "src/hermes_escape_top/scripts/refresh_cboe_daily_pcr.py",
    "src/hermes_escape_top/scripts/backfill_cot.py",
    "src/hermes_escape_top/scripts/backfill_occ_pcr.py",
    "src/hermes_escape_top/scripts/refresh_aaii_public.py",
    "src/hermes_escape_top/scripts/backfill_pcr_naaim.py",
    "src/hermes_escape_top/scripts/backfill_soft_data.py",
    "src/hermes_escape_top/scripts/backfill_cnn_fgi.py",
)


def _missing_config(tmp_path: Path) -> dict:
    config = deepcopy(load_config())
    config["paths"]["soft_history_dir"] = str(tmp_path / "soft_history")
    config["runtime"]["offline_replay_mode"] = False
    config["features"].update(
        {
            "data_aaii": True,
            "data_dollar": True,
            "data_net_liquidity": True,
            "use_fred_vintage_pit": False,
        }
    )
    return config


def test_scoring_readers_fail_closed_without_invoking_backfill(tmp_path, monkeypatch):
    config = _missing_config(tmp_path)
    called: list[str] = []

    aaii = AaiiSource()
    dollar = FredPercentileSource("dollar", "data_dollar", "DTWEXBGS", "dollar_broad")
    liquidity = FredNetLiquiditySource()
    monkeypatch.setattr(aaii, "backfill", lambda *args, **kwargs: called.append("aaii"))
    monkeypatch.setattr(dollar, "backfill", lambda *args, **kwargs: called.append("dollar"))
    monkeypatch.setattr(liquidity, "backfill", lambda *args, **kwargs: called.append("liquidity"))

    records = [
        aaii.collect("2026-07-15", config),
        dollar.collect("2026-07-15", config),
        liquidity.collect("2026-07-15", config),
    ]

    assert called == []
    assert all(not record.data_available for record in records)
    assert not (tmp_path / "soft_history").exists()


def test_external_canonical_promotion_has_no_legacy_csv_writer():
    forbidden_calls = {"to_csv", "atomic_write_csv"}
    offenders: list[str] = []
    for relative in LEGACY_WRITER_PATHS:
        path = ROOT / relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = function.attr if isinstance(function, ast.Attribute) else (
                function.id if isinstance(function, ast.Name) else ""
            )
            if name in forbidden_calls:
                offenders.append(f"{relative}:{getattr(node, 'lineno', 0)}:{name}")

    assert offenders == []


def test_runner_remains_the_canonical_promotion_module():
    runner = (
        ROOT / "src/hermes_escape_top/core/data/external_sources/runner.py"
    ).read_text(encoding="utf-8")

    assert "atomic_write_csv(frame, spec.target_path" in runner
