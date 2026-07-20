from __future__ import annotations

import inspect

from hermes_escape_top.ibkr import executions, live_check, positions
from hermes_escape_top.scripts import run_daily_package
from hermes_escape_top.web import mirror_render, render, server


def test_retired_m4_server_is_tombstone_only() -> None:
    source = inspect.getsource(server)
    for retired_helper in (
        "_read_run_daily_mode",
        "_shadow_status",
        "_run_shadow",
        "_run_history_refresh",
        "_run_baseline",
        "_backfill_compare",
        "_diff_shadow",
        "_flip_to_package",
    ):
        assert f"def {retired_helper}(" not in source
    assert '"/api/shadow_status"' not in source
    assert {
        "/api/m4_shadow",
        "/api/m4_backfill",
        "/api/m4_golive",
    }.issubset(server.RETIRED_WRITE_ENDPOINTS)


def test_auxiliary_artifact_writers_use_shared_atomic_text_writer() -> None:
    writers = (
        render.write_dashboard,
        mirror_render.write_mirror_dashboard,
        live_check._write_reports,
        positions._save_snapshot,
        executions._save_cache,
        run_daily_package.commit_state,
        run_daily_package.write_artifacts,
        run_daily_package._post_run_diff,
    )
    for writer in writers:
        source = inspect.getsource(writer)
        assert "atomic_write_text" in source, writer.__qualname__
        assert ".write_text(" not in source, writer.__qualname__
