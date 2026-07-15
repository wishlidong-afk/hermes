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
  LAUNCHAGENTS_DIR="${HERMES_DEPLOY_LAUNCHAGENTS_DIR:-$HERMES_HOME/Library/LaunchAgents}"
  BACKUP_DIR="${HERMES_DEPLOY_BACKUP_DIR:-}"
  PYTHON="${HERMES_DEPLOY_PYTHON:-}"
  LOCK_PYTHONPATH="${HERMES_DEPLOY_LOCK_PYTHONPATH:-}"
  GUARD_CMD="${HERMES_DEPLOY_GUARD_CMD:-}"
  DASHBOARD_STOP_CMD="${HERMES_DEPLOY_DASHBOARD_STOP_CMD:-}"
  DASHBOARD_RESTART_CMD="${HERMES_DEPLOY_DASHBOARD_RESTART_CMD:-}"
  DASHBOARD_HEALTH_CMD="${HERMES_DEPLOY_DASHBOARD_HEALTH_CMD:-}"
  EXTERNAL_PRECHECK_RELOAD_CMD="${HERMES_DEPLOY_EXTERNAL_PRECHECK_RELOAD_CMD:-}"
  RETENTION_RELOAD_CMD="${HERMES_DEPLOY_RETENTION_RELOAD_CMD:-}"
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
  LAUNCHAGENTS_DIR="$HOME/Library/LaunchAgents"
  BACKUP_DIR="$HOME/.hermes-deploy-backups/escape-top"
  PYTHON="/usr/bin/python3"
  LOCK_PYTHONPATH="$REPO/src"
  GUARD_CMD=""
  DASHBOARD_STOP_CMD=""
  DASHBOARD_RESTART_CMD=""
  DASHBOARD_HEALTH_CMD=""
  EXTERNAL_PRECHECK_RELOAD_CMD=""
  RETENTION_RELOAD_CMD=""
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

RELEASES="$LIVE/releases"
CURRENT="$LIVE/current"
PREVIOUS="$LIVE/previous"
SHARED_PKG="$LIVE/shared/hermes_escape_top"
LEGACY_PKG="$LIVE/hermes_escape_top"
RELEASE_ID="${HASH}_${STAMP}"
NEW_RELEASE="$RELEASES/$RELEASE_ID"
NEW_PKG="$NEW_RELEASE/hermes_escape_top"
EXTERNAL_PRECHECK_LAUNCHAGENT="$LAUNCHAGENTS_DIR/com.hermes.external-precheck.plist"
RETENTION_LAUNCHAGENT="$LAUNCHAGENTS_DIR/com.hermes.runtime-retention.plist"

if [ -d "$CURRENT/hermes_escape_top" ]; then
  ACTIVE_BASE="$CURRENT"
  PKG="$CURRENT/hermes_escape_top"
else
  ACTIVE_BASE="$LIVE"
  PKG="${PKG:-$LEGACY_PKG}"
fi

if [ -d "$SHARED_PKG/data/archive" ]; then
  LOCK_ARCHIVE_DIR="$SHARED_PKG/data/archive"
else
  LOCK_ARCHIVE_DIR="$PKG/data/archive"
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
    HERMES_DEPLOY_LAUNCHAGENTS_DIR \
    HERMES_DEPLOY_PYTHON HERMES_DEPLOY_LOCK_PYTHONPATH \
    HERMES_DEPLOY_GUARD_CMD HERMES_DEPLOY_DASHBOARD_STOP_CMD \
    HERMES_DEPLOY_DASHBOARD_RESTART_CMD HERMES_DEPLOY_DASHBOARD_HEALTH_CMD \
    HERMES_DEPLOY_EXTERNAL_PRECHECK_RELOAD_CMD \
    HERMES_DEPLOY_RETENTION_RELOAD_CMD \
    HERMES_DEPLOY_SMOKE_IMPORT_CMD HERMES_DEPLOY_SMOKE_CMD \
    HERMES_DEPLOY_VERIFY_CMD; do
    [ -n "${!name:-}" ] || die "!! test mode requires $name" 64
  done
}

