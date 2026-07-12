# Watchdog 硬化与 Live 部署外审交接

> 日期：2026-07-12
> 基线：`hermes-docs @ 3e4c0fc`
> 工作分支：`codex/watchdog-hardening`
> 当前 live：`4a0c20c 20260707_171720`
> 边界：测试期间未运行 daily、未刷新 IBKR、未改 live config、未部署

## 1. 结论

本批解决的是 R6 后 watchdog 仍读取旧审计路径而产生假阳性的问题，同时把 watchdog 纳入 R6 部署的同步、备份和回滚事务。

候选实现保持以下边界：

- watchdog 只读评分审计日志，不调用评分、刷新或下单路径；
- 通知阈值仍为落后超过 2 个已完成交易日；
- 运行解释器仍是系统 `/usr/bin/python3`，实现只使用标准库；
- repo/live config 均不在本批改动范围，Dollar SLO 继续为 6 天；
- `com.hermes.watchdog` LaunchAgent 不变，仍执行 `~/.hermes/bin/hermes_watchdog.py`。

## 2. 改动文件

| 文件 | 作用 |
|---|---|
| `ops/hermes_watchdog.py` | R6 路径解析、最新有效 audit 记录、交易日计算和只读告警 |
| `scripts/deploy_to_live.sh` | watchdog 的 backup/restore/sync/chmod/live Git pathspec |
| `src/hermes_escape_top/tests/test_ops_entrypoints.py` | 路径优先级、损坏尾行、全无效日志和 2031 日历测试 |
| `src/hermes_escape_top/tests/test_deploy_to_live.py` | 成功同步、live Git 白名单和各故障点回滚测试 |
| `src/hermes_escape_top/web/refresh.py` | 8766 health 同步周六元旦不补休规则 |
| `src/hermes_escape_top/tests/test_health_truth.py` | health 交易日口径回归测试 |
| `docs/superpowers/specs/2026-07-12-watchdog-live-deploy-design.md` | 已批准设计 |
| `docs/superpowers/plans/2026-07-12-watchdog-live-deploy.md` | 分步实施与验证记录 |

## 3. 行为设计

### 3.1 审计路径

候选按以下顺序选择第一份存在的审计日志：

1. `~/.hermes/skills/investment/escape-top/current/hermes_escape_top/data/archive/audit_log.jsonl`
2. `~/.hermes/skills/investment/escape-top/shared/hermes_escape_top/data/archive/audit_log.jsonl`
3. `~/.hermes/skills/investment/escape-top/hermes_escape_top/data/archive/audit_log.jsonl`

真实 live 只读取证：

```text
audit_path=/Users/liweishi/.hermes/skills/investment/escape-top/current/hermes_escape_top/data/archive/audit_log.jsonl
latest_as_of=2026-07-10
```

### 3.2 损坏尾行

读取器逐行解析并保留最新有效 `as_of`。空行、非 JSON、缺少 `as_of`、非法日期以及进程中断留下的半行均被忽略；若整份文件都没有有效记录，则返回 unknown 并走既有告警，而不是伪造新鲜状态。

### 3.3 交易日

