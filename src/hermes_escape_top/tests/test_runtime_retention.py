from __future__ import annotations

import importlib.util
import fcntl
import json
import os
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[3] / "ops" / "prune_runtime_artifacts.py"


def _module():
    spec = importlib.util.spec_from_file_location("prune_runtime_artifacts", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _dir(path: Path, size: int, mtime: int) -> Path:
    path.mkdir(parents=True)
    (path / "payload.bin").write_bytes(b"x" * size)
    os.utime(path, (mtime, mtime))
    return path


def _file(path: Path, size: int, mtime: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    os.utime(path, (mtime, mtime))
    return path


def test_dry_run_prunes_old_runtime_artifacts_and_protects_active_links(tmp_path: Path):
    module = _module()
    live = tmp_path / "live"
    releases = live / "releases"
    release_paths = [
        _dir(releases / f"{hash_}_2026070{i}_071000", 10, i)
        for i, hash_ in enumerate(("aaaaaaa", "bbbbbbb", "ccccccc", "ddddddd"), start=1)
    ]
    (live / "current").symlink_to(Path("releases") / release_paths[-1].name)
    (live / "previous").symlink_to(Path("releases") / release_paths[-2].name)
    _dir(releases / "operator-notes", 10, 0)

    backups = tmp_path / "backups"
    backup_paths = [
        _dir(backups / f"hermes_escape_top.predeploy_backup_2026070{i}_071000", 10, 10 + i)
        for i in range(1, 4)
    ]
    archive = live / "shared" / "hermes_escape_top" / "data" / "archive"
    audit_paths = [
        _file(archive / f"audit_log.archived_2026070{i}T071000.jsonl.gz", 10, 20 + i)
        for i in range(1, 4)
    ]
    runs = archive / ".score_run_transactions" / "runs"
    for i in range(1, 4):
        run = runs / f"run{i}"
        run.mkdir(parents=True)
        (run / "manifest.json").write_text(json.dumps({"run_id": f"run{i}", "status": "COMMITTED"}))
        os.utime(run, (30 + i, 30 + i))
    (archive / ".score_run_transactions" / "active.json").write_text(json.dumps({"run_id": "run1"}))

    plan = module.build_prune_plan(
        live_root=live,
        backup_root=backups,
        archive_dir=archive,
        keep_releases=2,
        keep_backups=1,
        keep_audit_archives=1,
        keep_transactions=1,
    )

    selected = {(row["kind"], Path(row["path"]).name) for row in plan["delete"]}
    assert ("release", release_paths[0].name) in selected
    assert ("release", release_paths[1].name) in selected
    assert ("backup", backup_paths[0].name) in selected
    assert ("backup", backup_paths[1].name) in selected
    assert ("audit_archive", audit_paths[0].name) in selected
    assert ("audit_archive", audit_paths[1].name) in selected
    assert ("score_transaction", "run2") in selected
    assert ("score_transaction", "run1") not in selected
    assert release_paths[-1].exists() and release_paths[-2].exists()
    assert (releases / "operator-notes").exists()
    assert all(path.exists() for path in release_paths + backup_paths + audit_paths)


def test_apply_deletes_only_validated_plan_entries(tmp_path: Path):
    module = _module()
    live = tmp_path / "live"
    releases = live / "releases"
    old = _dir(releases / "aaaaaaa_20260701_071000", 10, 1)
    current = _dir(releases / "bbbbbbb_20260702_071000", 10, 2)
    (live / "current").symlink_to(Path("releases") / current.name)
    backups = tmp_path / "backups"
    archive = live / "shared" / "hermes_escape_top" / "data" / "archive"

    plan = module.build_prune_plan(
        live_root=live,
        backup_root=backups,
        archive_dir=archive,
        keep_releases=1,
        keep_backups=0,
        keep_audit_archives=0,
        keep_transactions=0,
    )
    result = module.apply_prune_plan(plan)

    assert result["deleted_count"] == 1
    assert not old.exists()
    assert current.exists()


def test_capacity_limit_can_prune_beyond_count_limit(tmp_path: Path):
    module = _module()
    live = tmp_path / "live"
    releases = live / "releases"
    paths = [
        _dir(releases / f"{hash_}_2026070{i}_071000", 100, i)
        for i, hash_ in enumerate(("aaaaaaa", "bbbbbbb", "ccccccc"), start=1)
    ]
    archive = live / "shared" / "hermes_escape_top" / "data" / "archive"

    plan = module.build_prune_plan(
        live_root=live,
        backup_root=tmp_path / "backups",
        archive_dir=archive,
        keep_releases=3,
        keep_backups=0,
        keep_audit_archives=0,
        keep_transactions=0,
        max_release_bytes=150,
    )

    selected = {Path(row["path"]).name for row in plan["delete"] if row["kind"] == "release"}
    assert selected == {paths[0].name, paths[1].name}
    assert all(row["reason"] == "capacity" for row in plan["delete"] if row["kind"] == "release")


def test_apply_mode_writes_dated_and_latest_retention_evidence(tmp_path: Path):
    module = _module()
    live = tmp_path / "live"
    releases = live / "releases"
    old = _dir(releases / "aaaaaaa_20260701_071000", 10, 1)
    current = _dir(releases / "bbbbbbb_20260702_071000", 10, 2)
    (live / "current").symlink_to(Path("releases") / current.name)
    archive = live / "shared" / "hermes_escape_top" / "data" / "archive"
    archive.mkdir(parents=True)
    reports = tmp_path / "retention-reports"

    rc = module.main(
        [
            "--live-root",
            str(live),
            "--backup-root",
            str(tmp_path / "backups"),
            "--archive-dir",
            str(archive),
            "--keep-releases",
            "1",
            "--keep-backups",
            "0",
            "--keep-audit-archives",
            "0",
            "--keep-transactions",
            "0",
            "--apply",
            "--report-dir",
            str(reports),
        ]
    )

    assert rc == 0
    assert not old.exists()
    assert current.exists()
    latest = json.loads((reports / "runtime_retention_latest.json").read_text(encoding="utf-8"))
    dated = list(reports.glob("runtime_retention_????-??-??.json"))
    assert len(dated) == 1
    assert json.loads(dated[0].read_text(encoding="utf-8")) == latest
    assert latest["schema_version"] == "hermes-runtime-retention-v1"
    assert latest["status"] == "PASS"
    assert latest["plan"]["mode"] == "DRY_RUN"
    assert latest["result"]["mode"] == "APPLIED"
    assert latest["result"]["deleted_count"] == 1
    assert latest["lock_path"] == str(archive / ".pipeline.lock")


def test_apply_mode_records_busy_and_deletes_nothing_when_pipeline_locked(tmp_path: Path):
    module = _module()
    live = tmp_path / "live"
    releases = live / "releases"
    old = _dir(releases / "aaaaaaa_20260701_071000", 10, 1)
    current = _dir(releases / "bbbbbbb_20260702_071000", 10, 2)
    (live / "current").symlink_to(Path("releases") / current.name)
    archive = live / "shared" / "hermes_escape_top" / "data" / "archive"
    archive.mkdir(parents=True)
    lock_path = archive / ".pipeline.lock"
    lock_path.touch()
    reports = tmp_path / "retention-reports"

    with lock_path.open("r+") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        rc = module.main(
            [
                "--live-root",
                str(live),
                "--backup-root",
                str(tmp_path / "backups"),
                "--archive-dir",
                str(archive),
                "--keep-releases",
                "1",
                "--apply",
                "--report-dir",
                str(reports),
            ]
        )

    latest = json.loads((reports / "runtime_retention_latest.json").read_text(encoding="utf-8"))
    assert rc == 2
    assert old.exists() and current.exists()
    assert latest["status"] == "BUSY"
    assert latest["result"]["deleted_count"] == 0
    assert "pipeline busy" in latest["result"]["skipped"][0]["reason"]
