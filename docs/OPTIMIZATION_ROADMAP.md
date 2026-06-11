# Hermes 优化总方案（OPTIMIZATION ROADMAP）

> 版本：v1.1（2026-06-11，吸收 5 条执行前修订：交易日历 / T8 风险定级 / gate 缓存 key / mNAV 模块归属 / CoinMetrics 核验）
> 依据：15 维 × 10 轮评审（综合 7.8/10）+ 双方方案合并 + 3 项遗漏补全
> 主线：**先止血，再可信，再正交，最后产品化**
> 配套文档：`EXPERIMENT_REGISTRY.md`（实验治理）、`PRODUCTION_RUNBOOK.md`（运维手册）——由本路线图中 T15 / T12 产出

---

## 0. 总原则（六条红线）

1. **不碰红线**：只读、永不下单、新功能 flag 默认 OFF、人工翻闸、byte-identical 证明。
2. **冻结微调冲动**：阈值、A 模块因子、NAAIM/PCR 收紧、stabilizer/hysteresis 复活，一律不做（见 §7 不做清单）。
3. **每个优化有验证闭环**：假设 → 样本 → 回测 → 13 折 WF → PBO → DSR → 失败归档 → 回滚路径。
4. **先系统质量，后策略收益**：先让每天的输出可信、可解释，再追求增量 CAGR。
5. **新信号只接受正交来源**（链上数据），不接受已有价格/技术因子的变体。
6. **每个信号实验预算一次 gate，FAIL 即停归档**（COT 先例：管道留下、flag 永 OFF 也是合格产出）。

### 评审结论摘要（为什么是这个顺序）

- ≥9 分维度全部在方法论侧：防过拟合 9.5 / 可复现 9.5 / 架构 9.0 / 风控 9.0 / flag 治理 9.0 —— **是护城河，不是优化对象**。
- <7 分维度全部在运维侧：数据新鲜 6.0 / 性能 6.0 / 数据完备 6.5 / 部署一致 6.5 / 可观测 6.5 / 前瞻 6.5。
- **正在发生的事故**：live 价格停在 06-05、NAAIM 停在 05-27 —— 日任务靠人工触发，已静默停跑约 4 个交易日。一次真实顶部撞上"系统静默停跑一周"是本项目唯一能造成实际亏损的故障模式，因此 T1/T2/T3 先于一切。

---

## 1. 双 Agent 并行模型

### 轨道划分（按文件所有权切分，不按阶段切分）

| 轨道 | 定位 | 文件领地 |
|------|------|----------|
| **Agent A — 运维/生产轨** | launchd、日任务、部署、数据管道、WebUI | `scripts/`（顶层）、`src/.../scripts/run_daily_package.py`、`web/`、launchd plist、**config.json 与 pipeline.py 的唯一写者** |
| **Agent B — 研究/治理轨** | 基线、gate 工具链、链上实验、文档治理 | `src/.../core/factors/`、`scripts/flag_gate.py`、`scripts/backtest_flag_sweep.py`、`scripts/backfill_cot.py`、`docs/`、`building/reports/` |

### 冲突规则（必须遵守）

1. **单写者文件**：`config/config.json`、`pipeline.py`、`web/health.py` 只允许 Agent A 写。Agent B 需要加 config 键（如实验 flag）时，提交"键名+默认值+注释"清单给 A 合入，或等同步点。
2. **测试夹具冻结窗口**：T8（数据出 git）会大面积改 `tests/` 夹具。T8 进行期间 Agent B 不得改动任何测试文件；T8 合并后双方 rebase（同步点 S1）。
3. **回测互斥**：全窗口回测/gate 每个变体独占一个进程、约 38-52 分钟、内存敏感（同进程多回测会 OOM）。**两个 agent 不得同时跑回测**；gate 排队执行，且必须在 `/tmp` 冻结快照上跑（live serve 会重写 CSV，T8 完成后此竞态消失）。
4. **人工门保留**：所有 flag 翻转、deploy 确认、launchd 安装由人类执行，agent 只准备到"待确认"状态。

### 同步点

