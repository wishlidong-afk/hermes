# PRODUCTION RUNBOOK（T12 · 2026-06-11）

日常运行、异常处置、人工确认、回滚的固定流程。配套：`OPTIMIZATION_ROADMAP.md`（任务卡）、`FLAG_REGISTRY.md`（实验台账）、`BASELINE_2026_06_11.md`（基线）。

## 1. 正常运行（全自动）

- **06:45 CST** `com.hermes.external-precheck` 只刷新并验收 `decision` 通道；**07:05 CST** 同一任务只重试当天失败或 canonical 证据未就绪的决策源。禁用、inactive、auxiliary 与 research 源不进这两次早间请求。两次都只写 source ledger 与已验证的 canonical，不评分、不写官方 run。07:10 daily 若看到完整的当天预检证据会直接复用，避免对 FRED/AAII 连续重复请求。NAAIM 自 2026-08-01 标记为 `RETIRED_PAYWALL`，仅在周五上海时间做一次官方访问探测，非探测日不请求，也不迫使 07:10 补跑第三次。`ready=false` 时弹通知并返回非 0。`external_precheck_latest.{json,md}` 与 `external_precheck_<date>.{json,md}` 是原子更新的兼容视图；每次运行另保留不可变的 `external_precheck_<date>_<timestamp>_<mode>_<pid>.{json,md}`，06:45 与 07:05 不互相覆盖。
- **每个自然日 07:10 CST** `com.hermes.daily`（launchd `StartCalendarInterval` 无 `Weekday` 过滤，包含周末/休市日）→ `~/.hermes/bin/run_daily.sh --scheduled-launchd` → live `scripts/run_daily.py` → `python -m hermes_escape_top.scripts.run_daily_package --live --commit-state --run-type scheduled`。无参数手工执行同一 wrapper 时固定为 `manual_rerun`，不能写官方 receipt 或冒充自然调度。日志：`~/.hermes/logs/daily/daily_<date>.log`。Health 对 OK 回执的 26 小时阈值依赖这个日历日调度事实，与行情的交易日陈旧规则分开。
- daily 的 M4-1a 优先复用当天 06:45/07:05 的完整 ledger 证据；只有当天决策源证据不完整时才补跑 `decision` 通道 ExternalSourceRunner。它不会因 COT flag OFF、inactive OCC、research BTC funding 或 auxiliary VIX9D 再发起早间请求。AAII 结果页被 Imperva 阻断或结构变化时会转用 AAII 官方 Insights RSS，RSS 也失败后才尝试未被 ledger 消费过的官方下载文件。AAII/NAAIM 文件先按 SHA-256 进入 `external_import_queue/<source>/{inbox,processed,rejected}`，原始 Downloads 文件不移动，同内容不重复处理。每次 run 的 raw/normalized 路径与 `external_sources/blobs/sha256/` 认证 blob 是不同 inode 的只读副本；篡改单次副本不会污染 blob 或其它 run。失败不 abort official run，但会写 ledger 并在 8766 health 暴露；评分只使用已验证/已存在的 canonical 缓存。
- scheduled run 结束并写入 OK receipt 后，会落盘 `reports/system_health_<as_of>.json` 与 `.md`：这是运行健康审计快照，区分策略数据、持仓对账、辅助资金流三层；每份新报告绑定 `generator_release_hash` 与 `generator_policy_sha256`，并以 `generated_at` 证明它是否晚于当前 R6 attestation。它不是交易指令，交易仍以 official dashboard/daily_report 为准。
- **09:00 CST** `com.hermes.watchdog` → audit_log 落后 >2 个 NYSE 交易日则弹通知。日志：`~/.hermes/logs/watchdog.log`。
- **09:02 CST** `com.hermes.market-third-source` 在共享 pipeline lock 下只重试最新 market-admission operation 的 Alpha Vantage 第三源 shadow，解决 07:10 时供应商尚未发布最新日线的问题；锁忙返回 `BUSY`，不并发写入。它不修改 canonical history、准入状态、评分、官方回执或 `input_hash`；8766 仅在 `admission_operation_id` 与 `completed_through` 同时匹配时展示该延迟证据。日志：`~/.hermes/logs/market_third_source.launchd.{out,err}.log`。
- **09:10 CST** Codex heartbeat 只读运行 `ops/morning_acceptance.py`，位于 09:00 watchdog 和 09:02 延迟证据之后；不得借验收触发 daily、行情/外部源刷新或 IBKR 连接。退出码 `0=PASS`、`2=FAIL`、`3=PENDING_POST_DEPLOY`。后者只在 runtime 五项完整、旧官方报告本身有效、当前策略 readiness 为 OK，且当前 release 尚未获得“部署后下一个 07:10 调度点及其后”的同 release/policy 报告时出现；它不授权交易或下一次部署。8766 显示“策略待认证 / WAIT”，下一次自然 07:10 scheduled run 是唯一自动转回 PASS 的路径，禁止覆盖旧报告或无参数手工预览来制造认证。
- **09:20 CST** `com.hermes.external-shadow` 以非阻塞锁刷新 `shadow` 通道：active research BTC funding/basis 会调度；auxiliary VIX9D 仅在 `use_cboe_official_indices` 开启时加入。本任务不会暗中翻 flag。VIX9D 若推进受控 `history/` canonical，任务会在同一把 pipeline lock 内先核对晋升 SHA 和唯一允许的 drift，再跑行情完整性扫描并重冻结 data manifest；任一检查失败都保持 DRIFT、写失败证据并以非零状态退出。锁忙原样返回 75，结果保存在 `~/.hermes/logs/external-shadow/external_shadow_{<date>_<timestamp>_<pid>|latest}.json`；shadow 更新不追溯改写当日 07:10 的策略 readiness、评分、路由、官方回执或 `input_hash`。
- **每周日 08:30 CST** `com.hermes.runtime-retention` 在同一把非阻塞 pipeline lock 下清理超出保留策略的旧 release、部署备份、压缩 audit 与已结束评分事务；`current`、`previous` 和 active transaction 永不删除。锁忙则记录 `BUSY` 并零删除，证据在 `~/.hermes/logs/retention/runtime_retention_{<date>|latest}.json`。
- 健康判断三步：① 日志末行 `exit 0`；② preflight 段无 STALE/NOT WRITABLE；③ `[M4-diff]` 段解释今日 vs 昨日变化。
- 手工诊断预览：`bash ~/.hermes/bin/run_daily.sh`。它固定写 `manual_rerun`，不替代官方 07:10 run、不写官方 receipt、也不能完成部署再认证。需要恢复官方调度时按事故流程显式运行 `launchctl kickstart -k gui/$UID/com.hermes.daily`，并保留人工授权与日志证据。

