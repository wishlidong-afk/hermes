# 决策落地（2–10）+ v25 Golden 审计

> **日期：2026-06-02** ｜ 用户已授权按建议推进 2–10。本文记录每项的落地结果与依据。

## 决策落地

| # | 决策 | 落地 |
|---|---|---|
| 2 | 旧引擎退役时机 | **迁移验收后退役**;现保留作回测 baseline 对照(`run_full.py`/`phase2`)。活路径已单一源。 |
| 3 | Kelly | **保持关闭**(默认 `enabled=False`;启用须显式校准 `p_act`,否则报错)。 |
| 4 | mu 模式 | **保持 `proxy`**(已全窗口验证);`historical_tilt` 留作 opt-in,待单独回测。 |
| 5 | E7 fragility / E22 disagreement | **维持 0.0 占位**;需求见下「后续需求」。 |
| 6 | failover | **维持单源**;数据层未接 `FailoverSource`,`{"is_degraded":False}` 是事实。需求见下。 |
| 7 | v25 golden | **已查根因 + 重生成**(详见下「Golden 审计」)。 |
| 8 | 遗留 `core/` 重复树 | **保留**(仅被 v25 golden 用)。 |
| 9 | repo 补全为可安装包 | **维持现状**(实盘=`.hermes`,repo=镜像 + tracked 历史)。 |
| 10 | `.hermes` 改动留痕 | `.hermes` 整个 skill **本就不被其 git 跟踪**(0 文件 tracked,非 ignore)。留痕已由 **GitHub repo `src/`**(tracked,多次提交)+ 本地 `.review_backup_*`(可回滚)承担;不做凌乱的部分 git-add。 |

## v25 Golden 审计（决策 #7）

**根因**:`test_v25_parity` 测的是独立单体 `scripts/escape_top_system.py`(非我修的包)。
golden 于 2026-06-01 用更早的代码/环境冻结,之后单体演进(P16–P18)+ 环境升级
(numpy 2.4)使中间量漂移。

**重生成前的尽职核查(非破坏性,temp 对比)**:
- **确定性**:连续两次重生成**逐字节一致** → 当前代码确定,失配纯属"golden 来自旧码"。
- **决策影响**:跨所有公共日期×标的,**status 翻转 0 次、sell_pct 翻转 0 次**;
  `destination`/`protocol_step`/`reason` 全部一致。
- **数值漂移幅度**:`total_score`/`calibrated_score` 最大 |Δ|≈3.74,`raw_score`≤4.0;
  `qqq_ema*` 仅 ~1e-9 浮点级。
- 采样窗口从 5 日扩到 6 日(生成器按数据时钟取近端,非缺陷但不可复现——已记后续项)。

**结论**:重生成是**决策中性的重基线**(0 决策翻转),安全且已授权 → 已重生成。
**全套测试现 316 passed / 0 failed。**

> 提示给 owner:分数级 ~4 分的漂移虽未改决策,值得单体 owner 顺带看一眼是何改动导致;
> 并建议把生成器的"滑动采样窗口"改为固定日期集,以便 golden 可长期复现。

## 后续需求（被推迟项的"开工说明书"）

**E7 fragility（脆弱度)**:衡量"组合对单点冲击的敏感度"。可由 RiskEngine 已有的
`risk_contributions` 集中度(如最大单腿 RC 占比)或尾部相关骤升推导,归一到 [0,1]
喂 `compute_confidence(fragility=...)`。需定义阈值并加单测。

**E22 disagreement(模型分歧)**:衡量"多视角信号不一致度"。当前只有规则评分一条线;
需先有第二来源(如 FactorLab 校准概率 vs 规则分,或镜像系统 vs 逃顶系统的方向)才能算分歧。
属功能开发,需设计。

**failover 真信号**:`collect_soft_data` / 各 adapter 需经 `FailoverSource` 路由,
fetch 时返回 `FailoverResult.is_degraded` + `active_source_rank`,再喂脊柱。

**全网格 exact PBO**:7×3 场景 exact 跑(~5h,后台进行中),得到有意义的 `train_greedy_pbo`
/ `fixed_candidate_pbo`,作为 110/0.90 接受与否(决策 #1)的依据。