| 同步点 | 时机 | 动作 |
|--------|------|------|
| **S1** | T8 合并后 | 双方 rebase；B 恢复测试相关工作；回测竞态规则解除 |
| **S2** | T13 完成后 | gate 提速生效，P2 所有实验（T19/T21）必须用新 gate 链路 |
| **S3** | 每个 flag 就绪时 | 人工 review + 翻闸（不属于任何 agent） |

### 并行批次总览

**执行起点（已定）**：T1/T2/T3 + T5 先行——当前最值钱的优化不是新增 alpha，而是确保系统每天真的醒着、数据真的新、异常真的会叫人。链上与 UI 在系统"醒着"之前一律不碰。

```
批次1（P0 第1周）:  A: T1+T2+T3 → T5+T6        ‖  B: T4 + T7 + T14
批次2（P0 第2周）:  A: T8a→T8b→T8c（2-3d，独占 tests/）‖  B: T13 + T15（不碰 tests/）
                    └─────────── S1 ───────────┘
批次3（P1）:        A: T9 → T10 → T11 → T12     ‖  B: T16（链上离线研究）+ T18
批次4（P2）:        A: T20                      ‖  B: T17 → T19 →（gate 排队）→ T21
批次5（P3）:        A: T24                      ‖  B: T22 + T23
```

---

## 2. P0 —— 止血 + 基线 + 地基（~1.5 周）

### T1 launchd 自动日任务 ⚡最先做 `[A · 2h]`

- **依据**：日任务纯手动，已停跑 4 个交易日。本机已有 `ai.hermes.gateway.plist`、`com.hermes.next5watch.plist`，加第三个零学习成本。
- **实现**：
  - `~/Library/LaunchAgents/com.hermes.daily.plist`：每日北京时间 07:10（美股收盘后）执行 `~/.hermes/bin/run_daily.sh`。
  - wrapper 内容：cd 到 live runtime → `run_daily_package.py --live --commit-state`；stdout/stderr 落 `~/.hermes/logs/daily_$(date +%F).log`；退出码非零 → `osascript -e 'display notification'`。
  - launchd 环境是裸的：wrapper 显式写 PATH / python 解释器（沿用 06-07 修过的"该 venv 必须能 import numpy/pandas/scipy 才用"判断）。
  - 非交易日跑一次幂等（latest available date 不前进），无需日历判断。
- **验收**：`launchctl kickstart` 手动触发 → audit_log 出今日条目、OHLCV 推进到最新交易日；随后 3 个自然日零干预，每个交易日 log + audit_log 都有新条目。
- **回滚**：`launchctl unload` + 删 plist。

### T2 Dead-man switch `[A · 1-2h]`

- **依据**：对 T1 本身失效的保险（launchd 任务被 macOS 升级/权限变更掐掉是真实风险）；可观测的前提是"有人会被叫到"，而不是等人打开 8766。
- **实现**：`com.hermes.watchdog.plist` 每日 09:00 跑 ~30 行 python：读 live `data/archive/audit_log.jsonl` 最后条目日期，距今 > 2 个**NYSE 交易日** → osascript 推送 + 写 watchdog log。
- **⚠️ 交易日历**："交易日"必须按真实 NYSE trading calendar 算（含节假日），不是"非周末的自然日"——否则长周末/感恩节/圣诞必然误报。**复用现成轮子**：06-07 已把 `_history_is_fresh` 改成 trading-day-aware，watchdog 直接调它的交易日判断，不要另写一套。
- **验收**：阈值临时改 0 触发一次假告警确认通知到达；用一个历史长周末日期（如 7/4 后的周一）做单测，确认不误报。

### T3 立即补跑 `[A · 10min，人工]`

手动跑一次 live 日任务把停更的 4 天补上。**验收**：live QQQ/MSTR 推进到最新收盘。

### T4 基线冻结 `BASELINE_2026_06_11.md` `[B · 1d]`

- **实现**：
  - 汇总当前 config/flag 快照、data manifest id、CAGR/MDD/Sharpe/Calmar/PBO/DSR/换手率/各品种贡献（素材全在 `building/reports/` 与各 gate 报告，主要是汇总核对）。
  - **基线数字此后机器生成**：写脚本从最新 `GATE_REPORT_*.md`/回测 JSON 提取 → 注入 BASELINE 与 context.md 第 13 节，消灭"~15.5-17%"这种手抄区间漂移。
