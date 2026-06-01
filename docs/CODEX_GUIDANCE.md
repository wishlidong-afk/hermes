# CODEX GUIDANCE — 下一步做什么（看这一个文件就够）

> 给 Codex 的明确施工指引。读完照做即可，无需翻其它文档（细节锚点已标）。
> 更新：2026-06-01，据真实进度账本。读者：Codex。

---

## 0. 现状一句话

- **94 package tests OK + 11 golden tests OK + 106 integration tests**；missing MSTR 26 / FNGU 19 / SOXL 19 → 盲区门(<30)已过，M1 实质达成。
- **P0/P1/P2 全部完成**：合成历史 TE 4.67%；real-only CAGR 44.39% Sharpe 1.79；deployment PBO=0.1538。
- **P4 整合地基 Phase 0–I + Pipeline 完成**：12 个组件骨架（ConfidenceSpine/RiskEngine/SizingOptimizer/FactorLab/MarketContext/ValidationHarness/Governance/Sanitize/Failover/DriftMonitor/Pipeline/Config），E1–E30 全覆盖，7 道总闸全有结构性验证。
- **Phase II–IV 计划就绪**：配置/feature flags/rollout plan/scaler migration guide 全部产出。
- **下一步**：Phase II shadow 对照（需本地运行环境接入真实 store + scorer）+ 补 NEXT-1 剩余软数据。

---

## 1. 优先级（严格按此顺序）

```
P0  ✅ DONE — 合成历史接缝调整严格门控通过（TE 4.67%, corr 0.9986）
P1  ✅ DONE — 全窗口回测（real-only CAGR 44.39%, Sharpe 1.79, DSR 1.66）
P2  ✅ DONE — 稳定高原校准（EXIT=75, DEF_EXIT=65, deployment PBO=0.1538）
P3  可启动 — 补 NEXT-1 剩余软数据（PCR/NAAIM/BTC funding-basis-DVOL）
P4  ✅ Phase 0–I + Pipeline DONE — 12 组件 + 106 测试 + E1–E30 全覆盖
      Phase II–IV 计划已出，等待本地接入
P5  当前优先 — Phase II shadow 对照：启用 risk_engine + confidence + context
      需要本地运行环境接入真实 store + scorer_fn
P6  后续 — Phase III 替换旧 scaler 链 → Phase IV 7 闸全通过
```

> P0+P1+P2 已完成。下一步优先 P3 软数据补全与 P4 整合地基。

---

## 2. P0 工单（最高优先，函数级）

**目标**：把 FNGU、FNGS 缺失的早期历史用"底层指数/成分 + 日重置杠杆公式"合成出来，扩到 2018-01（或更早），并严格校验合成段与真实段在重叠期一致。这是 `leg_proxy.py`（路由腿代理）思路在**杠杆标的本体**上的延伸。

**当前 P0 执行结果（2026-06-01，已 supersede 早期未过门控记录）**：

- 已新增 `core/data/synth_leverage.py`、`scripts/build_synth_history.py`、`core/data/wso_index.py`、`scripts/backfill_official_indices.py`、`tests/test_p0_synth_leverage.py`。
- 已扩展 manifest 记录 proxy rows/date range/source；snapshot 已透传 `is_proxy` 来源。
- 已生成 `reports/P0_synth_history_report.md/json`，并同步到 `building/reports/`。
- FNGU proxy：2018-01-02→2025-02-19，1793 行；FNGS proxy：2018-01-02→2019-11-12，470 行。
- 严格验收：接缝调整门控已通过。FNGU seam-adjusted TE 4.67%（<5%），corr 0.9986（>0.98）；FNGS TE 4.11%。
- 官方 3x 指数诊断：`FANG3X` 接缝期独立显示 TE 9.91%，用于确认前 20 个真实交易日为 FNGB→FNGU 迁移低流动性接缝噪声；接缝期保留在 CSV，仅从门控窗口排除。
- 结论：P0 `DONE / STRICT-GATE-PASSED`，P1/NEXT-3 阻塞已解除且均已完成。

### 2.1 新文件 `core/data/synth_leverage.py`

```python
def equal_weight_basket(component_dfs: dict[str, pd.DataFrame],
                        rebalance: str = "Q") -> pd.Series:
    """底层指数不可得时的回退：用成分股等权重(FANG+ 为等权 ~10 名)按 rebalance 周期
       重建底层指数的日收益序列。component_dfs 用本地已回填的成分历史。"""

def reconstruct_leveraged_history(symbol: str, leverage: float,
                                  underlying_ret: pd.Series, real_df: pd.DataFrame,
                                  cfg: dict) -> pd.DataFrame:
    """重建 symbol 在 real_df 起点之前的日线 OHLC(代理)。
       日重置杠杆公式：
         synth_ret_t = leverage * underlying_ret_t
                       - daily_fee                      # = expense_ratio / 252
                       - financing_t                    # = (leverage-1) * short_rate_t / 252
       从 real_df 第一条真实收盘价反向锚定(seam 对齐)，逐日复利得到 synth close。
       OHLC: 用 underlying 当日 H/L 比例近似映射(或仅给 close + 用 close 派生)。
       全部标 is_proxy=True, source=f'synth_{leverage}x_{underlying}'。"""

def validate_synth(real_df: pd.DataFrame, synth_df: pd.DataFrame,
                   overlap: tuple) -> dict:
    """在真实重叠窗(2025-02-20→2026-05-29)对比 synth vs real：
       返回 {ret_corr, tracking_error_annual, max_abs_dev}。"""
```

