# PRODUCTION RUNBOOK（T12 · 2026-06-11）

日常运行、异常处置、人工确认、回滚的固定流程。配套：`OPTIMIZATION_ROADMAP.md`（任务卡）、`FLAG_REGISTRY.md`（实验台账）、`BASELINE_2026_06_11.md`（基线）。

## 1. 正常运行（全自动）

- **06:45 CST** `com.hermes.external-precheck` 全量刷新并验收外部源；**07:05 CST** 同一任务只重试当天失败或 canonical 证据未就绪的源。两次都只写 source ledger 与已验证的 soft_history，不评分、不写官方 run。07:10 daily 若看到完整的当天预检证据会直接复用，避免对 FRED/NAAIM/AAII 连续重复请求。`ready=false` 时弹通知并返回非 0，日志与取证报告在 `~/.hermes/logs/external/`（`external_precheck_latest.{json,md}` 与 `external_precheck_<date>.{json,md}`）。
- **每个自然日 07:10 CST** `com.hermes.daily`（launchd `StartCalendarInterval` 无 `Weekday` 过滤，包含周末/休市日）→ `~/.hermes/bin/run_daily.sh` → live `scripts/run_daily.py` → `python -m hermes_escape_top.scripts.run_daily_package --live --commit-state`。日志：`~/.hermes/logs/daily/daily_<date>.log`。Health 对 OK 回执的 26 小时阈值依赖这个日历日调度事实，与行情的交易日陈旧规则分开。
- daily 的 M4-1a 会再跑一次 `refresh_external --pre-daily-check` 等价链路作为最后保险：FRED/NAAIM/AAII 全源刷新 → AAII/NAAIM 自动尝试最新官方下载文件导入 → source profile SLO 验收。失败不 abort official run，但会写 ledger 并在 8766 health 暴露；评分只使用已验证/已存在的缓存数据。
- scheduled run 结束并写入 OK receipt 后，会落盘 `reports/system_health_<as_of>.json` 与 `.md`：这是运行健康审计快照，区分策略数据、持仓对账、辅助资金流三层；它不是交易指令，交易仍以 official dashboard/daily_report 为准。
- **09:00 CST** `com.hermes.watchdog` → audit_log 落后 >2 个 NYSE 交易日则弹通知。日志：`~/.hermes/logs/watchdog.log`。
- 健康判断三步：① 日志末行 `exit 0`；② preflight 段无 STALE/NOT WRITABLE；③ `[M4-diff]` 段解释今日 vs 昨日变化。
- 手动补跑：`bash ~/.hermes/bin/run_daily.sh`（幂等，非交易日跑了也无害）。

## 2. 数据缺失 / 过期

