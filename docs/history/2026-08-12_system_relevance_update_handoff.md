# Hermes System Relevance And Data Trust Update Handoff

日期：2026-08-13
基线：`c6aaa144902ea885f61fac98dac0e800c8de0ac7`
候选状态：独立外审通过，等待提交、推送与 R6 部署
范围：计划 Tasks 0-9，当前已完成 Tasks 0-8 与 Task 9 的本地发布门槛

## 1. 结论

本批把“会影响策略的输入”和“只用于观测/研究的数据”从同一个模糊健康概念中拆开，并把 repo checkout、R6 部署后认证、退役来源和发布日证据的边界写成可执行约束。

本批没有修改评分阈值、因子权重、模块 cap、硬阀门、仓位优化、DEFCON 路由、再入场、feature flag 或 live config。四个历史日期的 score status 与 `input_hash` 保持一致；在仅剥离批准的质量/置信度报告字段后，七份持久化业务工件保持一致。IBKR 仍为只读，未连接 IBKR，也没有新增下单路径。

独立外审最终结论为 P0/P1/P2/P3 均为 0，批准提交与推送。五个自然交易日观察只能在部署后逐日完成，不能被本地测试替代。

## 2. 数据通道

Source Policy Registry 仍是唯一来源政策注册表，新代码没有复制第二套元数据。`source_relevance.py` 只从现有 profile 的 `active`、`decision_role`、feature flag 和 lifecycle 计算三个结果：是否影响决策、进入哪个刷新通道、soft record 属于哪种决策角色。

按当前 live config，普通工作日自动计划为：

| 通道 | 来源 | 语义 |
|---|---|---|
| decision | dollar、real_rate、fred_net_liquidity、cboe_equity_pcr、AAII、VIX、VIX3M、SKEW、VVIX | 06:45 全量、07:05 仅重试失败、07:10 直接消费 |
| shadow | BTC funding/basis、VIX9D | 09:20 非阻断采集，不进入策略 readiness、评分、路由、官方回执或 `input_hash` |
| manual | COT NQ、OCC PCR | feature OFF 或 inactive，不再被早间任务重复请求 |
| Friday probe | NAAIM | `RETIRED_PAYWALL` 生命周期探测；普通工作日不请求 |

普通早间计划中非决策源从 4 个降为 0。显式 `--source` 仍保留给研究和人工取证，不受自动调度通道限制。

## 3. 质量含义

`data_quality` 现在只描述策略输入，`all_source_data_quality` 描述全源运维观测。当前隔离 fixture 的结果为：

| 指标 | quality | overall | 用途 |
|---|---:|---:|---|
| 策略输入质量 | 94.0 | 93.4 | health、strategy confidence、action confidence |
| 全源观测质量 | 90.0 | 92.2 | 折叠运维面板，不阻断策略 |

差异来自 `btc_funding_basis` 与两个 BTC basis 派生字段；它们 decision weight 为 0，不再扣策略置信度。策略源、hard gate、未知 soft record 的缺失、代理或超龄仍按原规则扣分。未知 record 默认 `strategy`，不能被乐观排除。

允许变化只限质量与置信度报告字段及其既有兼容镜像。scores、statuses、module/factor scores、missing weights、hard valves、sizing、routing、reentry、targets、destinations 和 `input_hash` 都受保护。

## 4. 运行数据根

从 git checkout 启动 score、dashboard/Web refresh 或 daily，缺少显式 `HERMES_DATA_DIR` 会在加锁、写回执、评分、绑定端口或落盘前拒绝运行。测试、回放和研究必须使用隔离数据副本。R6 release 的 package-level shared symlink 与显式 live root 继续可用，没有全局改写 `resolve_path()`。

repo-local ignored runtime inventory 为只读取证，没有删除运行文件。真实 worktree 也没有被清理；两个缺失的 `/private/tmp` 条目只登记为可清理元数据。

## 5. 输入生命周期

报告层现在明确区分三类状态：

- NAAIM：`已退役来源，等待 SLO 缺失路径`。认证历史保持不可变；超龄后沿用既有 missing-weight 防御路径。
- MSTR B6：`计分输入缺失 5 分`。mNAV gate 失败且 flag 保持 OFF，但 B6 不是零分占位。
- A2 CNN、B5 social、D-M4、D-M5：`非计分占位`，`max_score=0`，不进入策略 missing weight。

绑定裁决见 `docs/history/2026-08-12_naaim_b6_lifecycle_decision.md`。

## 6. 发布日证据

