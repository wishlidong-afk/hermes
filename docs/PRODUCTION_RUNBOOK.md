# PRODUCTION RUNBOOK（T12 · 2026-06-11）

日常运行、异常处置、人工确认、回滚的固定流程。配套：`OPTIMIZATION_ROADMAP.md`（任务卡）、`FLAG_REGISTRY.md`（实验台账）、`BASELINE_2026_06_11.md`（基线）。

## 1. 正常运行（全自动）

- **每个自然日 07:10 CST** `com.hermes.daily`（launchd `StartCalendarInterval` 无 `Weekday` 过滤，包含周末/休市日）→ `~/.hermes/bin/run_daily.sh` → live `scripts/run_daily.py` → `python -m hermes_escape_top.scripts.run_daily_package --live --commit-state`。日志：`~/.hermes/logs/daily/daily_<date>.log`。Health 对 OK 回执的 26 小时阈值依赖这个日历日调度事实，与行情的交易日陈旧规则分开。
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

- `bash scripts/deploy_to_live.sh`。部署开始会短暂停止 8766；这是为避免 dashboard 在同步中途惰性 import 到半套代码，通常只持续 smoke 与重启所需时间。
- 脚本先停 dashboard，再由 Python `fcntl` helper **一次 acquire** 同一把 `<archive_dir>/.pipeline.lock`，连续完成：精确目录备份 → `rsync --delete` 仓库代码到 live → 写 `VERSION` → 同步 [`ops/`](../ops/) 入口 → config diff 人工 y/N → import/predeploy smoke。整段中间不释放锁，daily、Web refresh、CLI score 都不能插入。
- 真正的持锁边界是 `pipeline_lock_exec` 父进程的单次 `fcntl` lease。内部 `--locked-swap/--locked-rollback` 还会校验继承 FD 与目标 lock 是同一 inode，并用新 OFD 非阻塞抢锁必须得到 `EWOULDBLOCK`；这是防止 agent/人工直接调内部模式的 guardrail，不宣称能对抗拥有本机同用户代码执行权限的恶意调用者。
- smoke 成功后释放部署锁并重启 dashboard；`verify_live` 再按正常事务获取锁。验证仍走真实 `run_daily.sh --deploy-verify` 与新 live 代码，但 `HERMES_DATA_DIR`、日志和 audit/SQLite 指向 APFS 临时隔离副本；它必须产生 `manual_rerun`，不得改官方 receipt/state、live audit、live SQLite、heartbeat 或 live 日志。
- live 运行数据不再反向同步到 repo。需要研究快照时使用显式导出到独立目录；部署本身不修改 repo 的 `data/soft_history`。
- 全部验收通过后，`.hermes` 只提交 allowlist：package Python（排除 tests/config/data）、`VERSION`、`scripts/run_daily.py`、`bin/run_daily.sh`、`bin/serve_dashboard.sh`。SQLite、audit/journal、持仓、order preview、logs/reports、备份、token/key/config 不进入部署 commit。
- 回滚：任何同步、smoke、dashboard、verify 或 `.hermes` commit 失败都会停止 dashboard、重新获取同一把锁，并用隔离备份目录 `~/.hermes-deploy-backups/escape-top/hermes_escape_top.predeploy_backup_<stamp>/` 配合 `rsync --delete` 恢复精确文件集合、内容、权限、VERSION、入口脚本和原 git index；随后重启 dashboard、非零退出，且绝不打印 `deploy OK`。rollback 本身失败会输出 `DOUBLE FAILURE` 与保留的 backup 路径，不自动重试。
- 目前仍是第一阶段的原目录精确切换；versioned release + symlink 原子切换需在本阶段稳定观察 3 个交易日后另行实施。
- daily 入口：launchd `com.hermes.daily` → `~/.hermes/bin/run_daily.sh` → `run_daily.py`，后者经 `python -m hermes_escape_top.scripts.run_daily_package` 跑**唯一的包引擎**（2026-06-17 起，旧的 standalone loose 副本已退役；`_discover_runtime_paths` 向上定位包，所以 `-m` 能从任意深度解析）。这些 live-only 入口/调度脚本的版本化副本在 [`ops/`](../ops/)。