## 2. 数据缺失 / 过期

- preflight 出现 `STALE` 或 watchdog 报警：先运行 `~/.hermes/bin/refresh_external.sh --pre-daily-check` 查看决策源证据；需要完整链路诊断时再运行 `bash ~/.hermes/bin/run_daily.sh` 生成非官方 `manual_rerun` 预览。不要把预览当成官方恢复。
- 决策外部源统一刷新+验收：`~/.hermes/bin/refresh_external.sh --pre-daily-check`（默认 `decision`）。手动只刷新影子通道：`~/.hermes/bin/refresh_external.sh --all --lane shadow --lock-timeout 0`。只看 ledger：`~/.hermes/bin/refresh_external.sh --status`。单源刷新：`~/.hermes/bin/refresh_external.sh --source {dollar|real_rate|fred_net_liquidity|cboe_equity_pcr|cot_nq|occ_equity_pcr|btc_funding_basis|naaim_exposure|aaii_sentiment}`，显式 `--source` 不受自动调度分通道限制。该稳定入口按 live `RUNTIME_LOCK_SHA256` 选择 managed Python，不使用 shell 的 ambient `python3`。`--all` 默认会在 AAII/NAAIM 自动抓取失败后尝试尚未被 ledger 消费过的官方下载文件；同一文件哈希不会反复导入。
- AAII 403/Imperva：runner 会自动尝试 AAII 官方 `https://insights.aaii.com/feed`，从每周 Sentiment Survey 正文解析同一组 Bullish/Neutral/Bearish 数值，并在 raw/ledger 记录 RSS URL、XML SHA-256 和实际 artifact `pubDate`；RSS 路径以该 `pubDate` 作为 PIT 可用日，不回填到更早的周四。这是官方自动化 fallback，不是第三方镜像。只有结果页与 RSS 都失败时，才运行 `~/.hermes/bin/refresh_external.sh --source aaii_sentiment --open-official-download`。若浏览器无法自动下载，则用已登录浏览器下载官方 `sentiment.xls`，复制到 `~/.hermes/external_imports/`，再执行 `~/.hermes/bin/refresh_external.sh --source aaii_sentiment --import-file ~/.hermes/external_imports/sentiment.xls`。
- NAAIM 公共 XLSX 自 2026-08-01 起付费退役：不购买时无需人工刷新。最后一份认证 canonical 与 ledger 保持冻结；超龄后评分按既有 `use_soft_data_max_age`/missing_weight 处理。周五探测失败只记运维告警，不把结构性不可用误报成 daily 故障；`EVIDENCE_DRIFT`、canonical 缺失或 ledger 绑定失效仍阻断。禁止用镜像、新闻、AAII/PCR 或推算值回填 NAAIM。未来只有实际配置且验证通过的官方订阅通道才能恢复 `ACTIVE_SUBSCRIBER`。
- 可靠性字段：`--status` 与 8766 展示按 Asia/Shanghai 自然日去重的 `success_rate_30d/90d`、样本数、连续失败、最近成功/恢复，并分开统计 transport/parse/validation/promotion 四段；另显示 canonical 推进率与有确定发布日源的 expected-release 状态。同日 06:45 失败、07:05 成功只算一个成功日。`MIGRATION_DUE` 是治理提醒；`ACTION_REQUIRED` 是仍应可获取的官方源需要人工处置；`RETIRED_PAYWALL` 表示历史冻结、周频探测、无需购买或日常干预。
- FRED PIT 取证：生产路径保留 observations API 查询的 `realtime_start/realtime_end`、`fetched_at`、source URL 和 `observation_date + 1 day` 规则；这些 legacy realtime 字段只是查询 vintage。ALFRED `output_type=3` 事件库与真实逐事件 `realtime_start` 回放已实现为独立的 `*_vintage.csv` canonical/ledger，但 `fred-vintage-pit-v1` 正式 gate 已拒绝，`use_fred_vintage_pit` 必须保持 OFF，不得把 exact 文件用于生产评分。父事件库失败时三个派生源保留上一份认证文件，OFF 直接读未改动 legacy 文件。This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.
- Dollar 历史修订：`dollar.csv` 的已认证行保持不可变。FRED 若修订非最新历史行，只有当前 H.10 同日期值在四位小数上精确一致时才记为 `FRED_PRIMARY_CONFIRMED_BY_H10 / QUARANTINED`；canonical 旧值不重写，新日期仍须逐日通过 H.10 精确见证后才可追加，新行百分位按冻结后的 canonical 历史重算。最新认证行被改、旧日期缺失、历史插行、H.10 缺失/不一致或最新日期不一致仍然 `VALIDATION_ERROR` 并保留旧 canonical。原始 FRED/H.10 文件、normalized CSV 与 revision evidence 都保存在对应 ExternalSourceRunner run 目录。
- 行情 shadow witness：Alpaca SIP 只与 Yahoo/local canonical 比较最近日线 OHLCV，产物在 `data/archive/market_witness_*.json`。`MATCH` 是辅助取证，`NO_WITNESS/FETCH_ERROR` 不自动替换 canonical，也不改评分或 `input_hash`。
- 许可边界：AAII/NAAIM 不以未授权镜像、抓取绕过或推算值替代官方真值。AAII Insights RSS 属 AAII 官方公开发布面；NAAIM 未购买订阅时保持 `RETIRED_PAYWALL`，不维护会员会话。自动化只负责读取获准的官方发布面、记录 SHA-256、校验期号/字段/PIT 日期并晋升 canonical。
- 旧 `backfill_soft_data --only {naaim|aaii}` 只作为兼容路由，生产刷新以 ExternalSourceRunner ledger 为准。CNN F&G 回填是 feature-OFF 的研究入口，也必须经 Runner 晋升，不能直接写 canonical。
- 缺数据≠安全：`use_soft_data_max_age` 当前已 ON，超龄源自动走 missing_weight；回滚仪式见 §6。

