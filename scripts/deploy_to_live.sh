#!/bin/bash
# repo -> live deploy: one fcntl-guarded code transaction, dashboard lifecycle
# outside the lock, end-to-end acceptance, and exact rollback on any failure.
set -uo pipefail  # failures are handled explicitly so rollback always runs

SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
TEST_MODE="${HERMES_DEPLOY_TEST_MODE:-0}"
MODE="${1:---main}"

# Test overrides are deliberately unavailable in production mode. A caller that
# merely exports HERMES_DEPLOY_* cannot bypass a production guard or smoke gate.
if [ "$TEST_MODE" = "1" ]; then
  HERMES_HOME="${HERMES_DEPLOY_HOME:-}"
  REPO="${HERMES_DEPLOY_REPO:-}"
  LIVE="${HERMES_DEPLOY_LIVE:-}"
  PKG="${HERMES_DEPLOY_PACKAGE:-}"
  BIN="${HERMES_DEPLOY_BIN:-}"
  BACKUP_DIR="${HERMES_DEPLOY_BACKUP_DIR:-}"
  PYTHON="${HERMES_DEPLOY_PYTHON:-}"
  LOCK_PYTHONPATH="${HERMES_DEPLOY_LOCK_PYTHONPATH:-}"
  GUARD_CMD="${HERMES_DEPLOY_GUARD_CMD:-}"
  DASHBOARD_STOP_CMD="${HERMES_DEPLOY_DASHBOARD_STOP_CMD:-}"
  DASHBOARD_RESTART_CMD="${HERMES_DEPLOY_DASHBOARD_RESTART_CMD:-}"
  DASHBOARD_HEALTH_CMD="${HERMES_DEPLOY_DASHBOARD_HEALTH_CMD:-}"
  SMOKE_IMPORT_CMD="${HERMES_DEPLOY_SMOKE_IMPORT_CMD:-}"
  SMOKE_CMD="${HERMES_DEPLOY_SMOKE_CMD:-}"
  VERIFY_CMD="${HERMES_DEPLOY_VERIFY_CMD:-}"
  FAIL_AT="${HERMES_DEPLOY_FAIL_AT:-}"
  FAIL_ROLLBACK="${HERMES_DEPLOY_FAIL_ROLLBACK:-0}"
else
  TEST_MODE=0
  HERMES_HOME="$HOME/.hermes"
  REPO="$HOME/Documents/github/hermes"
  LIVE="$HERMES_HOME/skills/investment/escape-top"
  PKG="$LIVE/hermes_escape_top"
  BIN="$HERMES_HOME/bin"
  BACKUP_DIR="$HOME/.hermes-deploy-backups/escape-top"
  PYTHON="/usr/bin/python3"
  LOCK_PYTHONPATH="$REPO/src"
  GUARD_CMD=""
  DASHBOARD_STOP_CMD=""
  DASHBOARD_RESTART_CMD=""
  DASHBOARD_HEALTH_CMD=""
  SMOKE_IMPORT_CMD=""
  SMOKE_CMD=""
  VERIFY_CMD=""
  FAIL_AT=""
  FAIL_ROLLBACK=0
fi

if [ "$MODE" = "--locked-swap" ] || [ "$MODE" = "--locked-rollback" ]; then
  STAMP="${2:-}"
  HASH="${3:-}"
  BACKUP="${4:-}"
else
  STAMP=$(date +%Y%m%d_%H%M%S)
  HASH=$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo unknown)
  BACKUP="$BACKUP_DIR/hermes_escape_top.predeploy_backup_$STAMP"
fi

die() { echo "$1" >&2; exit "${2:-1}"; }

run_override() {
  /bin/sh -c "$1"
}

