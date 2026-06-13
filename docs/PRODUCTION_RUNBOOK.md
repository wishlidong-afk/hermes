# PRODUCTION RUNBOOK（T12 · 2026-06-11）

日常运行、异常处置、人工确认、回滚的固定流程。配套：`OPTIMIZATION_ROADMAP.md`（任务卡）、`FLAG_REGISTRY.md`（实验台账）、`BASELINE_2026_06_11.md`（基线）。

## 1. 正常运行（全自动）

- **07:10 CST** `com.hermes.daily`（launchd）→ `~/.hermes/bin/run_daily.sh` → live `run_daily_package.py --live --commit-state`。日志：`~/.hermes/logs/daily/daily_<date>.log`。
- **09:00 CST** `com.hermes.watchdog` → audit_log 落后 >2 个 NYSE 交易日则弹通知。日志：`~/.hermes/logs/watchdog.log`。
- 健康判断三步：① 日志末行 `exit 0`；② preflight 段无 STALE/NOT WRITABLE；③ `[M4-diff]` 段解释今日 vs 昨日变化。
- 手动补跑：`bash ~/.hermes/bin/run_daily.sh`（幂等，非交易日跑了也无害）。

## 2. 数据缺失 / 过期

- preflight 出现 `STALE` 或 watchdog 报警：先手动 `bash ~/.hermes/bin/run_daily.sh`，看 M4-1b 四个刷新步骤哪个 WARNING。
- 单源手动刷新：`cd ~/.hermes/skills/investment/escape-top && PYTHONPATH=. python3 -m hermes_escape_top.scripts.backfill_soft_data --only {fred|fred_risk|naaim|cot|aaii}`。
- AAII 403：需会员会话，走 Claude-in-Chrome 抓取流程（记忆/历史会话有步骤），Thursday 约定追加 CSV。
- 缺数据≠安全：`use_soft_data_max_age` 翻闸后超龄源自动走 missing_weight（当前 OFF，翻闸见 §6）。

## 3. Suspect valve PENDING

- 含义：坏 tick 嫌疑日，硬阀门降级为 PENDING 等次日干净收盘确认（`use_suspect_valve_guard=true` 已部署）。
- 处置：不动作。次日确认仍触发→正常 100% EXIT；解除→恢复。连续 2 天 PENDING 才需人工查源数据（`data_quality_audit.py`）。

## 4. IBKR 只读连接失败

- 影响：仅持仓对账缺失（payload `ibkr` 块），评分/建议不受影响。
- 处置：确认 TWS/Gateway 在跑、端口对；红线检查 `config.ibkr.readonly` 必须 true（preflight 违规会直接 abort live 运行）。

## 5. 回测 / gate 失败

- 单变体独立进程跑（同进程多回测 OOM）；用 `HERMES_DATA_DIR` 指向隔离数据副本，绝不直接读写包内 data/。
- gate FAIL = 正常产出：flag 保持 OFF，失败原因归档进 FLAG_REGISTRY Rejected 区，**不二次调参**。

## 6. Flag 翻闸（人工门，固定仪式）

1. byte-identical（OFF）证明 + gate/no-op 证据齐备；2. FLAG_REGISTRY 写卡（假设/证据/回滚）；3. 改 repo config → `scripts/deploy_to_live.sh` 走 config diff y/n；4. 次日对比 post-run diff 确认行为符合预期。
- **回滚**：flag → false（config 同步 live），一律一步可逆。当前待翻闸：`use_soft_data_max_age`、`use_full_confidence_spine`（均需先跑一次全窗口 no-op 确认）。

## 7. 部署 repo → live

- `bash scripts/deploy_to_live.sh`：备份 tarball → 代码 rsync（加性）→ 软数据 live→repo 反向同步 → config diff 人工 y/n → import+决策对比 → .hermes git commit。
- 回滚：解 `predeploy_backup_<stamp>.tar.gz`。
- 注意：live `scripts/run_daily_package.py`（standalone）有本地补丁，不在 rsync 范围内，改它需人工对比合入。

## 7.5 仪表板服务（com.hermes.dashboard）

- 8766 由 launchd 常驻托管（开机自启 + 崩溃自拉起），入口 `~/.hermes/bin/serve_dashboard.sh`。
- **从 LIVE 包服务，不是 repo**：launchd agent 无 `~/Documents` 的 TCC 授权（repo-served 模式下会 `Operation not permitted` 且 NO_CACHE）；且操作台应跟随部署版本而非 repo 半成品。**代码改动经 `deploy_to_live.sh` 才会出现在 8766**。
- 数据根=live（`HERMES_DATA_DIR` 指向 live 包），显示的是当日真实决策。
- 排障：`tail ~/.hermes/logs/dashboard.err.log`；重启 `launchctl kickstart -k gui/$(id -u)/com.hermes.dashboard`。

## 8. launchd 维护

- 状态：`launchctl print gui/$(id -u)/com.hermes.daily`；手动触发：`launchctl kickstart gui/$(id -u)/com.hermes.daily`。
- 停用：`launchctl unload ~/Library/LaunchAgents/com.hermes.<daily|watchdog>.plist`。
- watchdog 节假日表覆盖到 2028，到期告警文本会自带提醒（`~/.hermes/bin/hermes_watchdog.py`）。

> 待办（T12 余项）：health 页面各非绿状态直接链接到本文对应小节（web/render 改动，与 T20 仪表板一起做）。

## 9. 系统验证回归 + 诊断纪律

- **回归脚本**：`HERMES_DATA_DIR=<干净数据根> PYTHONPATH=src python3 scripts/system_validation.py` —— 28 个用例覆盖数据可信/决定性/新鲜度/稳定性/逻辑/配置 byte-identical；结果写 `building/reports/system_validation_report.json`，任一 SYSTEM 用例失败即退出码 1。大改 pipeline/数据层后跑一次。
- **诊断纪律（铁律）**：这台机器的 shell stdout 会严重交错（cwd-reset 伪影），`cat -A`、多行 `echo`、交错的 `print` 都可能显示**假内容**。2026-06-13 我曾据此误判出一个不存在的"完整性闸门只扫首文件"bug。**任何"系统出问题"的判断，必须用 写临时文件 + Read 工具 + 单布尔/单 token 断言 复核，绝不凭 stdout 下结论。** 验证方法本身也要可信。