AAII、Dollar、Real Rate、Net Liquidity 增加 publisher-aware evidence：最近应发布日、官方 issue/release ID、content fingerprint、grace 状态和恢复证据。FRED 按官方 release metadata/calendar，不用猜固定星期；AAII 区分已发布 issue 与推断的下一期日期。

新的 expected-release 证据在每源至少五个成熟样本前只告警，不替换现有 SLO，也不放宽 canonical validation。离线 failure drill 覆盖 AAII/NAAIM 抓取失败、旧文件、错误期号、恢复，以及 VIX3M 历史修订隔离五类，共 13/13 通过，`network_used=false`、`live_data_touched=false`。

## 7. 部署后认证

新生成的 system health 报告绑定 `generator_release_hash` 与 `generator_policy_sha256`。如果 R6 已切换、旧官方报告仍健康但早于本次 attestation，morning acceptance 返回 `PENDING_POST_DEPLOY`，不是 PASS 或 FAIL，也不授权交易或下一次部署。

只有 deployment attestation 之后的下一次自然 07:10 scheduled run 可以为当前 release 生成新认证。R6 会同步、备份、回滚并重载 daily LaunchAgent，后者显式传入 `--scheduled-launchd`；直接运行 `ops/run_daily.sh` 只产生 `manual_rerun`，调用方传入任何完整 `--run-type` 会被 wrapper 拒绝，daily parser 也以 `allow_abbrev=false` 拒绝 `--run-ty` 等长选项缩写。代码不得覆盖旧报告，也不得借部署或人工重跑制造 PASS。真实 stale market、坏 receipt、audit mismatch、七工件事务失败或 policy drift 仍优先 FAIL。

BTC funding、VIX9D 和 SIP 等辅助层异常继续显示为 morning acceptance warning，但不能使策略验收 FAIL。Decision readiness 在 status 行和 refresh-run 行两轮都重新检查 source lane，即使调用方误注入 shadow 失败行也不会污染 blocking source 清单。

## 8. 有界技术债

本批只修了持久化、外部源、回执和 predeploy 边界上的六处静默失败：不可读 canonical、损坏 shared state、不可读 health evidence、SIP fallback 失败、损坏 audit JSONL、不可计算 market lag。评分敏感的广泛异常处理没有被顺手重构。

FRED credential 的最终解析顺序为 process `FRED_API_KEY`、显式 config、legacy `fred_api_key.txt` 兼容回退。`refresh_external` 会把 `~/.hermes/.env` 的 `FRED_API_KEY` 注入显式 config，因此它不会被 legacy 文件覆盖。repo 内忽略且未跟踪的重复 key 文件只在哈希一致和删除后 resolver smoke 通过后移除；live/shared legacy copy 未触碰，秘密值未写入证据。

全 `~/.hermes` Git 仓库约 1.19 GiB 的替代方案只形成迁移草案，未执行。后续应改为独立 escape-top deployment ledger，但不属于本次发布。

## 9. 发布前验证

| 门槛 | 结果 |
|---|---|
| Tasks 1-8 focused suites | `478 passed in 42.40s` |
| Task 9 first remediation focused suite | `260 passed in 17.63s` |
| Task 9 second remediation focused suite | `218 passed in 18.95s` |
| Task 9 final remediation focused suite | `243 passed in 18.95s` |
| 全套 | `1348 passed in 120.57s` |
| Governance | `7/7 OK`，含 live config policy；`ibkr_readonly=true` |
| Compile | `python -m compileall -q src scripts ops` PASS |
| Ruff severe | 全项目 `E9,F63,F7,F82` PASS |
| Ruff 默认规则 | pinned `0.15.22 --isolated`：HEAD 39、候选 39、新文件 0；本批零新增，旧债未伪装成全绿 |
| Shell / plist | 4 个 shell `bash -n` PASS；daily 与 external-shadow plist PASS |
| Secret / live data | 无秘密文件、真实 credential、CSV、database、archive 或 binary payload 进入变更；唯一命中是测试假值 `SECRET='runtime-data'` |
| Diff hygiene | `git diff --check` PASS |
| 四日期 | `all_equal=true`；只读 `c6aaa14` 基线归档与候选分别执行，绑定两棵源码树、74 个种子文件和解释器指纹；4 个 input hash 相同，每日期 7 个业务工件在批准的报告字段归一化后相等 |
| Failure drill | 13/13 PASS；无网络、无 live 写入 |

机器证据：