validate_test_contract() {
  [ "$TEST_MODE" = "1" ] || return 0
  local name
  for name in \
    HERMES_DEPLOY_REPO HERMES_DEPLOY_HOME HERMES_DEPLOY_LIVE \
    HERMES_DEPLOY_PACKAGE HERMES_DEPLOY_BIN HERMES_DEPLOY_BACKUP_DIR \
    HERMES_DEPLOY_PYTHON HERMES_DEPLOY_LOCK_PYTHONPATH \
    HERMES_DEPLOY_GUARD_CMD HERMES_DEPLOY_DASHBOARD_STOP_CMD \
    HERMES_DEPLOY_DASHBOARD_RESTART_CMD HERMES_DEPLOY_DASHBOARD_HEALTH_CMD \
    HERMES_DEPLOY_SMOKE_IMPORT_CMD HERMES_DEPLOY_SMOKE_CMD \
    HERMES_DEPLOY_VERIFY_CMD; do
    [ -n "${!name:-}" ] || die "!! test mode requires $name" 64
  done
}

validate_paths() {
  [ -d "$REPO/src/hermes_escape_top" ] || die "!! repo package missing: $REPO" 64
  [ -d "$PKG" ] || die "!! live package missing: $PKG" 64
  [ -d "$PKG/data/archive" ] || die "!! live archive missing: $PKG/data/archive" 64
  [ -d "$LIVE/scripts" ] || die "!! live scripts missing: $LIVE/scripts" 64
  mkdir -p "$BACKUP_DIR" || die "!! cannot create backup directory: $BACKUP_DIR" 64
}

require_pipeline_lock_held() {
  local fd="${HERMES_PIPELINE_LOCK_FD:-}"
  case "$fd" in
    ''|*[!0-9]*) die "!! internal mode requires a valid HERMES_PIPELINE_LOCK_FD" 65 ;;
  esac
  "$PYTHON" - "$PKG/data/archive/.pipeline.lock" "$fd" <<'PY' \
    || die "!! internal mode requires the pipeline lock to be held" 65
import errno
import fcntl
import os
import stat
import sys

lock_path = sys.argv[1]
inherited_fd = int(sys.argv[2])

try:
    inherited = os.fstat(inherited_fd)
    target = os.stat(lock_path)
except OSError as exc:
    print(f"pipeline lock validation failed: {exc}", file=sys.stderr)
    raise SystemExit(2)

if not stat.S_ISREG(target.st_mode):
    print("pipeline lock validation failed: target is not a regular file", file=sys.stderr)
    raise SystemExit(3)
if (inherited.st_dev, inherited.st_ino) != (target.st_dev, target.st_ino):
    print("pipeline lock validation failed: inherited fd is not the target lock", file=sys.stderr)
    raise SystemExit(4)

try:
    probe_fd = os.open(lock_path, os.O_RDWR)
except OSError as exc:
    print(f"pipeline lock validation failed: cannot open probe fd: {exc}", file=sys.stderr)
    raise SystemExit(5)

try:
    try:
        fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in {errno.EAGAIN, errno.EWOULDBLOCK}:
            raise SystemExit(0)
        print(f"pipeline lock validation failed: probe error: {exc}", file=sys.stderr)
        raise SystemExit(6)
    else:
        fcntl.flock(probe_fd, fcntl.LOCK_UN)
        print("pipeline lock validation failed: target lock is not held", file=sys.stderr)
        raise SystemExit(7)
finally:
    os.close(probe_fd)
PY
}

maybe_fail() {
  [ "$FAIL_AT" != "$1" ] || {
    echo "!! injected failure at $1" >&2
    return 1
  }
}

guard_is_clear() {
  if [ "$TEST_MODE" = "1" ]; then
    run_override "$GUARD_CMD"
  else
    ! pgrep -f "scripts/run_daily" >/dev/null 2>&1
  fi
}

deploy_index_is_clear() {
  local paths=()
  while IFS= read -r path; do
    paths+=("$path")
  done < <(deploy_git_pathspecs)
  git -C "$HERMES_HOME" diff --cached --quiet -- "${paths[@]}"
}

stop_dashboard() {
  if [ "$TEST_MODE" = "1" ]; then
    run_override "$DASHBOARD_STOP_CMD"
    return
  fi
  local target="gui/$(id -u)/com.hermes.dashboard"
  launchctl bootout "$target" >/dev/null 2>&1 && return 0
  ! launchctl print "$target" >/dev/null 2>&1
}

