#!/bin/bash
# repo -> live deploy (#6 Phase 1): 0-drift code sync, live-entry sync, restart,
# end-to-end acceptance, and AUTO-rollback on any failure — so the script actually
# delivers what CONTRIBUTING claims ("0 drift + restart"). True atomic switch
# (staging dir + symlink flip) is Phase 2, deferred until a concrete trigger (see
# review); the cross-process lock shipped in #3 (core/safe_io.py pipeline_lock).
#
# Flow: guard -> backup -> rsync --delete + VERSION -> entry sync -> soft/config
#       -> smoke -> restart -> accept (curl 200 + verify_live) -> commit.
# Any failure after files change rolls back the code + restarts + exits non-zero.
set -uo pipefail   # NOT -e: failures are handled explicitly so rollback always runs

REPO="$HOME/Documents/github/hermes"
LIVE="$HOME/.hermes/skills/investment/escape-top"
PKG="$LIVE/hermes_escape_top"
BIN="$HOME/.hermes/bin"
STAMP=$(date +%Y%m%d_%H%M%S)
HASH=$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo unknown)
BACKUP="$LIVE/hermes_escape_top.predeploy_backup_$STAMP.tar.gz"

die() { echo "$1" >&2; exit "${2:-1}"; }

rollback() {
  echo "!! ROLLBACK: restoring pre-deploy code ($STAMP)" >&2
  tar -xzf "$BACKUP" -C "$LIVE" 2>/dev/null || echo "  tar restore failed — manual: tar -xzf $BACKUP -C $LIVE" >&2
  [ -f "$BIN/run_daily.sh.bak_$STAMP" ]       && cp "$BIN/run_daily.sh.bak_$STAMP" "$BIN/run_daily.sh"
  [ -f "$BIN/serve_dashboard.sh.bak_$STAMP" ] && cp "$BIN/serve_dashboard.sh.bak_$STAMP" "$BIN/serve_dashboard.sh"
  launchctl kickstart -k "gui/$(id -u)/com.hermes.dashboard" 2>/dev/null || true
}

echo "== 0/7 guard: no daily/refresh run in progress =="
pgrep -f "scripts/run_daily" >/dev/null 2>&1 && die "!! a daily run appears in progress (pgrep run_daily) — aborting deploy." 4
echo "  clear"

echo "== 1/7 backup live code (package minus data + entry scripts) =="
tar --exclude='hermes_escape_top/data' -czf "$BACKUP" -C "$LIVE" hermes_escape_top scripts || die "!! backup failed" 1
cp "$BIN/run_daily.sh"       "$BIN/run_daily.sh.bak_$STAMP"       2>/dev/null || true
cp "$BIN/serve_dashboard.sh" "$BIN/serve_dashboard.sh.bak_$STAMP" 2>/dev/null || true

echo "== 2/7 code rsync repo->live (--delete = true 0-drift; *.py excl tests/config/data) =="
rsync -a --delete --include='*/' --include='*.py' --exclude='*' \
  --exclude='tests/' --exclude='config/' --exclude='data/' \
  "$REPO/src/hermes_escape_top/" "$PKG/" || { rollback; die "!! code rsync failed — rolled back" 1; }
echo "$HASH $STAMP" > "$PKG/VERSION"

echo "== 3/7 sync live-only entry scripts from ops/ =="
for pair in "run_daily.sh:$BIN/run_daily.sh" "serve_dashboard.sh:$BIN/serve_dashboard.sh" "run_daily.py:$LIVE/scripts/run_daily.py"; do
  src="$REPO/ops/${pair%%:*}"; dst="${pair##*:}"
  cp "$src" "$dst" || { rollback; die "!! entry sync failed ($src) — rolled back" 1; }
done
chmod +x "$BIN/run_daily.sh" "$BIN/serve_dashboard.sh" "$LIVE/scripts/run_daily.py" 2>/dev/null || true

echo "== 4/7 soft data live->repo + config gate (human) =="
rsync -a "$PKG/data/soft_history/" "$REPO/src/hermes_escape_top/data/soft_history/" || true
if ! diff -u "$PKG/config/config.json" "$REPO/src/hermes_escape_top/config/config.json"; then
  read -r -p "Apply repo config to live? [y/N] " ans
  if [ "${ans:-N}" = "y" ]; then
    cp "$PKG/config/config.json" "$PKG/config/config.json.bak_$STAMP"
    cp "$REPO/src/hermes_escape_top/config/config.json" "$PKG/config/config.json"
    echo "  config applied (backup .bak_$STAMP)"
  else echo "  config NOT applied"; fi
fi

echo "== 5/7 smoke on live (rollback on fail) =="
( cd "$LIVE" && PYTHONPATH=. /usr/bin/python3 -c "import hermes_escape_top.pipeline" ) \
  || { rollback; die "!! import broken after deploy — rolled back" 2; }
( cd "$LIVE" && PYTHONPATH=. /usr/bin/python3 -m hermes_escape_top.scripts.predeploy_smoke ) \
  || { rollback; die "!! smoke gate FAIL — rolled back" 2; }

echo "== 6/7 restart dashboard + accept =="
launchctl kickstart -k "gui/$(id -u)/com.hermes.dashboard" || { rollback; die "!! dashboard restart failed — rolled back" 2; }
ok=0; for _ in 1 2 3 4 5 6 7 8; do sleep 1; curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8766/ 2>/dev/null | grep -q 200 && { ok=1; break; }; done
[ "$ok" = 1 ] || { rollback; die "!! dashboard not serving 200 after restart — rolled back" 2; }
echo "  dashboard up · live VERSION=$(cat "$PKG/VERSION")"
echo "-- end-to-end: real entry (manual_rerun) effects landed --"
bash "$REPO/ops/verify_live.sh" || { rollback; die "!! verify_live FAIL — real entry broken — rolled back" 3; }

echo "== 7/7 commit in .hermes git =="
git -C "$HOME/.hermes" add skills/investment/escape-top \
  && git -C "$HOME/.hermes" commit --no-verify -m "deploy escape-top @$HASH ($STAMP)" -- skills/investment/escape-top \
  || echo "  NOTE: .hermes commit skipped/failed."
echo "✅ deploy OK @$HASH · backup: $(basename "$BACKUP")"