- **验收**：文档数字与 gate 报告零出入；任意后续实验能与冻结基线公平比较。

### T5 preflight 报告 `[A · 0.5d，依赖 T1]`

- **实现**：`run_daily_package.py` 运行开头输出一屏：OHLCV + 每个软数据源的 as_of 与超龄状态、suspect 标记、failover 是否触发、state_db/audit_log/signal_journal 可写性、`ibkr.readonly == true` 断言、git 工作区是否有运行时脏数据（T8 完成后此项退化为断言）。超龄判断同 T2：按 NYSE 交易日历，复用 trading-day-aware 辅助函数。
- **验收**：运行前一屏回答"今天的输出可信不可信"。

### T6 post-run diff `[A · 1d，依赖 T5]`

- **实现**：日任务结尾对比昨日 payload：分数（按 A/B/C/D 模块）、状态、卖出比例、路由、再入场三锁逐项变化 + 归因到具体因子（explain 链已有，主要是 diff 渲染）。同时落盘 `~/.hermes/logs/diff_$(date +%F).md` 供 T20 仪表板直接渲染。
- **验收**：一屏回答"今天的建议为什么和昨天不同"。

### T7 CI/测试不变量断言 `[B · 0.5d]`

- **实现**：四条 pytest 不变量：
  1. 全代码无下单路径（对 IBKR API 调用做白名单断言）；
  2. 所有 ibkr 配置 `readonly: true`；
  3. 代码中无 `ssl.CERT_NONE` / `verify=False`（配合 T14）；
  4. 跑完测试套件后 `git status` 干净（T8 完成前此条预期红，作为 T8 的验收测试先行写好）。
- **验收**：违反任何一条套件即红。

### T8 运行时数据移出 git `[A · 2-3d ⚠️高风险任务，独占 tests/，完成即 S1]`

- **依据**：一项改动消三个顽疾——serve↔backtest 竞态（读到半空 CSV）、"绝不 git add -A"纪律负担、测试弄脏跟踪文件。比"dirty-data guard"探测器更优：修根因而非检测症状。
- **风险定级**：⚠️ 高——它同时触碰数据路径解析、测试夹具、serve、run_daily、backtest 五个面。原估 1 天偏乐观，按 2-3 天排，且**严格分三步走，每步独立验收，不一把梭**：
  - **T8a 路径审计（0.5d，只读不改）**：盘点所有读写 `data/` 的代码路径——`resolve_path` 的全部调用方、`bootstrap_history` 写入点、store/state_store/manifest/archive 的落盘位置、scripts 里的硬编码相对路径。产出一张"路径清单 + 各自迁移方案"，发现意外耦合就在这步停下重估。
  - **T8b 最小切片（0.5-1d）**：只给 `history_dir` + `archive_dir` 加 `HERMES_DATA_DIR` 覆盖，只迁 serve 一个消费者。验收：serve 运行中 `git status` 干净、决策 byte-identical。通过后再推广到 run_daily / backtest。
  - **T8c 测试夹具迁移（1d）**：pytest `tmp_path` 化 + repo `data/` 转只读 seed。验收：全套件绿且跑完 `git status` 干净（T7-④ 转绿）。
- **总验收**：serve 与一个回测并行跑完无 EmptyDataError；任一环节失败可单独回滚该切片。
- **回滚**：unset env 即回旧行为（每个切片独立成立）。

### T14 ssl.CERT_NONE 修复 `[B · 0.5h]`

- **依据**：`backfill_cot.py` 用 `ssl.CERT_NONE` 绕过证书验证拉 CFTC 数据；只读系统的数据源被中间人污染同样影响决策。
- **实现**：装 certifi 或 `SSL_CERT_FILE` 指向打包 CA bundle，删 bypass。**验收**：COT 拉取成功 + T7-③ 转绿。

---

## 3. P1 —— 可信 + 提速（~2 周）

