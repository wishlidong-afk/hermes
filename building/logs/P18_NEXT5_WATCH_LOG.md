# P18 NEXT-5 元模型解锁守望（每日定时任务）

**时间**: 2026-06-02  
**范围**: 建立每日自动扫描 NEXT-5 元模型解锁条件的定时任务，达标时通知用户  
**机制**: macOS launchd LaunchAgent（独立运行，重启存活，几个月无需 Claude 开着）

---

## 关键修正：去重计数（防刷标签）

扫描 signal_journal 时**按 (日期, 标的) 去重**。原始 journal 有 3708 行，但都是反复运行 `2026-05-29` 同一天的副本——去重后只有 **6 个真实不同信号**（2 个交易日 × 3 标的）。

> 这是个真实的逻辑漏洞修复：否则反复跑 pipeline 就能刷满 300 个假标签，元模型会在虚假样本上训练。

---

## 当前真实状态

| 条件 | 当前值 | 门控 | 状态 |
|---|---:|---:|---|
| 不同信号数 | 6 | ≥ 300 | ❌ 差 294 |
| 正样本 (EXIT/DEF_EXIT) | 2 | ≥ 40 | ❌ 差 38 |
| 覆盖体制数 | 1 (bull) | ≥ 2 | ❌ |

**结论**: 元模型远未解锁。每个交易日积累 3 个新信号，需要约 **100 个交易日（~5 个月）** 攒够 300 个，且正样本依赖市场真实出现逃顶信号。

---

## 交付物

| 文件 | 作用 |
|---|---|
| `scripts/check_next5_unlock.py` | 扫描器：去重计数 + 体制覆盖 + 写状态文件 + exit code（0=锁/1=解锁） |
| `scripts/daily_next5_watch.sh` | 每日 runner：跑 pipeline → 扫描 → 解锁时 macOS 通知 → push 状态到 GitHub |
| `~/Library/LaunchAgents/com.hermes.next5watch.plist` | launchd 定时器：工作日 18:33 北京时间触发 |
| `building/logs/NEXT5_unlock_status.md` | 每日刷新的状态文件（GitHub 可查） |

---

## 调度配置

- **触发时间**: 工作日（周一~五）北京时间 18:33
- **为何傍晚**: 此时美股前一交易日已收盘（美东 16:00 ≈ 北京次日凌晨），数据已就绪；傍晚机器大概率醒着
- **睡眠补跑**: launchd `StartCalendarInterval` 在机器醒来后补跑错过的任务
- **通知方式**: 解锁时 `osascript` 弹 macOS 通知（带 Glass 提示音）
- **远程可查**: 状态文件每日 push 到 GitHub `hermes-docs` 分支

---

## 验证

- 手动 `launchctl start com.hermes.next5watch` → 任务跑通，状态文件刷新 ✅
- `launchctl list | grep hermes` → `com.hermes.next5watch` 已加载 ✅
- plist `plutil -lint` → OK ✅

---

## 管理命令

```bash
# 查看是否在运行
launchctl list | grep hermes

# 手动触发一次
launchctl start com.hermes.next5watch

# 停止/卸载
launchctl unload ~/Library/LaunchAgents/com.hermes.next5watch.plist

# 重新加载（改了 plist 后）
launchctl load ~/Library/LaunchAgents/com.hermes.next5watch.plist

# 看历史日志
tail -50 ~/.hermes/skills/investment/escape-top/hermes_escape_top/data/archive/next5_watch.log
```

---

## 状态

P18: **DONE** — 每日解锁守望已上线运行。解锁条件满足时自动弹通知 + push GitHub。
