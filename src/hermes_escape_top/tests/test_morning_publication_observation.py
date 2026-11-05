"""Morning integration remains an observation, never a main acceptance gate."""
from __future__ import annotations

import json
from datetime import datetime, time
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys

import pytest

from hermes_escape_top.core.safe_io import pipeline_lock
from hermes_escape_top.scripts import run_daily_package as rdp
from test_a2_production_capture import capture_root as capture_root
from test_broker_input_capture import broker_run as broker_run
from test_broker_publication_status import publication_run as publication_run
from test_commit_observation_receipt import receipt_run as receipt_run
from test_morning_acceptance import REPO_ROOT, _acceptance_fixture, _load_module, _switch_to_new_release
from test_scheduled_broker_publication import selected_run as selected_run


def _morning(tmp_path: Path, *, install: bool = True):
    home, now, dashboard = _acceptance_fixture(tmp_path)
    base = home / '.hermes/skills/investment/escape-top'
    package = base / 'current/hermes_escape_top'
    archive = package / 'data/archive'
    audit_path = archive / 'audit_log.jsonl'
    row = json.loads(audit_path.read_text())
    row['payload']['persistence']['run_id'] = 'a' * 32
    row['input_hash'] = row['payload']['input_hash'] = 'b' * 64
    audit_path.write_text(json.dumps(row) + '\n')
    health_path = base / 'reports/system_health_2026-07-10.json'
    health = json.loads(health_path.read_text())
    health['input_hash'] = 'b' * 64
    health_path.write_text(json.dumps(health))
    journal = archive / '.score_run_transactions/runs'
    (journal / 'run-1').rename(journal / ('a' * 32))
    record = json.loads((journal / ('a' * 32) / 'manifest.json').read_text())
    record['run_id'] = 'a' * 32
    (journal / ('a' * 32) / 'manifest.json').write_text(json.dumps(record))
    if install:
        for name in ('core/data/transaction_evidence.py', 'core/reporting/broker_publication_status.py',
                     'core/reporting/scheduled_broker_publication.py'):
            target = package / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / 'src/hermes_escape_top' / name, target)
    return home, now, dashboard, package, archive


def test_v1_is_visible_as_not_applicable_without_an_eighth_check(tmp_path):
    home, now, dashboard, _package, _archive = _morning(tmp_path)
    report = _load_module().collect_acceptance(home=home, now=now, dashboard_reader=lambda _: (200, dashboard))
    observation = report['operational_observations']['broker_cache_publication']
    assert observation['status'] == 'INFO'
    assert observation['publication_status'] == 'NOT_APPLICABLE'
    assert observation['official_receipt_status'] == 'OK'
    assert len(report['checks']) == 7
    assert report['status'] == 'PASS'


@pytest.mark.parametrize('damage', ['missing', 'symlink', 'parent_symlink', 'directory', 'release_symlink'])
def test_reader_is_never_loaded_through_missing_or_redirected_source(tmp_path, damage):
    home, now, dashboard, package, _archive = _morning(tmp_path)
    source = package / 'core/reporting/scheduled_broker_publication.py'
    if damage == 'release_symlink':
        physical = package.resolve()
        outside = tmp_path / 'other-package'
        physical.rename(outside)
        physical.symlink_to(outside, target_is_directory=True)
    elif damage == 'parent_symlink':
        outside = tmp_path / 'other-reporting'
        source.parent.rename(outside)
        source.parent.symlink_to(outside, target_is_directory=True)
    else:
        data = source.read_bytes()
        source.unlink()
        if damage == 'symlink':
            outside = tmp_path / 'other-reader.py'
            outside.write_bytes(data)
            source.symlink_to(outside)
        elif damage == 'directory':
            source.mkdir()
    before_modules = set(sys.modules)
    report = _load_module().collect_acceptance(home=home, now=now, dashboard_reader=lambda _: (200, dashboard))
    observation = report['operational_observations']['broker_cache_publication']
    assert observation['status'] == 'UNKNOWN'
    assert observation['reason'] == 'READER_UNAVAILABLE'
    assert 'broker publication: UNKNOWN' in report['summary']
    assert not any(n.startswith('_hermes_morning_reader_') for n in set(sys.modules) - before_modules)