restart_dashboard() {
  if [ "$TEST_MODE" = "1" ]; then
    run_override "$DASHBOARD_RESTART_CMD"
    return
  fi
  local domain="gui/$(id -u)"
  local target="$domain/com.hermes.dashboard"
  local plist="$HOME/Library/LaunchAgents/com.hermes.dashboard.plist"
  launchctl bootstrap "$domain" "$plist" >/dev/null 2>&1 || return 1
  launchctl kickstart -k "$target"
}

dashboard_is_healthy() {
  if [ "$TEST_MODE" = "1" ]; then
    run_override "$DASHBOARD_HEALTH_CMD"
    return
  fi
  local ok=0
  local _
  for _ in 1 2 3 4 5 6 7 8; do
    sleep 1
    curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8766/ 2>/dev/null \
      | grep -q 200 && { ok=1; break; }
  done
  [ "$ok" = 1 ]
}

run_import_smoke() {
  if [ "$TEST_MODE" = "1" ]; then
    run_override "$SMOKE_IMPORT_CMD"
  else
    ( cd "$LIVE" && PYTHONPATH=. /usr/bin/python3 -c "import hermes_escape_top.pipeline" )
  fi
}

run_predeploy_smoke() {
  if [ "$TEST_MODE" = "1" ]; then
    run_override "$SMOKE_CMD"
  else
    ( cd "$LIVE" && PYTHONPATH=. /usr/bin/python3 -m hermes_escape_top.scripts.predeploy_smoke )
  fi
}

run_verify_live() {
  if [ "$TEST_MODE" = "1" ]; then
    run_override "$VERIFY_CMD"
  else
    bash "$REPO/ops/verify_live.sh"
  fi
}

run_with_pipeline_lock() {
  local internal_mode="$1"
  PYTHONPATH="$LOCK_PYTHONPATH" "$PYTHON" \
    -m hermes_escape_top.scripts.pipeline_lock_exec \
    --archive-dir "$PKG/data/archive" --timeout 600 -- \
    /bin/bash "$SCRIPT_PATH" "$internal_mode" "$STAMP" "$HASH" "$BACKUP"
}

backup_entry() {
  local source="$1"
  local name="$2"
  if [ -e "$source" ]; then
    cp -p "$source" "$BACKUP/bin/$name" || return 1
    echo present > "$BACKUP/bin/$name.state" || return 1
  else
    echo absent > "$BACKUP/bin/$name.state" || return 1
  fi
}

restore_entry() {
  local target="$1"
  local name="$2"
  local state
  state=$(cat "$BACKUP/bin/$name.state" 2>/dev/null) || return 1
  if [ "$state" = "present" ]; then
    cp -p "$BACKUP/bin/$name" "$target" || return 1
  elif [ "$state" = "absent" ]; then
    rm -f "$target" || return 1
  else
    return 1
  fi
}

backup_git_index() {
  if [ -f "$HERMES_HOME/.git/index" ]; then
    cp -p "$HERMES_HOME/.git/index" "$BACKUP/hermes_git_index" || return 1
    echo present > "$BACKUP/hermes_git_index.state" || return 1
  else
    echo absent > "$BACKUP/hermes_git_index.state" || return 1
  fi
}

restore_git_index() {
  local state
  state=$(cat "$BACKUP/hermes_git_index.state" 2>/dev/null) || return 1
  if [ "$state" = "present" ]; then
    cp -p "$BACKUP/hermes_git_index" "$HERMES_HOME/.git/index" || return 1
  elif [ "$state" = "absent" ]; then
    rm -f "$HERMES_HOME/.git/index" || return 1
  else
    return 1
  fi
}

create_backup() {
  mkdir "$BACKUP" || return 1
  mkdir -p "$BACKUP/package" "$BACKUP/live_scripts" "$BACKUP/bin" || return 1
  rsync -a --exclude='data/' "$PKG/" "$BACKUP/package/" || return 1
  rsync -a "$LIVE/scripts/" "$BACKUP/live_scripts/" || return 1
  backup_entry "$BIN/run_daily.sh" run_daily.sh || return 1
  backup_entry "$BIN/serve_dashboard.sh" serve_dashboard.sh || return 1
  backup_git_index || return 1
}