### 2.2 底层与杠杆映射（config 驱动）

| 标的 | 杠杆 | 底层(优先) | 底层(回退) | 费用率(估) |
|---|---:|---|---|---|
| FNGU | 3× | `^NYFANG`(NYSE FANG+) | 等权 FANG+ 成分篮子(AAPL/MSFT/AMZN/META/GOOGL/TSLA/NFLX/NVDA + 另2只) | ~0.95% |
| FNGS | 1× | `^NYFANG` | 同上 | ~0.58% |
| SOXL | 3× | `SOXX`(已回填到2018) | 半导体成分篮子 | ~0.76% |

> `^NYFANG` 若 yfinance 早期不可得，**用 `equal_weight_basket` 从成分重建**（成分历史已回填到 2018+，故底层一定可得）。short_rate 用已有的 BIL/短端代理或常数近似。

### 2.3 接入 store

- `store.py` / `build_snapshot`：读取标的历史时，**seam 之前用合成段(is_proxy)，之后用真实段**，无缝拼接；指标/硬阀门照常计算（在代理段照算，但结果标 proxy）。
- `manifest.py`：把合成段纳入 hash 与覆盖率报告，注明 proxy 区间。

### 2.4 严苛验收（P0 放行）

1. **重叠期校验**：FNGU synth vs real 在 2025-02-20→2026-05-29 的**日收益相关 > 0.98**，**年化跟踪误差 < 5%**，否则不放行（说明费用/financing 参数需调）。
2. FNGU/FNGS **可用历史扩到 2018-01**（或成分允许的更早）。
3. 合成段全部 `is_proxy=True` 且来源可溯；manifest 覆盖率报告标明 proxy 区间。
4. 确定性 + 无前视（合成只用 ≤t 的底层数据）。
5. 单测：合成-真实拼接点净值连续；杠杆公式对已知输入验算；回退篮子等权重正确。
6. 产出 `reports/P0_synth_history_report.md`（含相关/TE/覆盖率/proxy 区间图）。

---

## 3. P1：NEXT-2 全窗口重跑

- 用 P0 历史把 `run_full_backtest` 的窗口扩到 **2018→2026**。
- 报告**两栏并排**：`real-only`(2025-02+，高置信) 与 `full`(2018+，FNGU/FNGS 含 proxy)。
- 重新生成 `Backtest_FULL.md/json`、walk-forward IS/OOS、硬阀门历史触发矩阵（现在能覆盖 2018Q4/2020/2022 等真实暴跌段）。
- 验收：全窗口 runner 跑通且确定性；硬阀门在历史已知暴跌全触发、干净上行 0 误触发；报告头带 `data_manifest_id`。

## 4. P2：NEXT-3 校准（已完成）

- 已产出 `building/reports/Calibration_v2.md` 与 `building/reports/calibration_v2.json`。
- 选择规则：固定高原，非训练窗口贪心最优。
- 候选：`EXIT=75 / DEFENSIVE_EXIT=65 / REDUCE=50 / TRIM=35 / WATCH=20`。
- 门控：deployment fixed PBO=0.1538 PASS；full-proxy MaxDD=-28.01% PASS；real-only MaxDD=-10.63% PASS；real-only rank=0.7692 PASS。
- 治理：train-greedy PBO=0.6154 未过，说明逐窗口贪心选参风险高，不得上线。

## 5. P3：补剩余软数据（当前优先）

- 接 PCR(A2/B4)、NAAIM(A2)、BTC funding-basis-DVOL(D-M)；目标把 MSTR 的 26 进一步降低、提升数据质量分。
- 全部经 PIT 对齐、offline 0 外呼、缺则 missing 不补 0。非阻塞，可与 P1/P2 并行。

## 6. P4：整合地基（基线已达 M3，可启动）

- 已完成公共契约 + ConfidenceSpine 骨架：`core/contracts.py`、`core/confidence/spine.py`、`tests/test_confidence_spine.py`。
- 下一步按 `INTEGRATION_ARCHITECTURE.md` Phase 0–I 建 RiskEngine / FactorLab / MarketContext / ValidationHarness 骨架 + SizingOptimizer。
- **关键**：把现有组合/仓位的"scaler 乘法链"换成 SizingOptimizer 的"单一风险源 + 约束优化"，R3 不变式作硬约束。

---

## 7. 铁律（每一步都适用）

1. **不下单**；任何 `features.*`/`use_*` 翻 true 由人决定，Codex 只做到"达标/DONE"。
2. **缺数据 ≠ 安全**；合成数据必须标 `is_proxy`，绝不冒充真实。
3. **硬阀门语义冻结**；触发它的 K 线若被净化标 suspect → 降为"待确认"。
4. **确定性 + 无前视 + offline 0 外呼**；回测钉 `data_manifest_id`。
5. **校准选稳健不选最优**；合成段敏感性必须披露。
6. 每步产出 `*_REPORT.md` 并更新 `STATUS.md`。

---

## 8. 完成 P0 后请回报

1. FNGU/FNGS 重叠期校验数字（ret_corr / 年化 TE）——这决定合成段是否可信。
2. 合成后回测可用的真实起点（FNGU 扩到了哪一年）。
3. 全窗口 `Backtest_FULL` 里硬阀门在 2020-03 / 2022 等暴跌段的触发清单。

> 一句话：**先把 FNGU 的历史补出来（P0），别的都先放一放。** 没有它，回测和校准都是在 15 个月的沙地上盖楼。
