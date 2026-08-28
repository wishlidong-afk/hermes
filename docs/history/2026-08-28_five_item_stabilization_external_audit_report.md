# 外审报告：Five-Item Stabilization

**审计日期**: 2026-08-28 | **审计方**: 独立外审（read-only） | **Baseline**: `ce96de01526dbb5a7bed84a2b9272b5c1c48da88` (`ce96de0`)

**Repository**: `/Users/liweishi/Documents/github/hermes` | **Branch**: `hermes-docs`

**Scope**: `git diff HEAD`（13 个已修改跟踪文件 + 1 个未跟踪审计提示文档）

---

## 1. Findings（按 P0→P3）

**P0 / P1 / P2: 无。**

**P3: 1 项 — 证据范围局限，非代码缺陷**

| # | 级别 | 描述 | 位置 |
|---|------|------|------|
| P3-1 | 证据范围 | `compare_pipeline_persistence.py` 的指纹根仅覆盖 `src/hermes_escape_top`，**结构上无法覆盖 `ops/morning_acceptance.py`**。Item 4/5 的"strict 四日期等价"证据只能证明 src/ 未变，不能证明 ops/ 行为等价。独立重跑确认：冻结基线树与工作树的 src/ manifest 完全相同（`b7cca676…`）。Item 4/5 的行为等价性实际由测试套件（+149 行场景测试）+ 逐行审阅背书，而非该 comparator。 | `scripts/compare_pipeline_persistence.py:36` |

---

## 2. Scope 与漂移判定

| 检查 | 结果 |
|------|------|
| Branch / Baseline | `hermes-docs` @ `ce96de01526d…` ✅ |
| 修改文件数 | 13 = 声明清单 13，逐名匹配 ✅ |
| Diff 规模 | +1329/-528 = 声明值 ✅ |
| 未跟踪文件 | 仅本审计提示文档 ✅ |
| 范围外文件 | 无 ✅ |

### 声明清单核对

生产/治理/文档（8）：`context.md`、`docs/FLAG_REGISTRY.md`、`docs/PRODUCTION_RUNBOOK.md`、`ops/morning_acceptance.py`、`scripts/check_governance_consistency.py`、`src/hermes_escape_top/core/data/source_relevance.py`、`src/hermes_escape_top/pipeline.py`、`src/hermes_escape_top/web/health.py` ✅

测试（5）：`test_governance_consistency.py`、`test_health_truth.py`、`test_morning_acceptance.py`、`test_phase1_data_flow.py`、`test_source_relevance.py` ✅

---

## 3. 命令/结果表（独立复现）

| 命令 | 声称 | 独立复现 |
|------|------|---------|
| 5 个变更测试文件（合成 `FRED_API_KEY`） | 111 passed | ✅ **111 passed** (1.90s) |
| 全套（合成 key） | 1392 passed | ✅ **1392 passed** (118.65s) |
| `scripts/check_governance_consistency.py` | 8/8 OK | ✅ **ok=true, 8 项**（含新 `current_facts_docs:OK`） |
| `compileall -q src scripts ops` | clean | ✅ PASS |
| Ruff severe `E9,F63,F7,F82`（10 文件） | clean | ✅ All checks passed |
| `git diff --check HEAD` | clean | ✅ PASS |
| 6 份 /tmp 证据 SHA-256 | 6 声明哈希 | ✅ 6/6 逐字节匹配 |
| Final strict 重跑（冻结基线） | all_equal=true | ✅ 独立重跑：**strict 契约, 4/4 equal, 零 strict_differences**（附 P3-1 范围注记） |

### /tmp 证据哈希核对

| 文件 | 声明 SHA-256 | 实测 |
|------|-------------|------|
| `hermes_current_facts_equivalence.json` | `2ef6bedf…` | ✅ 匹配 |
| `hermes-item2-health-equivalence.json` | `a952e02f…` | ✅ 匹配 |
| `hermes-item3-health-equivalence.json` | `833e77e3…` | ✅ 匹配 |
| `hermes-item4-equivalence.json` | `5b352d78…` | ✅ 匹配 |
| `hermes-item5-equivalence.json` | `b40700fb…` | ✅ 匹配 |
| `hermes-item5-final-verification.json` | `add4ade2…` | ✅ 匹配 |

