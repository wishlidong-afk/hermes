"""Collect whitelisted live metadata without importing or executing Hermes."""
from contextlib import closing
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import sqlite3
import subprocess
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
CURRENT = Path('/Users/liweishi/.hermes/skills/investment/escape-top/current')
PACKAGE = CURRENT / 'hermes_escape_top'
ARCHIVE = PACKAGE / 'data/archive'
CANDIDATE = Path('/Users/liweishi/Documents/New project/hermes-a2-postcommit-health-2026-11-04/candidate')
OLD_REPO = Path('/Users/liweishi/Documents/New project/hermes-r6-offline-tools-2026-10-30')
COMMIT = 'c1f4b8fc1df23876fefeccd33bc08e0270627f9e'
REPORT = Path('/Users/liweishi/.hermes/logs/acceptance/morning_acceptance_2026-11-04.json')
DAY = '2026-11-04'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def stable(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def optional_hash(path):
    return sha(path) if path.exists() else None


start = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
release_before = CURRENT.resolve(strict=True)
acceptance = read(REPORT)
markdown = REPORT.with_suffix('.md').read_text()
health_path = Path(next(row['evidence'] for row in acceptance['checks'] if row['id'] == 'bound_health_report'))
health = read(health_path)
latest = None
audit_count = 0
with (ARCHIVE / 'audit_log.jsonl').open() as stream:
    for line in stream:
        if line.strip():
            payload = json.loads(line)['payload']
            if payload.get('run_type') == 'scheduled':
                latest = payload
                audit_count += 1
assert latest is not None
evidence = latest['decision_evidence']
journal_path = ARCHIVE / f".score_run_transactions/runs/{latest['persistence']['run_id']}/manifest.json"
active = ARCHIVE / '.score_run_transactions/active.json'
main_db = ARCHIVE / 'hermes_state.sqlite'
watched = [PACKAGE / 'VERSION', PACKAGE / 'config/config.json', PACKAGE / 'governance/approved_live_config.json',
    PACKAGE / 'LIVE_CONFIG_ATTESTATION.json', ARCHIVE / 'audit_log.jsonl', main_db,
    ARCHIVE / 'run_receipt.json', ARCHIVE / 'data_manifest_latest.json', journal_path, active,
    REPORT, REPORT.with_suffix('.md'), health_path]
watched += [Path(str(main_db) + suffix) for suffix in ('-wal', '-shm', '-journal')]
watched += [ARCHIVE / name for name in ('reentry_state.sqlite', 'mirror_reference.sqlite', 'flow_reference.sqlite',
                                       'signal_journal.jsonl', 'soft_adapter_snapshot_' + latest['as_of'][:10] + '.json')]
before = {str(path): optional_hash(path) for path in watched}
sidecars = [Path(str(main_db) + suffix) for suffix in ('-wal', '-shm', '-journal')]
assert not any(path.exists() for path in sidecars), 'SQLite sidecar present; do not use immutable or touch live SHM'
with closing(sqlite3.connect(main_db.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as connection:
    state_latest = None
    for (raw,) in connection.execute('SELECT payload_json FROM score_runs ORDER BY id DESC'):
        value = json.loads(raw)
        if value.get('run_type') == 'scheduled':
            state_latest = value
            break
assert state_latest is not None
assert state_latest['decision_evidence'] == evidence and state_latest['input_hash'] == latest['input_hash']
assert evidence['semantic_hash'] == stable(evidence['semantic_identity'])
expected_id = 'decision-' + evidence['as_of'] + '-r' + str(evidence['decision_revision']) + '-' + stable({
    'as_of': evidence['as_of'], 'decision_hash': evidence['decision_hash'],
    'decision_revision': evidence['decision_revision'], 'bar_finality': evidence['bar_finality']})[:20]
assert expected_id == evidence['decision_id']
config = read(PACKAGE / 'config/config.json')
candidate_config = read(CANDIDATE / 'src/hermes_escape_top/config/config.json')
attestation = read(PACKAGE / 'LIVE_CONFIG_ATTESTATION.json')
assert sha(PACKAGE / 'config/config.json') == attestation['live_config_sha256']
assert sha(PACKAGE / 'governance/approved_live_config.json') == attestation['policy_sha256']
assert config['ibkr']['readonly'] is True
feature_diff = {key: {'live': config['features'].get(key), 'candidate_default': candidate_config['features'].get(key),
                     'live_key_present': key in config['features'], 'candidate_key_present': key in candidate_config['features']}
    for key in sorted(config['features'].keys() | candidate_config['features'].keys())
    if config['features'].get(key) != candidate_config['features'].get(key)}
assert all((row['live'] is None or isinstance(row['live'], bool))
           and isinstance(row['candidate_default'], bool) for row in feature_diff.values())
manifest = read(ARCHIVE / 'data_manifest_latest.json')
assert manifest['schema_version'] == 'escape-top-data-manifest-v1'
assert hashlib.sha256(json.dumps(dict(sorted(manifest['entries'].items())), sort_keys=True).encode()).hexdigest() == manifest['manifest_id']
history = Path(manifest['root']).resolve(strict=True)
assert history == (PACKAGE / 'data/history').resolve(strict=True)
observed_files = {path.relative_to(history).as_posix() for path in history.rglob('*') if path.is_file()}
assert observed_files == set(manifest['entries'])
for name, entry in manifest['entries'].items():
    relative = Path(name)
    assert not relative.is_absolute() and '..' not in relative.parts and entry['path'] == name
    assert sha(history / name) == entry['sha256']
journal = read(journal_path)
assert journal['status'] == 'COMMITTED' and len(journal['artifacts']) == 7 and not active.exists()
assert acceptance['acceptance_date'] == DAY
generated = datetime.fromisoformat(acceptance['generated_at'])
assert generated.tzinfo is not None and generated.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat() == DAY
for key, value in (('status', acceptance['status']), ('generated_at', acceptance['generated_at']),
    ('runtime_integrity', acceptance['readiness']['runtime_integrity']['status']),
    ('strategy_decision', acceptance['readiness']['strategy_decision']['status']),
    ('post_deploy_certification', acceptance['post_deploy_certification']['status'])):
    match = re.search(r'^- ' + re.escape(key) + r': `([^`]+)`', markdown, re.MULTILINE)
    assert match and match.group(1) == value, key
md_checks = {}
for line in markdown.splitlines():
    if line.startswith('|'):
        fields = [part.strip() for part in line.split('|')]
        if len(fields) > 3:
            md_checks[fields[1]] = fields[2]
assert all(md_checks.get(row['id']) == row['status'] for row in acceptance['checks'])
assert health['as_of'] == latest['as_of'] and health['input_hash'] == latest['input_hash']
assert health['decision_hash'] == evidence['decision_hash']
tree = subprocess.check_output(['git', '-C', str(OLD_REPO), 'ls-tree', '-r', '-z', COMMIT, '--', 'src/hermes_escape_top'],
    env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'}).decode()
expected = {}
for line in filter(None, tree.split('\0')):
    metadata, name = line.split('\t', 1)
    relative = Path(name).relative_to('src/hermes_escape_top')
    if relative.suffix == '.py' and relative.parts[0] not in {'tests', 'data'} and '__pycache__' not in relative.parts:
        expected[relative.as_posix()] = metadata.split()[2]
actual = {}
for path in PACKAGE.rglob('*.py'):
    relative = path.relative_to(PACKAGE)
    if relative.parts[0] not in {'tests', 'data'} and '__pycache__' not in relative.parts:
        raw = path.read_bytes()
        actual[relative.as_posix()] = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
assert actual == expected
plist = Path('/Users/liweishi/Library/LaunchAgents/com.hermes.morning-acceptance.plist')
service = plistlib.loads(plist.read_bytes())
installed = Path('/Users/liweishi/.local/libexec/hermes-morning-acceptance/morning_acceptance.py')
after = {str(path): optional_hash(path) for path in watched}
assert before == after and CURRENT.resolve(strict=True) == release_before
assert all(sha(history / name) == entry['sha256'] for name, entry in manifest['entries'].items())
result = {
    'scope': 'READ_ONLY_METADATA_PREFLIGHT_NOT_RELEASE_PROOF', 'started_at': start,
    'finished_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(), 'stable_observation': True,
    'release': {'target': str(release_before), 'VERSION': (PACKAGE / 'VERSION').read_text().strip(),
                'baseline_commit': COMMIT, 'non_test_python_files_match_commit': len(actual)},
    'decision': {key: value for key, value in evidence.items() if key != 'semantic_identity'},
    'semantic_logic_hash': evidence['semantic_identity']['scoring_logic_hash'],
    'audit_state_identity_input_equal': True, 'audit_successful_scheduled_rows_total': audit_count,
    'persistence': latest['persistence'], 'transaction_status': journal['status'], 'artifacts': 7, 'active_absent': True,
    'config': {'live_raw_sha256': sha(PACKAGE / 'config/config.json'), 'candidate_default_raw_sha256': sha(CANDIDATE / 'src/hermes_escape_top/config/config.json'),
               'attestation_sha256': sha(PACKAGE / 'LIVE_CONFIG_ATTESTATION.json'), 'attestation_matches': True,
               'policy_sha256': attestation['policy_sha256'], 'feature_diff': feature_diff, 'ibkr_readonly': True,
               'actual_live_config_used_in_synthetic_rehearsals': False},
    'current_manifest': {'raw_sha256': sha(ARCHIVE / 'data_manifest_latest.json'), 'manifest_id': manifest['manifest_id'],
        'frozen_at': manifest['frozen_at'], 'root': str(history), 'entries_verified': len(observed_files),
        'entries_sha256': {name: entry['sha256'] for name, entry in manifest['entries'].items()},
        'matches_certified_full_manifest': manifest['manifest_id'] == evidence['canonical_market_evidence_hash']},
    'morning': {'acceptance_date': DAY, 'generated_at': acceptance['generated_at'], 'status': acceptance['status'],
        'runtime_integrity': acceptance['readiness']['runtime_integrity']['status'],
        'strategy_decision': acceptance['readiness']['strategy_decision']['status'],
        'post_deploy_certification': acceptance['post_deploy_certification']['status'], 'json_md_match': True,
        'checks': [{key: row[key] for key in ('id','status','evidence')} for row in acceptance['checks']],
        'health_labels': [{key: row.get(key) for key in ('label','level','layer')} for row in health['health']['checks']],
        'ibkr_age_seconds': health['health'].get('ibkr_age_seconds'), 'Dollar_WARN': 'NOT_LISTED_IN_THIS_BOUND_HEALTH_REPORT'},
    'acceptance_install': {'plist_sha256': sha(plist), 'label': service['Label'], 'program_arguments': service['ProgramArguments'],
        'schedule': service['StartCalendarInterval'], 'installed_script_sha256': sha(installed),
        'candidate_script_sha256': sha(CANDIDATE / 'ops/morning_acceptance.py'),
        'publication_reader_dependencies': {name: {
            'live_exists': (PACKAGE / name).is_file(),
            'candidate_sha256': sha(CANDIDATE / 'src/hermes_escape_top' / name)} for name in (
                'core/reporting/broker_publication_status.py', 'core/reporting/scheduled_broker_publication.py')}},
    'observed_source_hashes_before_after_equal': before,
    'sqlite_read_mode': 'mode=ro&immutable=1; all WAL/SHM/journal absent before and after; OS writes denied',
    'not_done': ['No score recalculation', 'No market/external/IBKR request', 'No deployment/runtime/libexec/cron changes',
                 'No writer lock acquired; active absence is an observation, not a reserved deployment window',
                 'No final-candidate same-as-of release approval or natural ON/v2 certification'],
    'DEPLOY': 'HOLD', 'A2': 'OPEN', 'Phase_B': 'NOT_STARTED',
}
output = ROOT / 'live-metadata-final.json'
with output.open('x') as stream:
    stream.write(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
print(json.dumps({'stable_observation': True, 'as_of': latest['as_of'], 'revision': evidence['decision_revision'],
    'current_full_manifest_matches_certified': result['current_manifest']['matches_certified_full_manifest'],
    'live_python_files': len(actual), 'feature_diffs': len(feature_diff), 'morning': acceptance['status'],
    'libexec_is_candidate': sha(installed) == sha(CANDIDATE / 'ops/morning_acceptance.py'), 'DEPLOY': 'HOLD'}, indent=2))
