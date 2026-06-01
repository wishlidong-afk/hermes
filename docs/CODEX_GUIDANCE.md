# CODEX GUIDANCE — 下一步做什么（看这一个文件就够）

> 给 Codex 的明确施工指引。读完照做即可，无需翻其它文档（细节锚点已标）。
> 更新：2026-06-01，据真实进度账本。读者：Codex。

---

## 0. 现状一句话

- **78 单测绿；missing 已降到 MSTR 26 / FNGU 19 / SOXL 19 → 盲区门(<30)已过，M1 实质达成。**
- **当前唯一关键瓶颈：FNGU 价格历史只回到 2025-02-20（FNGS 到 2019-11-13）。** 这把回测有效窗口压到约 15 个月（2025-02→2026-05），只覆盖一个体制。
- 后果：NEXT-2 代码就绪但"窗口受限"，**NEXT-3 在 15 个月数据上做参数校准等于过拟合噪音，无意义。**
- 结论：**先解决 FNGU 历史，再谈回测/校准。** 这是当前唯一该做的第一件事。

---

## 1. 优先级（严格按此顺序）

```
P0  合成重建 FNGU(3×)/FNGS(1×) 的 2018+ 历史   ← 唯一阻塞，先做这个
P1  用 P0 历史把 NEXT-2 回测全窗口重跑（2018→2026）
P2  NEXT-3 参数扫描 + 每模块达标门 + PBO（报告对合成段敏感性）
P3  (并行) 补 NEXT-1 剩余软数据：PCR / NAAIM / BTC funding-basis-DVOL → 进一步降 MSTR 的 26
P4  整合地基：ConfidenceSpine / RiskEngine / SizingOptimizer（替换 scaler 乘法链）
```

> 不要先去补 GEX/CNN/social/valuation（那是 NEXT-4 向前数据，非阻塞）；不要在 15 个月窗口上跑 NEXT-3。

---

## 2. P0 工单（最高优先，函数级）

**目标**：把 FNGU、FNGS 缺失的早期历史用"底层指数/成分 + 日重置杠杆公式"合成出来，扩到 2018-01（或更早），并严格校验合成段与真实段在重叠期一致。这是 `leg_proxy.py`（路由腿代理）思路在**杠杆标的本体**上的延伸。

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

## 4. P2：NEXT-3 校准

- 在全窗口上跑 `param_sweep`（网格见 BUILD_TICKETS NEXT-3）；**选稳健高原非峰值**；walk-forward OOS + Deflated Sharpe + **PBO<0.5**。
- 写 `config/artifacts/calibration_vX.json`（chosen/oos_metrics/DSR/PBO/confidence_notes）。
- **诚实声明**：报告参数对"合成段(pre-2025 FNGU)"的**敏感性**——给出"只用真实段"与"含合成段"两套校准结果差异；差异过大则标低置信、保守取值。
- 每模块达标门（组合/vol目标/评分链/硬阀门）通过/不通过 + 证据 → `reports/Calibration_vX.md`。

## 5. P3（并行，非阻塞）：补剩余软数据

- 接 PCR(A2/B4)、NAAIM(A2)、BTC funding-basis-DVOL(D-M)；目标把 MSTR 的 26 进一步降低、提升数据质量分。
- 全部经 PIT 对齐、offline 0 外呼、缺则 missing 不补 0。非阻塞，可与 P1/P2 并行。

## 6. P4：整合地基（基线达 M3 后）

- 按 `INTEGRATION_ARCHITECTURE.md` Phase 0–I 建 ConfidenceSpine / RiskEngine / FactorLab / MarketContext / ValidationHarness 骨架 + SizingOptimizer。
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