validate_paths() {
  [ -d "$REPO/src/hermes_escape_top" ] || die "!! repo package missing: $REPO" 64
  [ -d "$PKG" ] || die "!! live package missing: $PKG" 64
  [ -d "$LOCK_ARCHIVE_DIR" ] || die "!! live archive missing: $LOCK_ARCHIVE_DIR" 64
  [ -d "$LIVE/scripts" ] || [ -d "$CURRENT/scripts" ] || die "!! live scripts missing: $LIVE/scripts" 64
  mkdir -p "$BACKUP_DIR" || die "!! cannot create backup directory: $BACKUP_DIR" 64
}

require_pipeline_lock_held() {
  local fd="${HERMES_PIPELINE_LOCK_FD:-}"
  case "$fd" in
    ''|*[!0-9]*) die "!! internal mode requires a valid HERMES_PIPELINE_LOCK_FD" 65 ;;
  esac
  "$PYTHON" - "$LOCK_ARCHIVE_DIR/.pipeline.lock" "$fd" <<'PY' \
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

reload_external_precheck_launchagent() {
  if [ "$TEST_MODE" = "1" ]; then
    run_override "$EXTERNAL_PRECHECK_RELOAD_CMD"
    return
  fi
  local domain="gui/$(id -u)"
  local target="$domain/com.hermes.external-precheck"
  if launchctl print "$target" >/dev/null 2>&1; then
    launchctl bootout "$target" >/dev/null 2>&1 || return 1
  fi
  launchctl bootstrap "$domain" "$EXTERNAL_PRECHECK_LAUNCHAGENT" >/dev/null 2>&1
}

reload_runtime_retention_launchagent() {
  if [ "$TEST_MODE" = "1" ]; then
    run_override "$RETENTION_RELOAD_CMD"
    return
  fi
  local domain="gui/$(id -u)"
  local target="$domain/com.hermes.runtime-retention"
  if launchctl print "$target" >/dev/null 2>&1; then
    launchctl bootout "$target" >/dev/null 2>&1 || return 1
  fi
  launchctl bootstrap "$domain" "$RETENTION_LAUNCHAGENT" >/dev/null 2>&1
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
  local base="${1:-$ACTIVE_BASE}"
  if [ "$TEST_MODE" = "1" ]; then
    run_override "$SMOKE_IMPORT_CMD"
  else
    ( cd "$base" && HERMES_RUNTIME_ROOT="$LIVE" PYTHONPATH=. /usr/bin/python3 -c "import hermes_escape_top.pipeline" )
  fi
}