# This function is called only by --locked-swap/--locked-rollback. It restores
# files and git index while the inherited pipeline lease is still held. It must
# never manage dashboard lifecycle.
rollback_locked() {
  echo "!! ROLLBACK: restoring exact pre-deploy trees ($STAMP)" >&2
  if [ "$FAIL_ROLLBACK" = "1" ]; then
    echo "  injected rollback failure; backup retained: $BACKUP" >&2
    return 1
  fi
  [ -d "$BACKUP/package" ] || return 1
  [ -d "$BACKUP/live_scripts" ] || return 1

  local failed=0
  rsync -a --checksum --delete --exclude='data/' "$BACKUP/package/" "$PKG/" || failed=1
  rsync -a --checksum --delete "$BACKUP/live_scripts/" "$LIVE/scripts/" || failed=1
  restore_entry "$BIN/run_daily.sh" run_daily.sh || failed=1
  restore_entry "$BIN/serve_dashboard.sh" serve_dashboard.sh || failed=1
  restore_git_index || failed=1
  [ "$failed" = 0 ]
}

fail_locked_swap() {
  local message="$1"
  local code="${2:-1}"
  if rollback_locked; then
    die "$message — rolled back under pipeline lock" "$code"
  else
    die "!! DOUBLE FAILURE: $message; rollback failed; backup retained: $BACKUP" 90
  fi
}

sync_code() {
  rsync -a --checksum --delete \
    --exclude='tests/' --exclude='config/' --exclude='data/' \
    --include='*/' --include='*.py' --exclude='*' \
    "$REPO/src/hermes_escape_top/" "$PKG/"
}

sync_entries() {
  local pair src dst
  for pair in \
    "run_daily.sh:$BIN/run_daily.sh" \
    "serve_dashboard.sh:$BIN/serve_dashboard.sh" \
    "run_daily.py:$LIVE/scripts/run_daily.py"; do
    src="$REPO/ops/${pair%%:*}"
    dst="${pair##*:}"
    cp "$src" "$dst" || return 1
  done
  chmod +x "$BIN/run_daily.sh" "$BIN/serve_dashboard.sh" "$LIVE/scripts/run_daily.py" \
    2>/dev/null || true
}

run_locked_swap() {
  echo "== 1/7 backup exact live/repo trees + git index =="
  create_backup || die "!! backup failed; partial backup retained: $BACKUP" 1

  echo "== 2/7 code rsync repo->live (--delete; *.py excl tests/config/data) =="
  sync_code || fail_locked_swap "!! code rsync failed" 1
  echo "$HASH $STAMP" > "$PKG/VERSION" \
    || fail_locked_swap "!! VERSION write failed" 1

  echo "== 3/7 sync live-only entry scripts from ops/ =="
  sync_entries || fail_locked_swap "!! entry sync failed" 1
  maybe_fail post_sync || fail_locked_swap "!! post-sync validation failed" 1

  echo "== 4/7 config gate (human; runtime data never writes back to repo) =="
  if ! diff -u "$PKG/config/config.json" "$REPO/src/hermes_escape_top/config/config.json"; then
    local ans
    read -r -p "Apply repo config to live? [y/N] " ans
    if [ "${ans:-N}" = "y" ]; then
      cp "$REPO/src/hermes_escape_top/config/config.json" "$PKG/config/config.json" \
        || fail_locked_swap "!! config apply failed" 1
      echo "  config applied (pre-deploy copy is in backup)"
    else
      echo "  config NOT applied"
    fi
  fi

  echo "== 5/7 smoke on live (rollback on fail) =="
  maybe_fail smoke || fail_locked_swap "!! smoke gate FAIL" 2
  run_import_smoke || fail_locked_swap "!! import broken after deploy" 2
  run_predeploy_smoke || fail_locked_swap "!! smoke gate FAIL" 2
}

deploy_git_pathspecs() {
  printf '%s\n' \
    ':(glob)skills/investment/escape-top/hermes_escape_top/**/*.py' \
    ':(exclude,glob)skills/investment/escape-top/hermes_escape_top/tests/**' \
    ':(exclude,glob)skills/investment/escape-top/hermes_escape_top/data/**' \
    ':(exclude,glob)skills/investment/escape-top/hermes_escape_top/config/**' \
    'skills/investment/escape-top/hermes_escape_top/VERSION' \
    'skills/investment/escape-top/scripts/run_daily.py' \
    'bin/run_daily.sh' \
    'bin/serve_dashboard.sh'
}