- `building/reports/system_update_2026_08_12/AFTER_EVIDENCE.json`
- `building/reports/system_update_2026_08_12/FINAL_FOUR_DATE_EQUIVALENCE.json`
- `building/reports/system_update_2026_08_12/FINAL_EXTERNAL_FAILURE_DRILL.json`
- `building/reports/system_update_2026_08_12/TASK3_CURRENT_QUALITY_SPLIT.json`
- `building/reports/system_update_2026_08_12/TASK7_POST_DEPLOY_CERTIFICATION_EVIDENCE.json`
- `building/reports/system_update_2026_08_12/TASK8_MAINTENANCE_EVIDENCE.json`

## 10. 独立外审清单

第一次独立外审阻断了 3 个 P1 与 1 个 P2：`refresh_external --status` 缺少运行根守卫、人工 daily 可冒充 scheduled、legacy FRED key 可覆盖显式 credential、四日期比较器没有绑定独立源码/种子环境。

第二次独立外审又阻断了 3 个 P1 与 1 个 P3：daily plist 没进入 R6 生命周期、调用方可用重复 `--run-type scheduled` 覆盖 wrapper、auxiliary health 会让 morning acceptance FAIL、readiness 第二轮未内生过滤 shadow run。四项均按上述契约完成 RED/GREEN 回归；当前等待同一审计员第三轮复审，不把“已修代码”自行等同于“外审通过”。

第三次独立外审发现最后一个 P1：`argparse` 默认允许长参数缩写，`--run-ty scheduled` 仍可覆盖 run type。解析器现已禁用 abbreviation，并有解析阶段失败的回归测试。

最终复审已通过：P0/P1/P2/P3 均为 0；独立结果为 `1348 passed in 120.83s`、governance `7/7 OK`，并逐项重算 baseline、candidate 与 74-file seed manifest 及四日期等价证据。结论为 `APPROVE COMMIT/PUSH`。

外审必须只读取证，至少回答：

1. disabled/inactive/auxiliary/research 是否可能重新进入 decision schedule？
2. shadow 证据是否可能影响 readiness、score、route、official receipt 或 input hash？
3. unknown soft record 是否 fail closed 为 strategy？
4. research-only 质量扣分是否只从 strategy confidence 排除，策略/硬门输入仍照常扣分？
5. repo production entrypoint 是否能在无 `HERMES_DATA_DIR` 时产生任何写入？
6. `PENDING_POST_DEPLOY` 是否可能掩盖 stale market、receipt/audit/transaction failure？
7. 同 hash 重新部署是否仍要求 deployment 后的新自然 run？
8. config/flags、IBKR readonly、评分、路由或订单边界是否改变？
9. 四日期差异是否严格限于批准的报告字段，七工件证据是否完整？
10. deploy 对 external-shadow 的 sync、backup、rollback、first-install 和 launchd reload 是否对称？

任何 P0/P1/P2、配置翻闸、live 数据混入或 protected output 差异都阻断提交与部署。

## 11. R6 发布与观察

独立外审批准后才可提交并推送。部署只执行一次：保留 live config，在同一 pipeline lock 下完成 R6 切换，不用 official daily 验证。部署后必须核对 VERSION、`/livez`、`/readyz`、原 official receipt/audit、七工件事务、8766 默认页、六个 launchd job 和 deployment ledger。

部署后立即出现 `PENDING_POST_DEPLOY` 是预期诚实状态；下一次自然 07:10 后才应恢复 PASS。随后观察五个自然交易日，不人工重复刷新：

- 06:45 decision 全量刷新；
- 07:05 只重试失败 decision 源；
- 07:10 daily 消费同日证据；
- 09:00 watchdog；
- 09:20 shadow 只刷新 BTC funding/VIX9D；
- morning acceptance 与 dashboard 对 source role、freshness 和认证状态一致。

五日观察未结束前，本批可视为代码已发布但运行观察仍开放；不得宣称整个 Task 9 已完成。

## 12. 残余风险

1. 39 条默认 Ruff finding 为基线旧债，主要是延迟 import、旧式脚本和未使用变量；本批零新增，但后续应单独分批清理。
2. NAAIM 仍是退役历史输入；SLO 超龄后的 missing-weight 是有意保守行为，不是自动化恢复。
3. expected-release 可靠性需自然积累五个成熟样本后才有统计意义。
4. 09:20 shadow 与 post-deploy pending 都尚未经过本 release 的五交易日自然观察。
5. whole-`~/.hermes` Git 体积与两个 prunable worktree metadata 仍待独立维护窗口处理。