run_predeploy_smoke() {
  local base="${1:-$ACTIVE_BASE}"
  if [ "$TEST_MODE" = "1" ]; then
    run_override "$SMOKE_CMD"
  else
    ( cd "$base" && HERMES_RUNTIME_ROOT="$LIVE" PYTHONPATH=. /usr/bin/python3 -m hermes_escape_top.scripts.predeploy_smoke )
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
  local archive_dir
  if [ -d "$SHARED_PKG/data/archive" ]; then
    archive_dir="$SHARED_PKG/data/archive"
  else
    archive_dir="$LOCK_ARCHIVE_DIR"
  fi
  PYTHONPATH="$LOCK_PYTHONPATH" "$PYTHON" \
    -m hermes_escape_top.scripts.pipeline_lock_exec \
    --archive-dir "$archive_dir" --timeout 600 -- \
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

backup_link_state() {
  local path="$1"
  local name="$2"
  mkdir -p "$BACKUP/links" || return 1
  if [ -L "$path" ]; then
    echo symlink > "$BACKUP/links/$name.state" || return 1
    readlink "$path" > "$BACKUP/links/$name.target" || return 1
  elif [ -e "$path" ]; then
    echo other > "$BACKUP/links/$name.state" || return 1
  else
    echo absent > "$BACKUP/links/$name.state" || return 1
  fi
}

restore_link_state() {
  local path="$1"
  local name="$2"
  local state target tmp
  state=$(cat "$BACKUP/links/$name.state" 2>/dev/null) || return 1
  if [ "$state" = "symlink" ]; then
    target=$(cat "$BACKUP/links/$name.target" 2>/dev/null) || return 1
    tmp="$path.rollback.$STAMP.tmp"
    rm -f "$tmp" || return 1
    ln -s "$target" "$tmp" || return 1
    "$PYTHON" - "$tmp" "$path" <<'PY' || return 1
import os
import sys
os.replace(sys.argv[1], sys.argv[2])
PY
  elif [ "$state" = "absent" ]; then
    rm -f "$path" || return 1
  elif [ "$state" = "other" ]; then
    echo "cannot restore non-symlink release pointer: $path" >&2
    return 1
  else
    return 1
  fi
}

backup_shared_state() {
  if [ -e "$SHARED_PKG" ]; then
    echo present > "$BACKUP/shared_pkg.state" || return 1
  else
    echo absent > "$BACKUP/shared_pkg.state" || return 1
  fi
}

restore_shared_state() {
  local state
  state=$(cat "$BACKUP/shared_pkg.state" 2>/dev/null) || return 1
  if [ "$state" = "absent" ]; then
    rm -rf "$SHARED_PKG" || return 1
    rmdir "$LIVE/shared" 2>/dev/null || true
  fi
}

backup_path_state() {
  local path="$1"
  local name="$2"
  if [ -e "$path" ]; then
    echo present > "$BACKUP/$name.state" || return 1
  else
    echo absent > "$BACKUP/$name.state" || return 1
  fi
}

restore_path_state() {
  local path="$1"
  local name="$2"
  local state
  state=$(cat "$BACKUP/$name.state" 2>/dev/null) || return 1
  if [ "$state" = "absent" ]; then
    rm -rf "$path" || return 1
  fi
}

create_backup() {
  mkdir "$BACKUP" || return 1
  mkdir -p "$BACKUP/package" "$BACKUP/live_scripts" "$BACKUP/bin" || return 1
  rsync -a --exclude='data/' "$PKG/" "$BACKUP/package/" || return 1
  if [ -d "$LIVE/scripts" ]; then
    rsync -a "$LIVE/scripts/" "$BACKUP/live_scripts/" || return 1
  fi
  backup_entry "$BIN/run_daily.sh" run_daily.sh || return 1
  backup_entry "$BIN/serve_dashboard.sh" serve_dashboard.sh || return 1
  backup_entry "$BIN/refresh_external_precheck.sh" refresh_external_precheck.sh || return 1
  backup_entry "$BIN/hermes_watchdog.py" hermes_watchdog.py || return 1
  backup_entry "$BIN/prune_runtime_artifacts.py" prune_runtime_artifacts.py || return 1
  backup_entry "$EXTERNAL_PRECHECK_LAUNCHAGENT" external_precheck_launchagent.plist || return 1
  backup_entry "$RETENTION_LAUNCHAGENT" runtime_retention_launchagent.plist || return 1
  backup_link_state "$CURRENT" current || return 1
  backup_link_state "$PREVIOUS" previous || return 1
  backup_shared_state || return 1
  backup_path_state "$LIVE/data" live_data || return 1
  backup_path_state "$LIVE/reports" live_reports || return 1
  backup_path_state "$LIVE/orders" live_orders || return 1
  backup_path_state "$RELEASES" releases_dir || return 1
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
  if [ -d "$LIVE/scripts" ]; then
    rsync -a --checksum --delete "$BACKUP/live_scripts/" "$LIVE/scripts/" || failed=1
  fi
  restore_entry "$BIN/run_daily.sh" run_daily.sh || failed=1
  restore_entry "$BIN/serve_dashboard.sh" serve_dashboard.sh || failed=1
  restore_entry "$BIN/refresh_external_precheck.sh" refresh_external_precheck.sh || failed=1
  restore_entry "$BIN/hermes_watchdog.py" hermes_watchdog.py || failed=1
  restore_entry "$BIN/prune_runtime_artifacts.py" prune_runtime_artifacts.py || failed=1
  restore_entry "$EXTERNAL_PRECHECK_LAUNCHAGENT" external_precheck_launchagent.plist || failed=1
  restore_entry "$RETENTION_LAUNCHAGENT" runtime_retention_launchagent.plist || failed=1
  restore_link_state "$CURRENT" current || failed=1
  restore_link_state "$PREVIOUS" previous || failed=1
  rm -rf "$NEW_RELEASE" || failed=1
  restore_path_state "$RELEASES" releases_dir || failed=1
  restore_shared_state || failed=1
  restore_path_state "$LIVE/data" live_data || failed=1
  restore_path_state "$LIVE/reports" live_reports || failed=1
  restore_path_state "$LIVE/orders" live_orders || failed=1
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
  local dst="${1:-$PKG}"
  rsync -a --checksum --delete \
    --exclude='/tests/' --exclude='/config/' --exclude='/data/' --exclude='/orders/' \
    --include='*/' --include='*.py' --exclude='*' \
    "$REPO/src/hermes_escape_top/" "$dst/"
}

sync_entries() {
  local src
  mkdir -p "$BIN" "$LAUNCHAGENTS_DIR" "$LIVE/scripts" "$NEW_RELEASE/scripts" || return 1
  src="$REPO/ops/run_daily.sh"
  cp "$src" "$BIN/run_daily.sh" || return 1
  src="$REPO/ops/serve_dashboard.sh"
  cp "$src" "$BIN/serve_dashboard.sh" || return 1
  src="$REPO/ops/refresh_external_precheck.sh"
  cp "$src" "$BIN/refresh_external_precheck.sh" || return 1
  src="$REPO/ops/hermes_watchdog.py"
  cp "$src" "$BIN/hermes_watchdog.py" || return 1
  src="$REPO/ops/prune_runtime_artifacts.py"
  cp "$src" "$BIN/prune_runtime_artifacts.py" || return 1
  src="$REPO/ops/launchagents/com.hermes.external-precheck.plist"
  cp "$src" "$EXTERNAL_PRECHECK_LAUNCHAGENT" || return 1
  src="$REPO/ops/launchagents/com.hermes.runtime-retention.plist"
  cp "$src" "$RETENTION_LAUNCHAGENT" || return 1
  src="$REPO/ops/run_daily.py"
  cp "$src" "$NEW_RELEASE/scripts/run_daily.py" || return 1
  cp "$src" "$LIVE/scripts/run_daily.py" || return 1
  chmod +x "$BIN/run_daily.sh" "$BIN/serve_dashboard.sh" "$BIN/refresh_external_precheck.sh" \
    "$NEW_RELEASE/scripts/run_daily.py" "$LIVE/scripts/run_daily.py" \
    2>/dev/null || true
  chmod +x "$BIN/hermes_watchdog.py" || return 1
  chmod +x "$BIN/prune_runtime_artifacts.py" || return 1
  chmod 0644 "$EXTERNAL_PRECHECK_LAUNCHAGENT" "$RETENTION_LAUNCHAGENT" 2>/dev/null || true
}

prepare_shared_runtime() {
  mkdir -p "$RELEASES" "$SHARED_PKG" "$LIVE/data" "$LIVE/reports" "$LIVE/orders" || return 1
  if [ ! -e "$SHARED_PKG/data" ]; then
    [ -d "$LEGACY_PKG/data" ] || return 1
    cp -pR "$LEGACY_PKG/data" "$SHARED_PKG/data" || return 1
  fi
  if [ ! -e "$SHARED_PKG/config" ]; then
    [ -d "$LEGACY_PKG/config" ] || return 1
    cp -pR "$LEGACY_PKG/config" "$SHARED_PKG/config" || return 1
  fi
  [ -d "$SHARED_PKG/data/archive" ] || return 1
}

link_release_runtime() {
  ln -s "$SHARED_PKG/data" "$NEW_PKG/data" || return 1
  ln -s "$SHARED_PKG/config" "$NEW_PKG/config" || return 1
  ln -s "$LIVE/data" "$NEW_RELEASE/data" || return 1
  ln -s "$LIVE/reports" "$NEW_RELEASE/reports" || return 1
  ln -s "$LIVE/orders" "$NEW_RELEASE/orders" || return 1
}

point_symlink() {
  local link="$1"
  local target="$2"
  "$PYTHON" - "$link" "$target" <<'PY'
import os
import pathlib
import sys
link = pathlib.Path(sys.argv[1])
target = pathlib.Path(sys.argv[2])
tmp = link.with_name(f".{link.name}.{os.getpid()}.tmp")
try:
    tmp.unlink()
except FileNotFoundError:
    pass
relative = os.path.relpath(target, link.parent)
os.symlink(relative, tmp)
os.replace(tmp, link)
PY
}

switch_current_release() {
  local old_target=""
  if [ -L "$CURRENT" ]; then
    old_target=$(readlink "$CURRENT") || return 1
  fi
  point_symlink "$CURRENT" "$NEW_RELEASE" || return 1
  if [ -n "$old_target" ]; then
    point_symlink "$PREVIOUS" "$LIVE/$old_target" || return 1
  fi
}

stage_release() {
  rm -rf "$NEW_RELEASE" || return 1
  mkdir -p "$NEW_PKG" || return 1
  sync_code "$NEW_PKG" || return 1
  echo "$HASH $STAMP" > "$NEW_PKG/VERSION" || return 1
  link_release_runtime || return 1
  sync_entries || return 1
}

sync_entries_legacy() {
  local pair src dst
  mkdir -p "$LAUNCHAGENTS_DIR" || return 1
  for pair in \
    "run_daily.sh:$BIN/run_daily.sh" \
    "serve_dashboard.sh:$BIN/serve_dashboard.sh" \
    "refresh_external_precheck.sh:$BIN/refresh_external_precheck.sh" \
    "hermes_watchdog.py:$BIN/hermes_watchdog.py" \
    "prune_runtime_artifacts.py:$BIN/prune_runtime_artifacts.py" \
    "launchagents/com.hermes.external-precheck.plist:$EXTERNAL_PRECHECK_LAUNCHAGENT" \
    "launchagents/com.hermes.runtime-retention.plist:$RETENTION_LAUNCHAGENT" \
    "run_daily.py:$LIVE/scripts/run_daily.py"; do
    src="$REPO/ops/${pair%%:*}"
    dst="${pair##*:}"
    cp "$src" "$dst" || return 1
  done
  chmod +x "$BIN/run_daily.sh" "$BIN/serve_dashboard.sh" "$BIN/refresh_external_precheck.sh" "$LIVE/scripts/run_daily.py" \
    2>/dev/null || true
  chmod +x "$BIN/hermes_watchdog.py" || return 1
  chmod +x "$BIN/prune_runtime_artifacts.py" || return 1
}

run_locked_swap() {
  echo "== 1/7 backup exact live/repo trees + git index =="
  create_backup || die "!! backup failed; partial backup retained: $BACKUP" 1

  echo "== 2/7 prepare shared runtime + stage versioned release =="
  prepare_shared_runtime || fail_locked_swap "!! shared runtime prep failed" 1
  stage_release || fail_locked_swap "!! release staging failed" 1

  echo "== 3/7 staged release ready: $RELEASE_ID =="
  maybe_fail post_sync || fail_locked_swap "!! post-sync validation failed" 1

  echo "== 4/7 config gate (human; runtime data never writes back to repo) =="
  if ! diff -u "$SHARED_PKG/config/config.json" "$REPO/src/hermes_escape_top/config/config.json"; then
    local ans
    read -r -p "Apply repo config to live? [y/N] " ans
    if [ "${ans:-N}" = "y" ]; then
      cp "$REPO/src/hermes_escape_top/config/config.json" "$SHARED_PKG/config/config.json" \
        || fail_locked_swap "!! config apply failed" 1
      echo "  config applied (pre-deploy copy is in backup)"
    else
      echo "  config NOT applied"
    fi
  fi

  echo "== 5/7 smoke staged release + atomic current switch =="
  maybe_fail smoke || fail_locked_swap "!! smoke gate FAIL" 2
  run_import_smoke "$NEW_RELEASE" || fail_locked_swap "!! import broken in staged release" 2
  run_predeploy_smoke "$NEW_RELEASE" || fail_locked_swap "!! smoke gate FAIL" 2
  switch_current_release || fail_locked_swap "!! current symlink switch failed" 2
}

deploy_git_pathspecs() {
  printf '%s\n' \
    ":(glob)skills/investment/escape-top/releases/$RELEASE_ID/hermes_escape_top/**/*.py" \
    "skills/investment/escape-top/releases/$RELEASE_ID/hermes_escape_top/VERSION" \
    "skills/investment/escape-top/releases/$RELEASE_ID/hermes_escape_top/config" \
    "skills/investment/escape-top/releases/$RELEASE_ID/hermes_escape_top/data" \
    "skills/investment/escape-top/releases/$RELEASE_ID/data" \
    "skills/investment/escape-top/releases/$RELEASE_ID/reports" \
    "skills/investment/escape-top/releases/$RELEASE_ID/orders" \
    "skills/investment/escape-top/releases/$RELEASE_ID/scripts/run_daily.py" \
    'skills/investment/escape-top/current' \
    'skills/investment/escape-top/scripts/run_daily.py' \
    'bin/run_daily.sh' \
    'bin/serve_dashboard.sh' \
    'bin/refresh_external_precheck.sh' \
    'bin/hermes_watchdog.py' \
    'bin/prune_runtime_artifacts.py'
  [ -L "$PREVIOUS" ] && printf '%s\n' 'skills/investment/escape-top/previous'
}

stage_deploy_allowlist() {
  local paths=()
  while IFS= read -r path; do
    paths+=("$path")
  done < <(deploy_git_pathspecs)
  # -f: the allowlist is the explicit deploy intent, so force past .hermes/.gitignore
  # (which ignores bin/ and tests/). The :(exclude) pathspecs still keep tests/,
  # data/ and config/ out, so this never re-introduces runtime/sensitive data.
  git -C "$HERMES_HOME" add -f -- "${paths[@]}"
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
  reload_external_precheck_launchagent \
    || die "!! DOUBLE FAILURE: $message; rollback restored plist but external precheck reload failed; dashboard remains stopped; backup: $BACKUP" 90
  reload_runtime_retention_launchagent \
    || die "!! DOUBLE FAILURE: $message; rollback restored plist but runtime retention reload failed; dashboard remains stopped; backup: $BACKUP" 90
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
maybe_fail external_precheck_reload \
  || rollback_after_release "!! external precheck LaunchAgent reload failed" 2
reload_external_precheck_launchagent \
  || rollback_after_release "!! external precheck LaunchAgent reload failed" 2

maybe_fail runtime_retention_reload \
  || rollback_after_release "!! runtime retention LaunchAgent reload failed" 2
reload_runtime_retention_launchagent \
  || rollback_after_release "!! runtime retention LaunchAgent reload failed" 2

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
if [ -f "$CURRENT/hermes_escape_top/VERSION" ]; then
  echo "  dashboard up · live VERSION=$(cat "$CURRENT/hermes_escape_top/VERSION")"
else
  echo "  dashboard up · live VERSION=$(cat "$PKG/VERSION")"
fi
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
