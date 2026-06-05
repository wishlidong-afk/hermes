#!/usr/bin/env bash
set -euo pipefail

cd /Users/liweishi/Documents/github/hermes
mkdir -p logs
export PYTHONPATH="/Users/liweishi/Documents/github/hermes/src"
exec /usr/bin/python3 -u -m hermes_escape_top.cli serve --as-of latest --host 127.0.0.1 --port 8766 >> logs/web_8766_repo.log 2>&1