## 3. Suspect valve PENDING

- 含义：坏 tick 嫌疑日，硬阀门降级为 PENDING 等次日干净收盘确认（`use_suspect_valve_guard=true` 已部署）。
- 处置：不动作。次日确认仍触发→正常 100% EXIT；解除→恢复。连续 2 天 PENDING 才需人工查源数据（`data_quality_audit.py`）。

## 4. IBKR 只读连接失败

- 影响：仅持仓对账缺失（payload `ibkr` 块），评分/建议不受影响。
- 处置：确认 TWS/Gateway 在跑、端口对；红线检查 `config.ibkr.readonly` 必须 true（preflight 违规会直接 abort live 运行）。

## 5. 回测 / gate 失败

- 单变体独立进程跑（同进程多回测 OOM）；用 `HERMES_DATA_DIR` 指向隔离数据副本，绝不直接读写包内 data/。git checkout 内的 `score`、dashboard/Web refresh 和 daily 入口缺少该变量时会在任何运行态写入前 fail closed；不要绕过此保护。
- alpha gate FAIL = 正常产出：flag 保持 OFF，失败原因归档进 FLAG_REGISTRY Rejected 区，**不二次调参**。
- 同一经济数据从近似/非 PIT 表示迁到更权威的真实 PIT 表示时，必须预先声明为 data-correctness migration，按 [`ADR-001-pit-data-correctness-migrations.md`](adr/ADR-001-pit-data-correctness-migrations.md) 验收。该门仍强制完整影响报告和人工批准，但不以正 alpha 作为通过条件；不得在看到 alpha gate 结果后临时换轨。