@pytest.mark.parametrize('change', ['receipt', 'audit', 'release'])
def test_changes_during_collection_never_mix_official_evidence(tmp_path, change):
    home, now, dashboard, _package, archive = _morning(tmp_path)

    def dashboard_reader(_url):
        if change == 'release':
            _switch_to_new_release(home)
        else:
            path = archive / ('run_receipt.json' if change == 'receipt' else 'audit_log.jsonl')
            path.write_bytes(path.read_bytes() + b'\n')
        return 200, dashboard

    report = _load_module().collect_acceptance(home=home, now=now, dashboard_reader=dashboard_reader)
    row = report['operational_observations']['broker_cache_publication']
    assert row['status'] == 'UNKNOWN'
    assert row['reason'] == 'EVIDENCE_CHANGED'


def _stub_reader(package, status, *, official='OK'):
    """State-combination control, not proof of real producer validation."""
    payload = {'status': status, 'publication_status': 'SYNTHETIC', 'reason': 'STATUS_CONTROL',
               'official_receipt_status': official, 'anchor_source': 'LOCAL_PRODUCER_RECEIPT',
               'scope': 'OPERATIONS', 'strategy_blocking': False, 'cache_contents_verified': False}
    (package / 'core/reporting/scheduled_broker_publication.py').write_text(
        'def read_scheduled_broker_publication(**kwargs):\n    return ' + repr(payload) + '\n'
    )


@pytest.mark.parametrize('main_status', ['PASS', 'FAIL', 'PENDING_POST_DEPLOY'])
@pytest.mark.parametrize('auxiliary', ['OK', 'WARN', 'INFO', 'UNKNOWN'])
def test_auxiliary_never_changes_main_checks_readiness_or_certification(tmp_path, main_status, auxiliary):
    home, now, dashboard, package, archive = _morning(tmp_path)
    official = 'OK'
    if main_status == 'FAIL':
        path = archive / 'run_receipt.json'
        receipt = json.loads(path.read_text())
        receipt.update(status='FAILED', ok=False)
        path.write_text(json.dumps(receipt))
        official = 'FAILED'
    elif main_status == 'PENDING_POST_DEPLOY':
        release, _ = _switch_to_new_release(home)
        new_package = release / 'hermes_escape_top'
        shutil.copytree(package.resolve().parent.parent / 'd9ec486_20260712_184620/hermes_escape_top/core',
                        new_package / 'core')
        package = new_package
        dashboard['level'] = 'OK'
        dashboard['layers']['strategy_data'] = {'level': 'OK', 'checks': []}
    module = _load_module()
    _stub_reader(package, 'INFO', official=official)
    baseline = module.collect_acceptance(home=home, now=now, dashboard_reader=lambda _: (200, dashboard))
    _stub_reader(package, auxiliary, official=official)
    actual = module.collect_acceptance(home=home, now=now, dashboard_reader=lambda _: (200, dashboard))
    for key in ('status', 'checks', 'readiness', 'post_deploy_certification'):
        assert actual[key] == baseline[key]
    assert actual['status'] == main_status
    row = actual['operational_observations']['broker_cache_publication']
    assert row['status'] == auxiliary
    assert row['official_receipt_status'] == official
    if auxiliary in {'WARN', 'UNKNOWN'}:
        assert f'broker publication: {auxiliary}' in actual['summary']
    paths = module.write_reports(actual, tmp_path / 'output')
    assert json.loads(paths['dated_json'].read_text()) == actual
    text = paths['dated_markdown'].read_text()
    assert f'official_receipt_status={official}' in text
    assert 'anchor_source=LOCAL_PRODUCER_RECEIPT' in text
    assert f'| broker_cache_publication | {auxiliary} |' in text