### T9 数据 SLO + 超龄降级 `[A · 0.5d]`

- **实现**：
  - config 每个软数据源声明 `max_age_days`（日频源 4 / 周频源 NAAIM、AAII、NFCI、COT 10）。**超龄按 NYSE 交易日算**（同 T2/T5，复用 trading-day-aware 辅助函数）——日频源的"4 天"若按自然日，长周末+一个节假日就会误降级。
  - `collect_soft_data` 超龄字段置 None → 走既有 missing_weight 路径（"缺数据≠安全"延伸为"过期数据≠新鲜数据"）。
  - `web/health.py` 超龄源黄灯（现状：dollar 用 9 天前的百分位打分而仪表板是绿的）。
  - flag `use_soft_data_max_age` 默认 OFF → byte-identical 证明 → 回测确认 no-op（历史数据完整）→ 属 F4 类 live 鲁棒性翻闸（不需完整 13 折 gate）。
- **验收**：人工截断一个 CSV 到 10 天前 → missing_weight 上升 + health 黄灯 + 分数偏防御。
- **回滚**：flag → false。

### T10 置信度脊柱接线 `[A · 0.5d]`

- **依据**：`pipeline.py:750` 的 `fragility=0.0`、`disagreement=0.0` 是硬编码——宣称 6 分量实际 4 分量，且 0.0 = 无惩罚，置信度被系统性高估。**T20 的置信度分解面板依赖本项，否则面板展示两个恒为零的假数字。**
- **实现**：接 governance 模块现成的 E7 脆弱性 / E22 分歧计算；flag `use_full_confidence_spine` 默认 OFF → byte-identical → gate（回放不消费 confidence 模式，预期 no-op）→ 翻闸。
- **回滚**：flag → false。

### T11 软数据 SSOT + 部署脚本 `[A · 0.5d]`

- **方向声明**：调度器跑在 live（T1）→ **live 是软数据权威**；repo 回测需要新数据时从 live 拉快照。结束"代码单向 rsync、数据双向分叉"的现状。
- **实现**：`scripts/deploy_to_live.sh` 五步：
  1. 代码 rsync repo→live（固化现有手工命令：`--include='*.py'`，排除 tests/config/data，加性不 `--delete`）；
  2. soft_history live→repo 反向同步；
  3. config diff 彩色展示 + 人工 y/n（人工门红线保留）；
  4. 部署后验证：live import + 离线跑最近一日评分，决策与部署前对比，变了报红；
  5. 在 .hermes git 仓 commit。
  - 顺手修本次发现的漂移：`backfill_cot.py` 同步进 live 包 scripts/；live 补 `cnn_fear_greed.csv`、`cot_nq.csv`。
- **验收**：连跑两次 deploy 第二次零变更（幂等）；决策对比通过。

### T12 `PRODUCTION_RUNBOOK.md` + health 操作清单化 `[A · 1d]`

- **实现**：固定流程六节——正常运行 / 数据缺失 / suspect valve pending / IBKR 只读连接失败 / gate 失败 / flag 回滚。health 页面每个非绿状态直接链接到 runbook 对应小节（从"状态展示"升级为"操作清单"）。
- **验收**：不读日志知道当天是否安全；任何 flag 开启有显式人工门记录。

### T13 gate 工具链提速 `[B · 1d，完成即 S2，必须在 P2 实验前]`

- **依据**：单变体回测 52 分钟、一次 gate 半天，是 P2 两组实验（T19/T21）的直接成本项；`calibrate_next3_v2` 已验证"预计算 Backtest_*.json 缓存"模式可行。
- **实现**：把缓存模式推广到 `flag_gate.py` 全链路——因子快照计算与组合模拟两段分离缓存；基线 equity 曲线缓存复用（同一基线不重跑）。
- **⚠️ 缓存 key 必须严格 hash**——gate 是验证体系的地基，缓存 key 不严格等于在地基上打洞。key 至少包含：**git commit（代码版本）+ config 内容 hash + data manifest id + flag 组合 + 回测窗口 + 成本参数（摩擦 5bps 等）**，任一变化即 miss 全量重算。缓存文件内嵌 key 明细，命中时打印"复用了什么、基于哪个 commit/manifest"，可审计。沿用系统既有 input_hash 纪律，不自创弱化版。
- **验收**：① 对已有候选重跑一次 gate，结果与历史报告一致、耗时显著下降；② **污染测试**：改动 config 任一参数 / 换 manifest / 换 commit，确认缓存 miss 重算而非误命中；③ 每变体仍独立进程（OOM 约束不变）。