## 6. Flag 翻闸（人工门，固定仪式）

1. byte-identical（OFF）证明 + gate/no-op 证据齐备；2. FLAG_REGISTRY 写卡（假设/证据/回滚）；3. 改 repo config → `scripts/deploy_to_live.sh` 走 config diff y/n；4. 次日对比 post-run diff 确认行为符合预期。
- **回滚**：flag → false（config 同步 live），一律一步可逆。`use_soft_data_max_age` 与 `use_full_confidence_spine` 当前均已 live；任何后续 flag 仍须先完成本节证据链。

## 7. 部署 repo → live

- `bash scripts/deploy_to_live.sh`。部署开始会短暂停止 8766；这是为避免 dashboard 在同步中途惰性 import 到半套代码，通常只持续 smoke 与重启所需时间。
- 脚本先停 dashboard，再由 Python `fcntl` helper **一次 acquire** 同一把 `<archive_dir>/.pipeline.lock`，连续完成：精确目录备份 → 构建 `releases/<hash>_<stamp>/` staging → 共享运行态挂载（`data/`、`reports/`、`orders/`、package `data/config` 不进 release）→ 同步 [`ops/`](../ops/) 入口 → config diff 人工 y/N → staging import/predeploy smoke → `current` symlink 原子切换。整段中间不释放锁，daily、Web refresh、CLI score 都不能插入。
- 真正的持锁边界是 `pipeline_lock_exec` 父进程的单次 `fcntl` lease。内部 `--locked-swap/--locked-rollback` 还会校验继承 FD 与目标 lock 是同一 inode，并用新 OFD 非阻塞抢锁必须得到 `EWOULDBLOCK`；这是防止 agent/人工直接调内部模式的 guardrail，不宣称能对抗拥有本机同用户代码执行权限的恶意调用者。
- smoke 成功后释放部署锁并重启 dashboard；`verify_live` 再按正常事务获取锁。验证仍走真实 `run_daily.sh --deploy-verify` 与新 live 代码，但 `HERMES_DATA_DIR`、日志和 audit/SQLite 指向 APFS 临时隔离副本；它必须产生 `manual_rerun`，不得改官方 receipt/state、live audit、live SQLite、heartbeat 或 live 日志。
- `predeploy_smoke --json` 的 `data_root` 是本次检查实际读取的数据根证据：仓库运行会临时选择 live mirror，显式 `HERMES_DATA_DIR` 原样优先，staging/R6 release 使用其 package-level shared symlink。该字段为空视为验收证据不完整。
- live 运行数据不再反向同步到 repo。需要研究快照时使用显式导出到独立目录；部署本身不修改 repo 的 `data/soft_history`。
- 全部验收通过后，`.hermes` 只提交 allowlist：`current`/`previous` 指针、当前 release 内 package Python（排除 tests/config/data）、`VERSION`、release `scripts/run_daily.py`、稳定入口 `scripts/run_daily.py`、`bin/run_daily.sh`、`bin/serve_dashboard.sh`、`bin/refresh_external_precheck.sh`、`bin/refresh_external_shadow.sh`、`bin/refresh_external.sh`、`bin/hermes_watchdog.py`、`bin/prune_runtime_artifacts.py`。SQLite、audit/journal、持仓、order preview、logs/reports、备份、token/key/config 不进入部署 commit。
- 回滚：任何同步、smoke、dashboard、verify 或 `.hermes` commit 失败都会停止 dashboard、重新获取同一把锁，并用隔离备份目录 `~/.hermes-deploy-backups/escape-top/hermes_escape_top.predeploy_backup_<stamp>/` 恢复入口脚本、`current/previous` 指针、共享运行态初始状态和原 git index；如果已切到新 release，则把 `current` 原子切回旧 release 或恢复 legacy 原目录模式；随后重启 dashboard、非零退出，且绝不打印 `deploy OK`。rollback 本身失败会输出 `DOUBLE FAILURE` 与保留的 backup 路径，不自动重试。
- daily 入口：launchd `com.hermes.daily` → `~/.hermes/bin/run_daily.sh` → `~/.hermes/skills/investment/escape-top/current/scripts/run_daily.py`（若 `current` 尚不存在则回退 legacy root），后者经 `python -m hermes_escape_top.scripts.run_daily_package` 跑**唯一的包引擎**。R6 原子化部署后，`HERMES_RUNTIME_ROOT` 指向 `current` release，`HERMES_DATA_DIR` 默认指向 `current/hermes_escape_top`，而 package `data/`、根 `reports/`、`orders/` 再由 release 内 symlink 落到 shared runtime。不要把 daily 的 runtime root 指回稳定 live 根，否则会写入 legacy `escape-top/hermes_escape_top/data`，dashboard 看不到。

