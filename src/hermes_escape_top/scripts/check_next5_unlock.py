"""NEXT-5 元模型解锁条件扫描脚本。

每日运行后把结果写到 building/logs/NEXT5_unlock_status.md，
再由 run_daily.py 或手动 git push 同步到 GitHub。
Remote scheduled agent 读取该文件判断是否解锁。

解锁条件 (来自 docs/BUILD_TICKETS.md NEXT-5):
  - 完成20日标签信号 ≥ 300
  - 正样本 (EXIT / DEFENSIVE_EXIT) ≥ 40
  - 覆盖体制 ≥ 2 (至少出现过 LOW_VOL_TREND 和 HIGH_VOL/CRISIS 各一)

Usage:
  python3 -m hermes_escape_top.scripts.check_next5_unlock
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List

HERMES_ROOT   = Path(__file__).resolve().parents[1]
JOURNAL_PATH  = HERMES_ROOT / "data" / "archive" / "signal_journal.jsonl"

# 写到 repo 里，remote agent 才能读到
REPO_ROOT     = Path(__file__).resolve().parents[4]   # ~/.hermes/.../escape-top → repo root 不对
# 尝试找到 hermes repo
_CANDIDATES = [
    Path.home() / "hermes",
    Path("/tmp/hermes-work"),
    Path.home() / "Documents" / "hermes",
]
REPO_STATUS_PATH = None
for c in _CANDIDATES:
    if (c / "building").exists():
        REPO_STATUS_PATH = c / "building" / "logs" / "NEXT5_unlock_status.md"
        break

UNLOCK_LABELS    = 300
UNLOCK_POSITIVE  = 40
UNLOCK_REGIMES   = 2

POSITIVE_STATUSES = {"EXIT", "DEFENSIVE_EXIT"}
REGIME_MAP = {
    "LOW_VOL_TREND":  "bull",
    "NORMAL":         "bull",
    "HIGH_VOL":       "bear",
    "CRISIS":         "bear",
    "CHOP":           "chop",
}


def load_journal(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _load_backtest_regimes() -> Dict[str, str]:
    """Load date→regime mapping from the backtest JSON (best available source)."""
    candidates = [
        HERMES_ROOT / "reports" / "Backtest_FULL.json",
        HERMES_ROOT / "reports" / "Backtest_FULL_2018_2026.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                data = json.loads(p.read_text())
                out = {}
                for r in data.get("rows", []):
                    reg = r.get("regime", "")
                    # regime may be a dict {"current": "..."} or a plain string
                    if isinstance(reg, dict):
                        reg = reg.get("current", "")
                    out[str(r.get("date", ""))] = str(reg)
                return out
            except Exception:
                continue
    return {}


def scan() -> Dict[str, Any]:
    entries = load_journal(JOURNAL_PATH)

    # IMPORTANT: dedupe by (date, symbol) so re-running the pipeline on the same
    # day does NOT inflate the label count. A meta-model needs DISTINCT signals
    # across time, not duplicate copies of one day.
    seen_keys = {}
    for e in entries:
        dt  = str(e.get("as_of", e.get("date", "")))
        sym = str(e.get("symbol", ""))
        if not dt:
            continue
        seen_keys[(dt, sym)] = e   # last write wins for a given (date, symbol)

    unique = list(seen_keys.values())
    raw_total = len(entries)
    total    = len(unique)
    positive = sum(1 for e in unique if e.get("status") in POSITIVE_STATUSES)

    # Regime coverage: join distinct-signal dates with backtest regime map
    regime_map = _load_backtest_regimes()
    regimes_seen = set()
    for e in unique:
        dt = str(e.get("as_of", e.get("date", "")))
        reg = e.get("regime") or regime_map.get(dt, "")
        if reg in REGIME_MAP:
            regimes_seen.add(REGIME_MAP[reg])
    n_regimes = len(regimes_seen)

    distinct_dates = len({k[0] for k in seen_keys})

    unlocked = (
        total    >= UNLOCK_LABELS   and
        positive >= UNLOCK_POSITIVE and
        n_regimes >= UNLOCK_REGIMES
    )

    # Oldest and newest distinct signal dates
    dates = sorted({k[0] for k in seen_keys if k[0]})

    return {
        "scanned_at":    datetime.utcnow().isoformat() + "Z",
        "journal_path":  str(JOURNAL_PATH),
        "journal_exists": JOURNAL_PATH.exists(),
        "total_labels":  total,
        "raw_journal_rows": raw_total,
        "distinct_dates": distinct_dates,
        "positive_samples": positive,
        "regimes_seen":  sorted(regimes_seen),
        "n_regimes":     n_regimes,
        "date_range":    [dates[0], dates[-1]] if len(dates) >= 2 else dates,
        "unlocked":      unlocked,
        "conditions": {
            "labels_ok":   total    >= UNLOCK_LABELS,
            "positive_ok": positive >= UNLOCK_POSITIVE,
            "regimes_ok":  n_regimes >= UNLOCK_REGIMES,
        },
        "thresholds": {
            "labels":   UNLOCK_LABELS,
            "positive": UNLOCK_POSITIVE,
            "regimes":  UNLOCK_REGIMES,
        },
    }


def write_status(result: Dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    c = result["conditions"]
    t = result["thresholds"]
    emoji = "🟢" if result["unlocked"] else "🔴"

    lines = [
        f"# NEXT-5 元模型解锁状态",
        f"",
        f"**更新时间**: {result['scanned_at']}  ",
        f"**状态**: {emoji} {'**已解锁 — 可启动元模型训练**' if result['unlocked'] else '未解锁（条件未达）'}",
        f"",
        f"## 条件检查",
        f"",
        f"| 条件 | 当前值 | 门控 | 状态 |",
        f"|---|---:|---:|---|",
        f"| 总标签数 | {result['total_labels']} | ≥ {t['labels']} | {'✅' if c['labels_ok'] else '❌ 差 ' + str(t['labels'] - result['total_labels']) + ' 个'} |",
        f"| 正样本 (EXIT/DEF_EXIT) | {result['positive_samples']} | ≥ {t['positive']} | {'✅' if c['positive_ok'] else '❌ 差 ' + str(t['positive'] - result['positive_samples']) + ' 个'} |",
        f"| 覆盖体制数 | {result['n_regimes']} ({', '.join(result['regimes_seen']) or '无'}) | ≥ {t['regimes']} | {'✅' if c['regimes_ok'] else '❌'} |",
        f"",
        f"## 数据来源",
        f"",
        f"- signal_journal: `{result['journal_path']}`",
        f"- 文件存在: {result['journal_exists']}",
        f"- journal 原始行数: {result.get('raw_journal_rows', '?')}（含重复运行）",
        f"- **去重后不同(日期,标的)信号: {result['total_labels']}**",
        f"- 不同交易日数: {result.get('distinct_dates', '?')}",
        f"- 信号日期范围: {result['date_range']}",
        f"",
        f"> 注：解锁门按去重后的不同信号计数，反复运行同一天不刷标签。",
        f"",
    ]
    if result["unlocked"]:
        lines += [
            f"## ✅ 解锁操作",
            f"",
            f"条件已全部满足，可以启动 NEXT-5 元模型训练：",
            f"",
            f"```bash",
            f"python3 -m hermes_escape_top.scripts.train_meta_model  # 待实现",
            f"```",
            f"",
            f"训练前请确认：",
            f"- [ ] purged CV 划分正确（无前视）",
            f"- [ ] 正样本覆盖至少 2 个体制",
            f"- [ ] 测试集不入训练",
            f"",
        ]
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    result = scan()

    print(f"=== NEXT-5 解锁扫描 {result['scanned_at']} ===")
    print(f"总标签: {result['total_labels']}/{result['thresholds']['labels']}  "
          f"正样本: {result['positive_samples']}/{result['thresholds']['positive']}  "
          f"体制: {result['n_regimes']}/{result['thresholds']['regimes']}")
    print(f"状态: {'🟢 UNLOCKED' if result['unlocked'] else '🔴 LOCKED'}")

    if REPO_STATUS_PATH:
        write_status(result, REPO_STATUS_PATH)
        print(f"→ 状态写入: {REPO_STATUS_PATH}")
    else:
        print("⚠ 未找到 hermes repo，状态未写入文件")

    # 返回 exit code 0 = 未解锁，1 = 已解锁（方便脚本判断）
    import sys
    sys.exit(0 if not result["unlocked"] else 1)


if __name__ == "__main__":
    main()