- preflight 出现 `STALE` 或 watchdog 报警：先手动 `bash ~/.hermes/bin/run_daily.sh`，看 M4-1b 四个刷新步骤哪个 WARNING。
- 外部源统一刷新+验收：`cd ~/.hermes/skills/investment/escape-top/current && PYTHONPATH=. python3 -m hermes_escape_top.scripts.refresh_external --pre-daily-check`。只看 ledger：`--status`。单源刷新：`--source {dollar|real_rate|fred_net_liquidity|naaim_exposure|aaii_sentiment}`。`--all` 默认会在 AAII/NAAIM 自动抓取失败后尝试 `~/Downloads` 内最新官方下载文件导入。
- AAII 403/Imperva：首选一条命令打开官方下载并自动导入新文件：`cd ~/.hermes/skills/investment/escape-top/current && PYTHONPATH=. python3 -m hermes_escape_top.scripts.refresh_external --source aaii_sentiment --open-official-download`。若浏览器无法自动下载，则用已登录浏览器从 AAII Sentiment Survey 页面下载官方 `sentiment.xls`，复制到 `~/.hermes/external_imports/`（LaunchAgent 可读，不依赖 Downloads 权限），再执行 `PYTHONPATH=. python3 -m hermes_escape_top.scripts.refresh_external --source aaii_sentiment --import-file ~/.hermes/external_imports/sentiment.xls`。
- NAAIM 官网 XLSX 发现失败或 2026-08-01 后订阅化：自动抓取仍首选官方 XLSX；失败时可打开官方页等待 workbook 落盘并导入：`PYTHONPATH=. python3 -m hermes_escape_top.scripts.refresh_external --source naaim_exposure --open-official-download`。若需手工下载订阅 workbook，则放入 `~/.hermes/external_imports/` 并执行 `PYTHONPATH=. python3 -m hermes_escape_top.scripts.refresh_external --source naaim_exposure --import-file ~/.hermes/external_imports/naaim.xlsx`。镜像源（如 YCharts/MacroMicro）只用于核对，不直接替代生产真值。
- 旧 `backfill_soft_data --only {naaim|aaii}` 只作为诊断参考；生产刷新以 ExternalSourceRunner ledger 为准。
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
- 脚本先停 dashboard，再由 Python `fcntl` helper **一次 acquire** 同一把 `<archive_dir>/.pipeline.lock`，连续完成：精确目录备份 → 构建 `releases/<hash>_<stamp>/` staging → 共享运行态挂载（`data/`、`reports/`、`orders/`、package `data/config` 不进 release）→ 同步 [`ops/`](../ops/) 入口 → config diff 人工 y/N → staging import/predeploy smoke → `current` symlink 原子切换。整段中间不释放锁，daily、Web refresh、CLI score 都不能插入。
- 真正的持锁边界是 `pipeline_lock_exec` 父进程的单次 `fcntl` lease。内部 `--locked-swap/--locked-rollback` 还会校验继承 FD 与目标 lock 是同一 inode，并用新 OFD 非阻塞抢锁必须得到 `EWOULDBLOCK`；这是防止 agent/人工直接调内部模式的 guardrail，不宣称能对抗拥有本机同用户代码执行权限的恶意调用者。
- smoke 成功后释放部署锁并重启 dashboard；`verify_live` 再按正常事务获取锁。验证仍走真实 `run_daily.sh --deploy-verify` 与新 live 代码，但 `HERMES_DATA_DIR`、日志和 audit/SQLite 指向 APFS 临时隔离副本；它必须产生 `manual_rerun`，不得改官方 receipt/state、live audit、live SQLite、heartbeat 或 live 日志。
- live 运行数据不再反向同步到 repo。需要研究快照时使用显式导出到独立目录；部署本身不修改 repo 的 `data/soft_history`。
- 全部验收通过后，`.hermes` 只提交 allowlist：`current`/`previous` 指针、当前 release 内 package Python（排除 tests/config/data）、`VERSION`、release `scripts/run_daily.py`、稳定入口 `scripts/run_daily.py`、`bin/run_daily.sh`、`bin/serve_dashboard.sh`。SQLite、audit/journal、持仓、order preview、logs/reports、备份、token/key/config 不进入部署 commit。
- 回滚：任何同步、smoke、dashboard、verify 或 `.hermes` commit 失败都会停止 dashboard、重新获取同一把锁，并用隔离备份目录 `~/.hermes-deploy-backups/escape-top/hermes_escape_top.predeploy_backup_<stamp>/` 恢复入口脚本、`current/previous` 指针、共享运行态初始状态和原 git index；如果已切到新 release，则把 `current` 原子切回旧 release 或恢复 legacy 原目录模式；随后重启 dashboard、非零退出，且绝不打印 `deploy OK`。rollback 本身失败会输出 `DOUBLE FAILURE` 与保留的 backup 路径，不自动重试。
- daily 入口：launchd `com.hermes.daily` → `~/.hermes/bin/run_daily.sh` → `~/.hermes/skills/investment/escape-top/current/scripts/run_daily.py`（若 `current` 尚不存在则回退 legacy root），后者经 `python -m hermes_escape_top.scripts.run_daily_package` 跑**唯一的包引擎**。R6 原子化部署后，`HERMES_RUNTIME_ROOT` 指向 `current` release，`HERMES_DATA_DIR` 默认指向 `current/hermes_escape_top`，而 package `data/`、根 `reports/`、`orders/` 再由 release 内 symlink 落到 shared runtime。不要把 daily 的 runtime root 指回稳定 live 根，否则会写入 legacy `escape-top/hermes_escape_top/data`，dashboard 看不到。

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

- 状态：`launchctl print gui/$(id -u)/com.hermes.daily`；外部源预检看 `launchctl print gui/$(id -u)/com.hermes.external-precheck`；手动触发：`launchctl kickstart gui/$(id -u)/com.hermes.<external-precheck|daily>`。
- 停用：`launchctl unload ~/Library/LaunchAgents/com.hermes.<external-precheck|daily|watchdog>.plist`。
- watchdog 节假日表覆盖到 2028，到期告警文本会自带提醒（`~/.hermes/bin/hermes_watchdog.py`）。

> 待办（T12 余项）：health 页面各非绿状态直接链接到本文对应小节（web/render 改动，与 T20 仪表板一起做）。

## 9. 系统验证回归 + 诊断纪律

- **回归脚本**：`HERMES_DATA_DIR=<干净数据根> PYTHONPATH=src python3 scripts/system_validation.py` —— 28 个用例覆盖数据可信/决定性/新鲜度/稳定性/逻辑/配置 byte-identical；结果写 `building/reports/system_validation_report.json`，任一 SYSTEM 用例失败即退出码 1。大改 pipeline/数据层后跑一次。
- **诊断纪律（铁律）**：这台机器的 shell stdout 会严重交错（cwd-reset 伪影），`cat -A`、多行 `echo`、交错的 `print` 都可能显示**假内容**。2026-06-13 我曾据此误判出一个不存在的"完整性闸门只扫首文件"bug。**任何"系统出问题"的判断，必须用 写临时文件 + Read 工具 + 单布尔/单 token 断言 复核，绝不凭 stdout 下结论。** 验证方法本身也要可信。