### 7.1 已登记的一次性 live 权限维护

- 2026-06-19 只读盘点：live `data/` 共 68 个 CSV，49 个为 `0600`、19 个为 `0644`；repo 对应 CSV 全部为 `0644`。这是旧 `mkstemp + os.replace` 留下的权限漂移，不是当前运行故障（live 进程与文件同用户）。
- 新 `atomic_write_csv` 会保留已有 mode，不再制造新漂移，但不会自动修正历史文件。在真实部署窗口中先导出 path/mode 清单，再将 live `data/history/*.csv` 和 `data/soft_history/*.csv` 统一为 `0644`，最后复核文件数、SHA256 与 dashboard/daily 可读性。该操作不得在普通 code review 中静默执行。

## 7.5 仪表板服务（com.hermes.dashboard）

- 8766 由 launchd 常驻托管（开机自启 + 崩溃自拉起），入口 `~/.hermes/bin/serve_dashboard.sh`。
- **从 LIVE 包服务，不是 repo**：launchd agent 无 `~/Documents` 的 TCC 授权（repo-served 模式下会 `Operation not permitted` 且 NO_CACHE）；且操作台应跟随部署版本而非 repo 半成品。**代码改动经 `deploy_to_live.sh` 才会出现在 8766**。
- 探针分层：`/health` 与 `/livez` 只证明 HTTP 进程存活；`/readyz` 只在 `strategy_data.level=OK` 时返回 200，否则返回 503。IBKR 或 SIP 等辅助证据降级不会单独把策略 readiness 置为失败。部署脚本只用 `/livez` 判断服务已拉起，业务可用性仍由 `/readyz`、`/api/health_status` 和 morning acceptance 共同取证。
- 数据根=live（`HERMES_DATA_DIR` 指向 live 包），显示的是当日真实决策。
- 威胁模型：8766 只绑定 loopback，所有有效 POST 都校验本机 Host/Origin。`/api/confirm_execution` 会写决策确认状态，额外要求 `HERMES_CONFIRM_TOKEN`；数据刷新、重算和只读检查端点仅限 loopback。退休的 M4/demo URL 只有 HTTP 410 tombstone、没有执行实现。锁冲突返回 409，不并发执行。
- 禁止将当前鉴权模式直接用在非 loopback/反向代理场景；如需对外暴露，必须先将全部 mutating POST 升级为 token 鉴权并重新审核 CSRF 与代理信任边界。
- 排障：`tail ~/.hermes/logs/dashboard.err.log`；重启 `launchctl kickstart -k gui/$(id -u)/com.hermes.dashboard`。