---

## 4. 五区域判定

### Item 1 — current facts + source relevance ✅ PASS

- 独立 payload 逐字段 diff（ce96de0 基线 vs 工作树，2026-07-10）：**唯一**业务差异为 `data_quality_breakdown.sources[9].decision_bearing`（`cboe_indices`）与 `sources[14].decision_bearing`（`gex`）→ `False`；其余差异均为 volatile 元数据（时间戳/临时路径/`run_id`）。
- 两源均无有效 profile（`data_cboe_official_indices` / `data_gex` 均 disabled），`quality_penalty` 两侧均为 0.0 — 纯报告字段修正，零评分影响。
- `input_hash`、symbol status、factor scores 四日期全等。
- fail-closed 验证：
  - `unknown_future_source` → `decision_bearing=True`（未知源默认策略承载）；
  - `cot_nq`（inactive）→ `False`；
  - `occ_equity_pcr`（research）→ `False`；
  - `dollar` / `naaim_exposure` / `aaii_sentiment`（active strategy）→ `True`。
- Governance 第 8 项 `current_facts_docs`：`baseline.json` 实测 `git_commit=b23cf124b5b906d897884f2774d354b8cae23d1a`、`equity_timing=next_open`、`CAGR=15.56%`、`MaxDD=-20.83%`、`Sharpe=1.064` — 与 FLAG_REGISTRY 新文案精确一致；NAAIM 四状态（`ACTIVE_PUBLIC` / `ACTIVE_SUBSCRIBER` / `RETIRED_PAYWALL` / `PUBLIC_OFFICIAL_STABLE`）+ runtime ledger 权威文案已核对。行取向、fail-closed（缺失即 ERROR）。

### Item 2 — health evaluator 分解 ✅ PASS

- `_HealthEvaluator.evaluate()` 调用顺序 = 旧单体 11 规则顺序：scored payload → price freshness → manifest → market admission → data quality → soft sources → receipt → IBKR → SIP → external sources → certification。
- 顶层输出 = `strategy_data` level（陈旧 IBKR 不使策略不可用）；layer 集合不变；公共 payload shape 保留。
- strict 四日期等价 + 1382 测试（含 `test_compute_health_remains_a_small_facade`）。

### Item 3 — 准入解释分解 ✅ PASS

- shadow-support index（`_market_admission_shadow_support`）/ row formatter（`_format_market_admission_rejected_row`）/ volume formatter（`_format_market_admission_volume_diff`）三分；过滤、顺序、lookup key、截断未变。
- 组件级分类仍要求三计数一致 + 每行角色/影响元数据一致（`_market_admission_is_component_only` 逻辑未动）。

### Item 4 — 迁移观察分解 ✅ PASS

- 集中通道表 `_EXTERNAL_MIGRATION_AUTOMATIC_CHANNELS` 值与旧内联 dict **完全相同**（无拓宽）：`aaii_sentiment: {public_html, official_insights_rss}` / `naaim_exposure: {naaim_public_workbook, naaim_subscriber}`。
- 证据/政策/截止日/汇总四 helper（`_external_migration_evidence_issues` / `_external_migration_policy_issues` / `_external_migration_deadline_issues` / `_external_source_migration_summary`）逐条件核对一致。
- 缺失/malformed precheck → WARN（新测试 `test_external_source_migration_observation_warns_when_precheck_is_missing` 等覆盖）。
- 逐行确认 `status` / `evidence_status` / `freshness_status`（非退役）/ `precheck_date`（非退役）/ `official_issue_as_of` / SHA-256 指纹 / manual-channel / `ACTION_REQUIRED` / retired 不一致 / `MIGRATION_DUE` 前后期 全部语义保留。

### Item 5 — morning 健康策略分解 ✅ PASS

