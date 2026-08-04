#!/bin/bash
# Build an immutable, hash-addressed Python runtime from requirements.lock.
set -euo pipefail

LOCK_FILE="${1:?usage: bootstrap_runtime.sh REQUIREMENTS_LOCK RUNTIME_PARENT}"
RUNTIME_PARENT="${2:?usage: bootstrap_runtime.sh REQUIREMENTS_LOCK RUNTIME_PARENT}"
UV_BIN="${HERMES_UV_BIN:-$HOME/.local/bin/uv}"
BASE_PYTHON="${HERMES_BASE_PYTHON:-$HOME/.local/bin/python3.11}"

[ -r "$LOCK_FILE" ] || { echo "runtime lock missing: $LOCK_FILE" >&2; exit 64; }
[ -x "$UV_BIN" ] || { echo "uv missing: $UV_BIN" >&2; exit 64; }
[ -x "$BASE_PYTHON" ] || { echo "Python 3.11 missing: $BASE_PYTHON" >&2; exit 64; }

LOCK_SHA="$(shasum -a 256 "$LOCK_FILE" | awk '{print $1}')"
DEST="$RUNTIME_PARENT/$LOCK_SHA"
PY="$DEST/.venv/bin/python"

validate_runtime() {
  "$1" -c 'import ssl, ib_insync, numpy, pandas, scipy, requests, yfinance; assert ssl.OPENSSL_VERSION.startswith("OpenSSL "), ssl.OPENSSL_VERSION'
}

if [ -x "$PY" ]; then
  validate_runtime "$PY" || { echo "immutable runtime is corrupt: $DEST" >&2; exit 65; }
  printf '%s\n' "$PY"
  exit 0
fi
[ ! -e "$DEST" ] || { echo "immutable runtime path exists but is incomplete: $DEST" >&2; exit 65; }

mkdir -p "$RUNTIME_PARENT"
TMP="$RUNTIME_PARENT/.${LOCK_SHA}.$$.tmp"
trap 'rm -rf "$TMP"' EXIT
"$UV_BIN" venv --python "$BASE_PYTHON" "$TMP/.venv" >/dev/null
"$UV_BIN" pip sync --python "$TMP/.venv/bin/python" --require-hashes "$LOCK_FILE" >/dev/null
validate_runtime "$TMP/.venv/bin/python"

"$BASE_PYTHON" - "$TMP" "$DEST" <<'PY'
import os
import sys
os.replace(sys.argv[1], sys.argv[2])
PY
trap - EXIT
printf '%s\n' "$PY"