### T15 `EXPERIMENT_REGISTRY.md` 升级 + Rejected 回填 `[B · 1d]`

- **实现**：升级现有 `FLAG_REGISTRY.md`（**不新建平行文档**）。每实验一张卡：假设 / 影响面（数据·因子·评分·阀门·仓位·路由·UI）/ flag / 验证（WF·PBO·DSR·Bootstrap CI·in-system path）/ 回滚（配置项·commit·报告）/ 结论。四态：Candidate / Shadow / Live / Rejected。
- **Rejected 区从历史回填**（素材在 `building/reports/` 与 gate 报告）：decision_stabilizer、hysteresis_only、H-M2 缓冲、NAAIM/PCR 收紧（f8）、COT NQ、MOVE（A18）、A19 NDX 集中度、batch-2 组合……每条写明失败原因，防止重复踩坑。
- **验收**：所有历史 flag（含 24 个 data/use flag）在 registry 中有归属态和证据链接。

---

## 4. P2 —— 正交增量 + 工作台（~3 周）

### T16 MSTR 链上 D 轴：离线研究 `[B · 1-2 周，可与批次 3 的 A 轨全程并行]`

- **候选信号**（六个）：MVRV / realized cap 估值温度；交易所流入流出异常；长短期持有人行为；BTC 实现波动 regime；BTC 回撤 × mNAV 扩张/压缩；流动性压力 proxy。
- **实现**：
  - **第 0 步：数据源核验（0.5d，先于一切编码）**——"CoinMetrics community API 免费可回填"是会过期的信息（参考 FRED fredgraph 无 key 端点悄悄截断 hy_oas、CFTC zip URL 整体失效的先例）。动手前核验：当前 API 端点与认证方式、所需字段（MVRV/realized cap/exchange flows/SOPR 等）在 community 层是否可用、历史回填深度、速率限制、许可条款是否允许本用途。**任一不满足 → 评估替代源（Glassnode/Coin Metrics 付费层/blockchain.info），数据源不落实不写一行因子代码。**
  - 新建 `core/factors/onchain_mstr_lab.py`，**不进生产路径**。
  - 全字段 PIT 对齐，禁止未来数据。
  - **先回答结构问题（A 模块的死因，不在 D 重演）**：D 模块 cap=20、MSTR 已有 6 因子——链上因子挤占现有权重还是撞 cap？权重方案在离线阶段定稿。
  - 筛选方法用**事件法**（labeled tops 的 lead-time / precision），不用裸 IC（IC 结构性偏向 coincident 因子，06-08 autopsy 的方法论结论）+ 与现有 A/B/C/D 因子相关性矩阵 + 触发频率。
- **门控标准**（进 T19 的前提）：相关性不过高；PBO 低于既有上限（0.50）；MDD 不显著恶化；换手不爆炸；对 MSTR 的贡献不靠牺牲 FNGU/SOXL 平均出来。
- **失败条件**：只在少数 BTC 牛熊拐点有效；median forward return 好看但 in-system 路径变差；需要过多参数；数据源不可稳定回填。

### T17 B6 mNAV 接线 `[B · 1d + gate]`