def test_system_python_without_site_packages_uses_only_pinned_readers(tmp_path):
    home, now, dashboard, package, _archive = _morning(tmp_path)
    for relative in ('__init__.py', 'core/__init__.py', 'core/data/__init__.py', 'core/reporting/__init__.py'):
        (package / relative).write_text('raise AssertionError("project init executed")\n')
    code = '''
import importlib.util, json, sys
from datetime import datetime
from pathlib import Path
spec = importlib.util.spec_from_file_location('acceptance', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
before = list(sys.path)
report = module.collect_acceptance(home=Path(sys.argv[2]), now=datetime.fromisoformat(sys.argv[3]),
    dashboard_reader=lambda _: (200, json.loads(sys.argv[4])))
assert sys.path == before
assert not any(n.startswith('_hermes_morning_reader_') for n in sys.modules)
assert not any(n in sys.modules for n in ('hermes_escape_top', 'pandas', 'numpy', 'ib_insync'))
print(json.dumps(report['operational_observations']['broker_cache_publication']))
'''
    result = subprocess.run(['/usr/bin/python3', '-I', '-S', '-B', '-c', code,
                             str(REPO_ROOT / 'ops/morning_acceptance.py'), str(home), now.isoformat(),
                             json.dumps(dashboard)], text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)['reason'] == 'CAPTURE_DISABLED'


@pytest.mark.parametrize('damage', ['missing_anchor', 'bad_schema', 'deep_json', 'missing_receipt'])
def test_real_reader_retains_unknown_evidence_states(tmp_path, damage):
    home, now, dashboard, _package, archive = _morning(tmp_path)
    if damage == 'missing_anchor':
        path = archive / 'audit_log.jsonl'
        value = json.loads(path.read_text())
        value['payload']['persistence'].update(protocol='recoverable-journal-v2', capture_id='c' * 32)
        path.write_text(json.dumps(value))
    elif damage == 'bad_schema':
        path = archive / 'audit_log.jsonl'
        value = json.loads(path.read_text())
        value['schema_version'] = 'future-audit-v999'
        path.write_text(json.dumps(value))
    elif damage == 'deep_json':
        path = archive / 'run_receipt.json'
        path.write_text('{"deep":' + '[' * 2000 + '0' + ']' * 2000 + '}')
    else:
        (archive / 'run_receipt.json').unlink()
    report = _load_module().collect_acceptance(home=home, now=now, dashboard_reader=lambda _: (200, dashboard))
    row = report['operational_observations']['broker_cache_publication']
    assert row['status'] == 'UNKNOWN'
    if damage == 'missing_anchor':
        assert row['reason'] == 'ANCHOR_UNAVAILABLE'


def _attach_run(package, archive, day, now):
    (package / 'data').unlink()
    (package / 'data').symlink_to(archive.parent, target_is_directory=True)
    return datetime.combine(day, time(9, 10), tzinfo=now.tzinfo)


@pytest.mark.parametrize('case', ['published', 'failed', 'missing', 'official_failed', 'changed_journal'])
def test_actual_v2_declarations_keep_main_and_auxiliary_outcomes_separate(tmp_path, selected_run, case):
    run, receipt, _audit, day, write = selected_run(sources=('tws', 'tws'),
                                                  fail=('positions',) if case == 'failed' else ())
    archive = run.arguments['archive_dir']
    if case == 'missing':
        run.receipt.unlink()
    elif case == 'official_failed':
        receipt.update(status='FAILED', ok=False)
        write()
    elif case == 'changed_journal':
        run.journal.write_bytes(run.journal.read_bytes() + b'\n')
    home, now, dashboard, package, _ = _morning(tmp_path / 'morning')
    now = _attach_run(package, archive, day, now)
    report = _load_module().collect_acceptance(home=home, now=now, dashboard_reader=lambda _: (200, dashboard))
    row = report['operational_observations']['broker_cache_publication']
    assert row['status'] == {'published': 'OK', 'failed': 'WARN', 'missing': 'UNKNOWN',
                             'official_failed': 'OK', 'changed_journal': 'UNKNOWN'}[case]
    if case == 'official_failed':
        assert row['official_receipt_status'] == 'FAILED'
        assert report['status'] == 'FAIL'
        assert next(r for r in report['checks'] if r['id'] == 'scheduled_receipt')['status'] == 'FAIL'