- 旧代码**本来就有** `_unique()` 去重 — 新四层 helper（`_strategy_health_policy` / `_position_health_policy` / `_operations_health_policy` / `_auxiliary_health_policy`）保持同序（strategy→position→operations→auxiliary）+ 同去重。
- Dollar 唯一允许策略警告 / IBKR stale→非阻断 INFO / operations CRITICAL→failure / auxiliary degradation→warning — 逐行核对未变。
- `test_health_policy_preserves_layer_order_and_classification` 锁定顺序与分类。

---

## 5. Safety Boundary

| 检查 | 结果 |
|------|------|
| `config.json` / `requirements.txt` / `requirements.lock` / `pyproject.toml` / `ci.yml` | 零 diff ✅ |
| CSV / DB / DuckDB / SQLite / Parquet / env / secret / token / key / pem / json | 零 diff ✅ |
| 生产代码 order path（`placeOrder|submitOrder|transmit=True`） | 零匹配 ✅ |
| live 路径注入 | 零 ✅ |
| IBKR readonly / feature flag / 评分阈值 / 路由 / 模块上限 | 未触碰（governance `ibkr_readonly=true`）✅ |

---

## 6. 十个审计问题 — 直接回答

1. **禁用已知源还能降低策略决策质量？** 不能。仅报告字段变化，penalty/评分/input_hash 字节相等。
2. **未知 soft record 会被静默视为非决策？** 不能。默认 fail-closed=True，实测验证。
3. **陈旧基线事实/过时 NAAIM 生命周期能过 governance？** 不能。第 8 项检查拒绝，测试锁定。
4. **compute_health 改变任何分支/顺序/层/schema？** 没有。顺序与 shape 保留 + strict 等价。
5. **畸形准入数据能获组件级待遇？** 不能。三计数 + 行元数据必须全一致。
6. **迁移重构拓宽通道或弱化证据检查？** 没有。通道集逐值相同，全部检查保留。
7. **健康策略重构改变顺序或允许例外？** 没有。同序、同去重、同 Dollar/IBKR/ops/auxiliary 语义。
8. **全部声称结果可独立复现？** 是。111 / 1392 / 8-8 / compile / ruff / 6-hash 全复现。
9. **config/flags/评分/路由/依赖/IBKR/下单/live/密钥有变？** 没有。全零 diff。
10. **有无阻塞理由？** 没有。

---

## 7. 残余风险判定

| 声明残余 | 我的判定 |
|---------|---------|
| C901 ×3（`_collect_release` 复杂度14 / `_collect_bound_health` 复杂度14 / `_market_admission_observation` 复杂度12） | ✅ 准确 — diff 中仅 hunk 头部锚点出现，函数体未动 |
| 行取向 prose 检查 | ✅ 准确 — 明确 fail-closed；文档表格重构必须同步 checker + 测试 |
| `_HealthEvaluator` 仍策略密集 | ✅ 准确 — facade 变小、类内规则仍多 |
| /tmp 等价证据易失 | ✅ 准确 — 非持久档案 |
| （新增）Item 4/5 等价证据范围 | ⚠️ 见 P3-1 — comparator 不指纹 `ops/`；作者未声称其证明 ops 行为，行为证明以测试为准 |

---

## 8. 最终判定

### **APPROVE R6 DEPLOY** ✅

代码审计与部署安全审计均通过：

- 评分路径字节级不变（独立 payload diff + strict 等价 + 1392 测试）；
- Governance 8/8 OK（含新增 `current_facts_docs` 检查）；
- 零 config / flag / 路由 / IBKR 变更；
- 无订单路径、无 live/secret 注入、无范围漂移。

### 部署纪律（若用户授权执行）

1. 避开北京时间 **07:00–07:20**；
2. 确认无 daily / refresh writer 活跃；
3. 保留 live config，走标准 R6 release/symlink 原子路径；
4. **禁止**以手动重跑官方 daily 作为部署验证；
5. 等待下一个自然调度 run + 09:10 morning acceptance 完成运行时认证。