- **实现**：mNAV = MSTR 市值 / (BTC 持仓 × BTC 价格)；BTC 持仓数做低频手工 CSV（季度公告更新，慢变量可接受），其余分量自动。与 T16 共用数据管道。flag `data_mstr_mnav` 默认 OFF。
- **⚠️ 模块归属与隐性重标定，实现前定稿**：
  - mNAV 是 MSTR-specific valuation，放 B6 可以，但要先回答它与 D 模块（品种特有风险，已有 mNAV 溢价相关因子语义）的边界——**同一信息不得在 B、D 两处重复计分**。若 D 模块现有 MSTR 因子已隐含溢价逻辑，接线 B6 前先做去重裁决。
  - 接线 B6 会把 B 有效上限 16→21，**这本身就改变所有 MSTR 历史分数的归一化**（有效满分变化 → missing_weight 重排）——它不是"加一个因子"而是一次隐性重标定。因此权重/上限方案（B6 占几分、是否下调其他 B 因子）必须在写代码前定稿并写进实验卡，gate 按"含归一化效应的完整 in-system 路径"评估，不许只看因子本身的边际贡献。
- **验收**：byte-identical（OFF）→ 一次 gate → 人工翻闸或归档。

### T18 正版 CBOE PCR 前向抓取 `[A · 0.5d]`

- **依据**：现 PCR 是 100% 代理且 repo 侧也停在 05-29；历史数据封锁，但每日页面可从现在开始积累，攒一两年后替换代理。
- **实现**：挂进日任务的软数据刷新（与 T17 手工 CSV 同性质：低频、便宜、先攒着）。**验收**：每日新增一行真实 PCR。

### T19 链上信号 in-system gate `[B · 每信号 0.5d，依赖 T13+T16，gate 排队执行]`

- T16 幸存者逐个进 13 折 WF + PBO + DSR；**每信号一次 gate，FAIL 即归档进 T15 的 Rejected 区**。通过者待人工翻闸（S3）。

### T20 仪表板工作台化 `[A · 1 周，依赖 T6+T10]`

- **范围控制**：操作者只有一人，**首屏六问做完即停**，不做通用产品打磨。
- **首屏六问**：总体状态？最危险资产？为什么危险？建议动作？置信度最弱环节？待人工确认事项？
- **模块**（payload 中 action_intents / routing_explain / confidence 分解已存在，主要是渲染）：
  - 今日变化：直接渲染 T6 的 post-run diff；
  - Top 5 因子贡献；
  - 置信度六分量分解（依赖 T10，否则 fragility/disagreement 恒零=面板撒谎）；
  - 硬阀门面板：触发 / 未触发 / pending 及原因；
  - 再入场三锁面板；
  - 路由解释：为什么 DEFCON 1/2/3、为什么是 BOXX/DBMF/GLD/BRK.B/QQQ/SOXX/BTC。
- **顺带**：render.py（1606 行，零测试）与 health.py 加冒烟测试（固定 payload → HTML 含关键元素断言）。
- **验收**：不读日志能理解当天建议；能区分"数据问题 / 市场问题 / 模型分歧问题"；人工确认事项显式列出。

### T21 arm-then-fire 重构 `[B · 1-2 周，排 T19 之后，先验 ~30%，一次 gate 定生死]`

- **降级理由（三条历史证据）**：现有实现有双重计数缺陷（arm 源 real_rate/dollar 同时是加分因子）；"suspect 触发硬阀门"场景已被已部署的 `use_suspect_valve_guard` 覆盖；所有"确认延迟/平滑"类机制（stabilizer、hysteresis）in-sample 好看、OOS 全部失败。
- **前置**：重构为 **leading-data-only arming**——arm 信号只允许用不进评分的数据（NFCI / MOVE 等 OFF 因子是现成候选），消灭双重计数。
- **状态机**：ARMED / FIRE / COOLDOWN / INVALIDATED。
- **不适合 arm（保持直接开火）**：数据干净的明确硬阀门；QQQ/SOXX/SMH 同时结构破位；MSTR 与 BTC 同破关键线；confidence DEGRADED 且风险极高（应要求人工确认，而非自动放松）。
- **流程**：shadow 模式先跑（payload 输出"已 armed，因 X，等待 Y 确认"，不影响 live）→ 一次 gate：whipsaw 降低 且 MDD/尾部不变差才翻；FAIL 即按 T15 模板归档，**不二次调参**。
- 注：arm-then-fire 的 relief 不在 replay 路径内，不能用 calibrate_next3_v2 校准——对照 on/off 直接跑 `run_full_backtest`。

---

## 5. P3 —— 解释力 + 远期（~2 周）

