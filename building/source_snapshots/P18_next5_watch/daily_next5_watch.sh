#!/bin/bash
# NEXT-5 元模型解锁守望 — 每日定时任务
#
# 1. 跑 score_pipeline 积累当天信号（写入 signal_journal）
# 2. 扫描 NEXT-5 解锁条件，写状态到 hermes repo
# 3. 解锁时弹 macOS 通知
# 4. 把状态文件 push 到 GitHub（远程可查）
#
# 挂到 cron：每个交易日北京时间收盘后跑一次。

set -uo pipefail

SKILL_DIR="$HOME/.hermes/skills/investment/escape-top"
REPO_DIR="$HOME/hermes"
LOG="$SKILL_DIR/hermes_escape_top/data/archive/next5_watch.log"
TODAY=$(date +%Y-%m-%d)

cd "$SKILL_DIR" || exit 1

{
  echo "===== NEXT-5 watch $(date '+%Y-%m-%d %H:%M:%S') ====="

  # 1. 跑当天 pipeline 积累信号（非交易日会复用最近收盘，不报错即可）
  python3 -m hermes_escape_top.pipeline "$TODAY" 2>/dev/null \
    || python3 -c "from hermes_escape_top.pipeline import score_pipeline; score_pipeline('$TODAY')" 2>/dev/null \
    || echo "pipeline run skipped ($TODAY may be non-trading day)"

  # 2. 扫描解锁条件
  python3 -m hermes_escape_top.scripts.check_next5_unlock
  UNLOCK_CODE=$?

  # 3. 如果解锁（exit code 1），弹通知
  if [ "$UNLOCK_CODE" -eq 1 ]; then
    osascript -e 'display notification "NEXT-5 元模型解锁条件已满足！可以启动训练。" with title "Hermes 逃顶系统" sound name "Glass"' 2>/dev/null
    echo "🟢 UNLOCKED — notification sent"
  else
    echo "🔴 still locked"
  fi

  # 4. push 状态到 GitHub（如果 repo 存在且有变化）
  if [ -d "$REPO_DIR/.git" ]; then
    cd "$REPO_DIR" || exit 0
    if ! git diff --quiet building/logs/NEXT5_unlock_status.md 2>/dev/null; then
      git add building/logs/NEXT5_unlock_status.md
      git commit -m "[NEXT-5] daily unlock scan $TODAY" --quiet 2>/dev/null
      git push origin hermes-docs --quiet 2>/dev/null && echo "pushed to GitHub" || echo "push skipped"
    fi
  fi

  echo ""
} >> "$LOG" 2>&1