stage_deploy_allowlist() {
  local paths=()
  while IFS= read -r path; do
    paths+=("$path")
  done < <(deploy_git_pathspecs)
  git -C "$HERMES_HOME" add -- "${paths[@]}"
}

commit_deploy_allowlist() {
  local paths=()
  while IFS= read -r path; do
    paths+=("$path")
  done < <(deploy_git_pathspecs)
  git -C "$HERMES_HOME" commit --no-verify -m "deploy escape-top @$HASH ($STAMP)" \
    -- "${paths[@]}"
}

rollback_after_release() {
  local message="$1"
  local code="$2"
  local rollback_rc restart_rc

  stop_dashboard || die "!! DOUBLE FAILURE: $message; cannot stop dashboard for rollback; backup: $BACKUP" 90
  run_with_pipeline_lock --locked-rollback
  rollback_rc=$?
  if [ "$rollback_rc" -ne 0 ]; then
    die "!! DOUBLE FAILURE: $message; locked rollback failed ($rollback_rc); dashboard remains stopped; backup: $BACKUP" 90
  fi
  restart_dashboard
  restart_rc=$?
  [ "$restart_rc" -eq 0 ] \
    || die "!! DOUBLE FAILURE: $message; rollback succeeded but dashboard restart failed; backup: $BACKUP" 90
  die "$message — rolled back under pipeline lock" "$code"
}

validate_test_contract
validate_paths

case "$MODE" in
  --locked-swap)
    require_pipeline_lock_held
    run_locked_swap
    exit $?
    ;;
  --locked-rollback)
    require_pipeline_lock_held
    rollback_locked
    exit $?
    ;;
  --main)
    ;;
  *)
    die "!! unknown deploy mode: $MODE" 64
    ;;
esac

echo "== 0/7 guard + stop dashboard =="
guard_is_clear || die "!! a daily run appears in progress — aborting deploy." 4
deploy_index_is_clear \
  || die "!! .hermes has pre-staged deploy-allowlist files — aborting before dashboard stop" 4
stop_dashboard || die "!! dashboard stop failed — deploy not started" 4
echo "  clear; dashboard stopped"

run_with_pipeline_lock --locked-swap
swap_rc=$?
if [ "$swap_rc" -eq 90 ]; then
  die "!! locked swap and rollback failed; dashboard remains stopped; backup: $BACKUP" 90
fi

# The lock helper has exited here. Dashboard lifecycle is never managed while
# HERMES_PIPELINE_LOCK_FD is present.
maybe_fail dashboard_restart \
  || rollback_after_release "!! dashboard restart failed" 2
restart_dashboard
restart_rc=$?
if [ "$swap_rc" -ne 0 ]; then
  [ "$restart_rc" -eq 0 ] \
    || die "!! locked swap failed ($swap_rc) and dashboard restart failed; backup: $BACKUP" 90
  die "!! locked swap failed ($swap_rc); pre-deploy tree restored" "$swap_rc"
fi
if [ "$restart_rc" -ne 0 ]; then
  rollback_after_release "!! dashboard restart failed" 2
fi

echo "== 6/7 accept dashboard + verify live =="
dashboard_is_healthy || rollback_after_release "!! dashboard not serving 200 after restart" 2
echo "  dashboard up · live VERSION=$(cat "$PKG/VERSION")"
echo "-- end-to-end: real entry (manual_rerun) effects landed --"
maybe_fail verify_live || rollback_after_release "!! verify_live FAIL — real entry broken" 3
run_verify_live || rollback_after_release "!! verify_live FAIL — real entry broken" 3

echo "== 7/7 commit in .hermes git =="
stage_deploy_allowlist \
  || rollback_after_release "!! .hermes git add failed" 3
maybe_fail hermes_commit || rollback_after_release "!! .hermes commit failed" 3
commit_deploy_allowlist \
  || rollback_after_release "!! .hermes commit failed" 3

echo "✅ deploy OK @$HASH · backup: $BACKUP"