算法使用标准库计算 observed New Year、MLK Day、Presidents Day、Good Friday、Memorial Day、Juneteenth、Independence Day、Labor Day、Thanksgiving 和 Christmas，不再依赖截至 2028 年的静态表。NYSE 对 2028 年明确规定：元旦落在周六时不在前一周五补休；watchdog 与 8766 health 都已加入该例外。[NYSE 官方日历](https://www.nyse.com/trade/hours-calendars)

16:30 ET 仍是当日 session 计入完成状态的 settle buffer，并有 16:29/16:30 双边界测试。

## 4. TDD 与验证证据

### Watchdog RED

```text
5 failed, 13 passed
```

五项均因仓库尚无 `ops/hermes_watchdog.py` 而失败，分别覆盖 current/shared/legacy、损坏尾行、全无效日志和 2031 日历。

### Watchdog GREEN

```text
18 passed in 0.34s
```

系统解释器自检：

```text
/usr/bin/python3 ops/hermes_watchdog.py --self-test
6/6 cases OK, including 2031-07-04 and Saturday New Year
```

### Deploy RED

```text
1 failed, 12 passed
```

唯一失败是成功部署后的 `~/.hermes` commit 缺少 `bin/hermes_watchdog.py`。

### Deploy GREEN

```text
15 passed in 4.10s
bash -n scripts/deploy_to_live.sh: exit 0
```

测试覆盖 `post_sync`、`smoke`、`external_precheck_reload`、`dashboard_restart`、`verify_live` 和 `hermes_commit` 六个失败点；每个失败点都要求路径、内容、mode、symlink、Git index 恢复到部署前快照。

### 汇总

```text
focused watchdog/deploy/health: 49 passed in 4.59s
full suite: 780 passed in 92.75s
```

最终全套无 warning。

## 5. 独立 Reviewer 发现与处置

| 级别 | 发现 | 处置 |
|---|---|---|
| P1 | 周六元旦被错误前移到周五，可能把 lag=3 算成 2 | 新增 2027-12-31/2028-01-03 红测；watchdog 与 8766 health 同步修正 |
| P2 | 16:30 ET settle buffer 无回归测试 | 新增 16:29 不计、16:30 计入测试 |
| P2 | deploy fixture 只覆盖首次 legacy→R6 | 新增已有 current/shared 的成功切换与失败回滚测试 |
| P2 | watchdog 源和旧文件原本可执行，chmod 测试可能假阳性 | fixture 改为 0644/0640，并要求 watchdog chmod 失败阻断部署 |
| P3 | 全损坏 JSONL 被写成 missing/empty | 区分 missing/empty 与 invalid，分别通知和记录 |
| P3 | torn-tail fixture 末尾有换行 | 改为真实无末尾换行的半条 JSON |

reviewer 未发现 current/shared/legacy 顺序或 R6 backup/sync/rollback/pathspec 的结构性错误。以上 P1/P2/P3 均在部署前修复并重新跑完全套。

## 6. 外审必核问题

1. `resolve_audit_log()` 是否严格按 current/shared/legacy 顺序，且路径不存在时不创建文件？
2. malformed tail 是否只被忽略，而全无有效记录时是否仍返回 unknown？
3. 2031 年 Juneteenth、Independence Day和普通交易日是否能区分？周六元旦是否不错误前移？
4. watchdog 是否保持纯标准库，并能由 `/usr/bin/python3` 导入和自检？
5. watchdog 是否同时进入 `create_backup`、`rollback_locked`、R6 sync、legacy sync、chmod 和 `deploy_git_pathspecs`？
6. 部署任一步失败时，旧 watchdog 内容和 mode 是否恢复？
7. 本批是否零改动于策略、config、daily、IBKR、WebUI 和 live？
8. 主工作树的大型 baseline、execution-timing 产物和其它未提交文件是否被排除？

## 7. 部署门槛

部署前必须同时满足：

1. `hermes-docs` 与远端同步，候选提交已 push；
2. 工作区只有已知且不会进入提交的本地产物；
3. 当前时间不在北京 07:00-07:20；
4. 8766 返回 HTTP 200；
5. `pgrep -f scripts/run_daily` 为空；
6. `/usr/bin/python3 ops/hermes_watchdog.py --self-test` 为 0；
7. 部署 config 提示必须回答 `N`。

部署命令：

```bash
echo N | bash scripts/deploy_to_live.sh
```

部署后必须验证：

- 输出为 `deploy OK @<repo HEAD>`，无 `ROLLBACK`；
- live `VERSION` 等于 repo HEAD；
- 8766 为 200，官方绿回执仍在，默认页无 preview 红条；
- `~/.hermes/bin/hermes_watchdog.py --self-test` 为 0；
- live watchdog 解析 active current/shared audit，最新 as_of 与官方 payload 一致；
- `~/.hermes` Git 提交包含 `bin/hermes_watchdog.py`；
- live config 的 `soft_data_slo.max_age_days.dollar` 仍为 6。