### T22 ex-ante 风险贡献 `[B · 0.5 周]`

每个 sleeve 对组合波动 / CVaR / 回撤预算的贡献（risk_engine 的 HAR-RV + EWMA 相关矩阵已有，主要是分解输出）。**验收**：每次减仓后不只知道"卖多少"，还知道"风险降了多少"。

### T23 路由后压力测试 `[B · 0.5 周]`

减仓路由完成后的情景重估：QQQ −5% / BTC −10% / VIX spike / 相关性升至 0.9。输出进 payload + T20 面板。

### T24 DEFCON 解释 + BRK.B↔BOXX 相关性可视化 `[A · 0.5 周]`

哪些条件把系统推到 DEFCON 1/2/3；BRK.B fallback BOXX 的相关性规则（>0.85）随时间的可视化。**验收**：路由不是黑箱，能解释为什么不是现金、不是 QQQ、不是 BTC。

### T25 远期池（不排期）

mirror 系统更深度融合（仅作参考输入，**不变硬决策**）；税务/洗售逻辑增强；broad breadth 真数据源（需付费/手工）。

---

## 6. 人工门清单（agent 准备，人类执行）

| 时点 | 动作 |
|------|------|
| T1/T2 | launchd plist 安装（`launchctl load`） |
| T9/T10 | `use_soft_data_max_age` / `use_full_confidence_spine` 翻闸 |
| T11 | 每次 deploy 的 config diff y/n |
| T17/T19/T21 | gate 通过后的 flag 翻闸；FAIL 的归档确认 |
| 全程 | 任何对 live config / .hermes 的写操作 |

---

## 7. 不做清单（双方合并，全量）

调 EXIT/DEFENSIVE_EXIT 阈值；A 模块新宏观因子（cap 饱和）；打开 decision_stabilizer / hysteresis（WF 否决）；NAAIM/PCR 收紧重试（全指标更差）；H-M2 缓冲重试（真实路径否决）；6 年窗口再做阈值扫描（局部最优已确认）；为 CAGR 放松硬阀门；mirror 变 escape-top 硬决策输入；任何自动/半自动下单。

---

## 8. 交付产物与成功指标

**产物**：本文档 + `EXPERIMENT_REGISTRY.md`（T15）+ `PRODUCTION_RUNBOOK.md`（T12）+ `BASELINE_2026_06_11.md`（T4）。

**成功指标**（对照 2026-06-11 评分）：

| 维度 | 现值 | 目标 | 主要贡献任务 |
|------|------|------|------|
| 数据新鲜度 | 6.0 | 8.5 | T1/T2/T9/T11/T18 |
| 可观测性 | 6.5 | 8.5 | T2/T5/T6/T10/T20 |
| 部署一致性 | 6.5 | 8.5 | T11 |
| 性能效率 | 6.0 | 7.5 | T8/T13 |
| 数据完备性 | 6.5 | 7.5 | T17/T18 +（T19 若过 gate） |
| 测试覆盖 | 7.5 | 8.0 | T7/T8/T20 冒烟 |
| 安全 | 8.5 | 9.0 | T7/T14 |
| **综合** | **7.8** | **8.5+** | — |

方法论侧的 9.5（防过拟合/可复现）不动——它们是护城河，不是优化对象。

---

## 附录：任务依赖图

```
T3(补跑)   T1(launchd) ──► T2(watchdog)
                │
                ├──► T5(preflight) ──► T6(post-run diff) ──┐
                │                                          │
T4(baseline)    T7(CI断言) ◄── T14(ssl修复)                 │
                │                                          ▼
T8(数据出git) ──┴──[S1]                          T20(仪表板) ◄── T10(脊柱接线)
                                                           ▲
T13(gate提速) ──[S2]──► T19(链上gate) ──► T21(arm-then-fire)│
                              ▲                            │
T16(链上离线) ────────────────┘        T9(SLO) ────────────┘
T17(mNAV) ──► gate排队           T11(deploy脚本) ──► T12(runbook)
T15(registry回填)                T18(PCR抓取)
T22/T23/T24 ◄── T20 之后
```
