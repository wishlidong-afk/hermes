# T1 · 特征层差异图(为什么 status 对不齐)+ T2 对齐工单

> **日期：2026-06-02** ｜ T1 目标:建同输入桥,把 T5 的 status 缺口(44% 一致)归因到具体 module/字段。
> **结论(重要)**:status 对不齐的根因**不是阈值,而是"计算口径"——单体与包在 module B/C
> 计算的是部分不同的特征**。所以"byte-identical 输入"在对齐特征定义(T2)之前根本无法达成。

## 方法

用单体自己的 `build_dataset(raw, state)` 取它**实际评分用的**每标的字段集(sandbox 读 fixtures),
对照包各 module 评分实际 `ctx.get(...)` 读取的字段,逐字段分类:ALIGNED / 改名 / 定义不同 / 缺失 / 结构不同。

## 特征层差异图

| Module | 包需要 | 单体提供 | 类型 | 影响 |
|---|---|---|---|---|
| B | `rsi14`(单一) | `rsi14_daily` + `rsi14_weekly`(拆分) | **定义不同** | B1 过热判定口径不同 → 直接影响 status |
| B | `SOFT.vvix_pctl` / `skew_index` / `skew_pctl` | — 无 | **缺失** | B4 期权压力在包侧拿不到输入 → 分歧 |
| C | `avwap_60d` | `estimated_avwap_20d`(20≠60) | **窗口不同** | AVWAP 锚定窗口不同 → C 模块分歧 |
| C | `support_60d_low` / `support_distance_60d_pct` | `platform_support_level` | **定义不同** | 支撑位定义不同 |
| C | `chandelier_exit`(单一) | `chandelier_exit_22_3x` + `_22_4_5x`(两条) | **重命名/选型** | 需定用哪条(3x/4.5x) |
| D | `SOXX.*`(独立快照) | 每标的内嵌 `radar` 字段 | **结构不同** | 雷达标的的取数结构不同 |
| A | `SOFT.naaim_*`/`equity_pcr_*`/`aaii_*`/`aggregate_*`/`QQQ.cmf20`/`mfi14`/`ad_slope20` | 部分有(market/soft),命名/命名空间需逐一核 | **混合** | 软数据命名空间(`SOFT.`)与单体扁平命名需映射 |
| — | close / ma50/150/200/220 / ema20/50 / return_2d / drawdown_60d_high_pct / distribution_days_25d / realized_vol20 | 同名同义 | **ALIGNED** | 这些不是问题 |

## 关键结论

1. **硬阀门 100% 对齐**(T5 已证),安全门 OK。
2. **status 44% 不一致的根因 = module B、C 的特征"计算口径"不同**(rsi 单/双、avwap 窗口、
   支撑定义、chandelier 选型),外加 module B 的期权压力软字段在单体侧缺失、module A 的软数据命名空间需映射。
3. **不是阈值问题**——即便把阈值对齐,只要特征定义不同,status 仍会分歧。
4. 因此"byte-identical 输入桥"在 T2(特征定义对齐)之前不可能真正达成;T1 的产出就是这张**对齐清单**。

## T2 对齐工单(逐项,owner 决定哪边为准)

- **T2-B1**:统一 `rsi14`——包用单一 RSI,单体用 daily+weekly。定:包是否引入 weekly RSI,或单体并入单一口径。
- **T2-B4**:把 VVIX/SKEW 期权压力软字段接进单体 `daily_raw_data`(或确认包侧降级处理)。
- **T2-C-avwap**:统一 AVWAP 窗口(20d vs 60d)。
- **T2-C-support**:统一支撑位定义(`support_60d_low` vs `platform_support_level`)。
- **T2-C-chandelier**:定 chandelier 用 3x 还是 4.5x(注意:硬阀门用的是 4.5x)。
- **T2-D-radar**:统一雷达标的取数结构(独立 SOXX 快照 vs 内嵌 radar)。
- **T2-A-soft**:软数据命名空间映射表(`SOFT.x` ↔ 单体扁平名)。
- **完成后**:重建 T1 同输入桥(此时特征已统一)→ 跑 parity harness,status 应趋近 100%,
  剩余差异即纯阈值/代码,再逐一消除。

## 下一步

T2 每一项都需 owner 决定"以哪边的口径为准"(这是产品/风控判断,不该我替你定)。
建议从 **T2-B(rsi + 期权压力)** 入手,因为 module B 直接驱动了 T5 观察到的 WATCH↔HOLD 翻转。
我可以为选定的某项做"两边口径并排 + 改动方案",但"定哪边为准"需要你/风控拍板。