## 8. launchd 维护

- 状态：`launchctl print gui/$(id -u)/com.hermes.daily`；决策外部源预检看 `com.hermes.external-precheck`；研究/辅助影子刷新看 `com.hermes.external-shadow`；延迟行情证据看 `com.hermes.market-third-source`；运行态保留看 `com.hermes.runtime-retention`。手动触发必须先确认无 daily/deploy，再用对应 label 的 `launchctl kickstart`；默认无需人工触发。
- 停用：`launchctl bootout gui/$(id -u)/com.hermes.<external-precheck|external-shadow|market-third-source|daily|watchdog|runtime-retention>`。
- watchdog 节假日表覆盖到 2028，到期告警文本会自带提醒（`~/.hermes/bin/hermes_watchdog.py`）。

> 待办（T12 余项）：health 页面各非绿状态直接链接到本文对应小节（web/render 改动，与 T20 仪表板一起做）。

## 9. 系统验证回归 + 诊断纪律

- **回归脚本**：`HERMES_DATA_DIR=<干净数据根> PYTHONPATH=src /Users/liweishi/.hermes-v3/.venv/bin/python scripts/system_validation.py` —— 28 个用例覆盖数据可信/决定性/新鲜度/稳定性/逻辑/配置 byte-identical；结果写 `building/reports/system_validation_report.json`，任一 SYSTEM 用例失败即退出码 1。大改 pipeline/数据层后跑一次。这里固定使用开发 managed venv，不使用 shell 的 ambient `python3`。
- **诊断纪律（铁律）**：这台机器的 shell stdout 会严重交错（cwd-reset 伪影），`cat -A`、多行 `echo`、交错的 `print` 都可能显示**假内容**。2026-06-13 我曾据此误判出一个不存在的"完整性闸门只扫首文件"bug。**任何"系统出问题"的判断，必须用 写临时文件 + Read 工具 + 单布尔/单 token 断言 复核，绝不凭 stdout 下结论。** 验证方法本身也要可信。