def test_real_producer_receipt_flows_through_morning_without_writers(tmp_path, receipt_run, broker_run, monkeypatch):
    with pipeline_lock(path=receipt_run.archive / '.pipeline.lock') as lease:
        rdp._run_daily_with_receipt(receipt_run.args, _lease=lease, capture_inputs=True)
    receipt = json.loads((receipt_run.archive / 'run_receipt.json').read_text())
    home, now, dashboard, package, _ = _morning(tmp_path / 'morning')
    day = datetime.fromisoformat(receipt['finished_at']).astimezone(now.tzinfo).date()
    now = _attach_run(package, receipt_run.archive, day, now)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
              for p in receipt_run.archive.rglob('*') if p.is_file()}

    def forbidden(*_args, **_kwargs):
        raise AssertionError('observation attempted a network, database or writer call')

    module = _load_module()
    original = module._read_publication
    calls = []

    def count(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(module, '_read_publication', count)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(sqlite3, 'connect', forbidden)
    monkeypatch.setattr(Path, 'write_text', forbidden)
    monkeypatch.setattr(Path, 'write_bytes', forbidden)
    report = module.collect_acceptance(home=home, now=now, dashboard_reader=lambda _: (200, dashboard))
    row = report['operational_observations']['broker_cache_publication']
    assert row['status'] == 'INFO'
    assert row['publication_status'] == 'NOT_PUBLISHED'
    assert row['journal_sha256'] == receipt['commit_observation']['journal_sha256']
    assert row['anchor_source'] == 'LOCAL_PRODUCER_RECEIPT'
    assert calls == [1]
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
            for p in receipt_run.archive.rglob('*') if p.is_file()} == before


def test_broken_release_link_returns_a_report_instead_of_crashing(tmp_path):
    home, now, dashboard, _package, _archive = _morning(tmp_path)
    current = home / '.hermes/skills/investment/escape-top/current'
    current.unlink()
    current.symlink_to('current')
    report = _load_module().collect_acceptance(home=home, now=now, dashboard_reader=lambda _: (200, dashboard))
    assert report['status'] == 'FAIL'
    assert report['operational_observations']['broker_cache_publication']['reason'] == 'RELEASE_UNVERIFIED'


@pytest.mark.parametrize('change', ['receipt', 'audit', 'run_identity'])
def test_changes_inside_the_reader_discard_even_a_successful_result(tmp_path, monkeypatch, change):
    home, now, dashboard, package, archive = _morning(tmp_path)
    _stub_reader(package, 'OK')
    module = _load_module()
    original = module._read_publication

    def read(*args):
        result = original(*args)
        if change == 'run_identity':
            result['run_id'] = 'c' * 32
        else:
            path = archive / ('run_receipt.json' if change == 'receipt' else 'audit_log.jsonl')
            path.write_bytes(path.read_bytes() + b'\n')
        return result

    monkeypatch.setattr(module, '_read_publication', read)
    report = module.collect_acceptance(home=home, now=now, dashboard_reader=lambda _: (200, dashboard))
    row = report['operational_observations']['broker_cache_publication']
    assert row['status'] == 'UNKNOWN'
    assert row['reason'] == 'EVIDENCE_CHANGED'
    assert row['official_receipt_status'] is None


def test_readers_are_not_reused_after_release_switch_or_failed_load(tmp_path):
    home, now, dashboard, package, _archive = _morning(tmp_path)
    source = package / 'core/reporting/scheduled_broker_publication.py'
    source.write_text('raise ValueError("bad reader")\n')
    module = _load_module()
    first = module.collect_acceptance(home=home, now=now, dashboard_reader=lambda _: (200, dashboard))
    assert first['operational_observations']['broker_cache_publication']['reason'] == 'READER_UNAVAILABLE'
    old_core = package.resolve() / 'core'
    release, _ = _switch_to_new_release(home)
    package = release / 'hermes_escape_top'
    shutil.copytree(old_core, package / 'core')
    _stub_reader(package, 'WARN')
    second = module.collect_acceptance(home=home, now=now, dashboard_reader=lambda _: (200, dashboard))
    assert second['operational_observations']['broker_cache_publication']['status'] == 'WARN'
    assert second['operational_observations']['broker_cache_publication']['reader_release'] == release.name
    assert not any(n.startswith('_hermes_morning_reader_') for n in sys.modules)