### 7.1 已登记的一次性 live 权限维护

- 2026-06-19 只读盘点：live `data/` 共 68 个 CSV，49 个为 `0600`、19 个为 `0644`；repo 对应 CSV 全部为 `0644`。这是旧 `mkstemp + os.replace` 留下的权限漂移，不是当前运行故障（live 进程与文件同用户）。
- 新 `atomic_write_csv` 会保留已有 mode，不再制造新漂移，但不会自动修正历史文件。在真实部署窗口中先导出 path/mode 清单，再将 live `data/history/*.csv` 和 `data/soft_history/*.csv` 统一为 `0644`，最后复核文件数、SHA256 与 dashboard/daily 可读性。该操作不得在普通 code review 中静默执行。

## 7.5 仪表板服务（com.hermes.dashboard）

- 8766 由 launchd 常驻托管（开机自启 + 崩溃自拉起），入口 `~/.hermes/bin/serve_dashboard.sh`。
- **从 LIVE 包服务，不是 repo**：launchd agent 无 `~/Documents` 的 TCC 授权（repo-served 模式下会 `Operation not permitted` 且 NO_CACHE）；且操作台应跟随部署版本而非 repo 半成品。**代码改动经 `deploy_to_live.sh` 才会出现在 8766**。
- 数据根=live（`HERMES_DATA_DIR` 指向 live 包），显示的是当日真实决策。
- 威胁模型：8766 只绑定 loopback，所有 POST 都校验本机 Host/Origin。`/api/m4_golive` 和 `/api/confirm_execution` 会改变生产行为/决策状态，额外要求 `HERMES_CONFIRM_TOKEN`；数据刷新、重算和只读检查端点仅限 loopback。锁冲突返回 409，不并发执行。
- 禁止将当前鉴权模式直接用在非 loopback/反向代理场景；如需对外暴露，必须先将全部 mutating POST 升级为 token 鉴权并重新审核 CSRF 与代理信任边界。
- 排障：`tail ~/.hermes/logs/dashboard.err.log`；重启 `launchctl kickstart -k gui/$(id -u)/com.hermes.dashboard`。

## 8. launchd 维护

- 状态：`launchctl print gui/$(id -u)/com.hermes.daily`；手动触发：`launchctl kickstart gui/$(id -u)/com.hermes.daily`。
- 停用：`launchctl unload ~/Library/LaunchAgents/com.hermes.<daily|watchdog>.plist`。
- watchdog 节假日表覆盖到 2028，到期告警文本会自带提醒（`~/.hermes/bin/hermes_watchdog.py`）。

> 待办（T12 余项）：health 页面各非绿状态直接链接到本文对应小节（web/render 改动，与 T20 仪表板一起做）。

## 9. 系统验证回归 + 诊断纪律

- **回归脚本**：`HERMES_DATA_DIR=<干净数据根> PYTHONPATH=src python3 scripts/system_validation.py` —— 28 个用例覆盖数据可信/决定性/新鲜度/稳定性/逻辑/配置 byte-identical；结果写 `building/reports/system_validation_report.json`，任一 SYSTEM 用例失败即退出码 1。大改 pipeline/数据层后跑一次。
- **诊断纪律（铁律）**：这台机器的 shell stdout 会严重交错（cwd-reset 伪影），`cat -A`、多行 `echo`、交错的 `print` 都可能显示**假内容**。2026-06-13 我曾据此误判出一个不存在的"完整性闸门只扫首文件"bug。**任何"系统出问题"的判断，必须用 写临时文件 + Read 工具 + 单布尔/单 token 断言 复核，绝不凭 stdout 下结论。** 验证方法本身也要可信。
