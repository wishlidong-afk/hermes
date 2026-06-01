# 01 · FUNCTIONAL SPEC（功能规格 · 事实源）

> 系统"怎么判"的单一事实源。源自原《逃顶与镜像系统逻辑说明 v2.5》，并标注 v3 修正点（修正点的施工细节见 BUILD_TICKETS / ENHANCEMENTS / INTEGRATION_ARCHITECTURE）。
> 实现要求：纯函数、缺数据走 missing_weight、确定性、无前视。

---

## 1. 覆盖标的与定位

| 标的 | 定位 | 主雷达 | 袖珍上限 |
|---|---|---|---:|
| MSTR | BTC 高 beta / 高波动进攻 | MSTR 自身 + BTC-USD | 15% |
| FNGU | FANG+ 三倍杠杆 ETN | QQQ + FNGS / ^NYFANG | 20% |
| SOXL | 半导体三倍杠杆 ETF | QQQ + SOXX/SMH/^SOX | 30% |

镜像策略：QQQ/FNGU(上限20%)、SOXX/SOXL(30%)、MSTR/QQQ(15%)。

---

## 2. 数据源

- **行情(yfinance 日线)**：交易标的 + QQQ/SPY/^VIX/^VIX3M + 雷达资产 + 成分篮子（FNGU 9 只 / SOXL 10 只）。
- **情绪/宏观/宽度/期权**：CBOE Equity PCR、CNN Fear&Greed、AAII、NAAIM、NDX 50/200DMA 宽度、FRED(DXY/10Y/TGA/HY OAS)、期权链(PCR/OI PCR/IV Rank/Call Wall)、新闻/社交热度。
- **估值**：MSTR mNAV 溢价分位、FNGU FANG+ forward PE 分位、SOXL SOXX/SMH forward PE 分位。分位打分 ≥95→5 / ≥90→3 / ≥80→2 / ≥70→1 / <70→0。
- **IBKR 持仓**：股数/市值/成本/未实现/NetLiq；离线读快照。
- **底层资金流**：v2.5 用 `signed dollar volume = sign(close−prev)·close·volume` 的 5/10 日篮子汇总。

> **v3 修正**：①资金流升级为 CMF/MFI/AD（E3 在 BUILD_TICKETS N1-T07 等，弱代理降权）。②净流动性补 RRP：`net_liq=WALCL−WTREGEN−RRPONTSYD`。③补 SKEW/VVIX/期权偏度/GEX/BTC 资金费率·基差·DVOL。④可历史化软数据按发布日(PIT)对齐回填，降 missing_weight。

---

## 3. 评分模块（A/B/C/D）

模块封顶：**A=20 / B=25 / C=35 / D=20**。标的差异化加权后归一化百分制：
```
weighted_score = Σ(module_score · symbol_module_weight)
weighted_max   = Σ(module_cap   · symbol_module_weight)
final_score    = weighted_score / weighted_max × 100
```
标的模块权重：MSTR 0.90/0.95/1.00/1.25 · FNGU 1.10/0.90/1.10/1.05 · SOXL 0.90/0.95/1.15/1.25。

### A 模块（大盘背景/宏观流动性/情绪，≤20）
A1 VIX 极端 · A2 情绪/PCR 过热(CNN/AAII/NAAIM/Equity PCR) · A3 NDX 宽度 · A4 QQQ 技术拉伸 · A5 宏观/信用收紧(TGA/DXY/10Y/HY OAS；**v3 改净流动性含 RRP**) · A6 底层资金异常流出(**v3 改 CMF/MFI/AD**) · A7 VIX 期限结构(VIX/VIX3M；**v3 加 VVIX**) · A8 市场派发日。
> A≥12 高亮；A1/A5/A7/A8 是资金路由核心宏观因子；宏观核爆须结合 QQQ 趋势确认。

### B 模块（个股/杠杆/估值过热，≤25）
B1 RSI 过热(日/周) · B2 EMA 偏离 · B3 涨幅/放量高潮 · B4 期权投机(PCR/IV Rank/Call Wall；**v3 加 SKEW/VVIX/GEX**) · B5 社交/新闻热度 · B6 PE/mNAV 估值分位。
> 升级规则：B6≥3 且 B1≥2 且 B2≥2 → 防守级别 +1。

### C 模块（技术破位/动能/派发，≤35）
C1 EMA 跌破 · C2 MACD 衰减 · C3 10 日派发 · C4 反转K线/长上影 · C5 相对强弱背离 · C6 急跌确认 · C7 AVWAP/平台支撑 · C8 25 日派发压力 · C9 ATR 吊灯(Chandelier 22 日 ×4.5) · C10 超级趋势因子(EMA50 跌破3 + Minervini 破坏4 + Weinstein 破 MA150/MA200 3，合并降维防共线性，≤10)。

### D 模块（标的专属风险，≤20）
- **MSTR**：D-M1 MSTR/BTC 背离(60日 z) · D-M2 BTC 本体 · D-M3 mNAV 溢价 · D-M4 加密杠杆(**v3 加资金费率/基差/DVOL**) · D-M5 内部人/资本事件。
- **FNGU**：D-F1 FANG+ 宽度 · D-F2 QQQ/FANG 趋势 · D-F3 巨头领导力背离 · D-F4 财报/指引新闻 · D-F5 ETN/杠杆损耗 · D-F6 龙头资金流背离。
- **SOXL**：D-S1 半导体宽度 · D-S2 龙头背离 · D-S3 SOXX/QQQ 转弱 · D-S4 政策/新闻 · D-S5 SOXL 杠杆损耗 · D-S6 龙头资金流背离。
- SOXL 越权：`D-S2≥4 且 C5≥3` → 最低 TRIM；D 总分≥10 → 警戒连升两级。

---

## 4. 缺数据处理（缺数据 ≠ 安全）

- **缺失权重**（部分）：history/close/ma200=100；A2 情绪 2–4；A3 宽度 4；A5 宏观 4；A6 资金流 4；A7 VIX 期限 2；A8 派发 4；B4 期权 6；B5 社交 4；B6 估值 5；C7 支撑 4；D 专属 3–5。
- **缩放**：`effective_max=100−missing_weight`；`adjusted=raw/effective_max×100`。
- **盲区**：`missing_weight>30` → 触发盲区惩罚 + 防守级别 +1；关键数据缺失 → `DATA_BLOCKED`。
- **数据质量**：完整度 50% + 质量 30% + 延迟 20%；signed-dollar 代理每源扣 2，期权链 yfinance 扣 1、代理标的扣 3，AAII 手工扣 1.5，代理推算每项扣 3(≤12)，延迟按天扣。

---

## 5. 最终裁决

状态阶梯：`HOLD < WATCH < TRIM < REDUCE < DEFENSIVE_EXIT < EXIT`
阈值：≥80 EXIT / ≥65 DEFENSIVE_EXIT / ≥50 REDUCE / ≥35 TRIM / ≥20 WATCH / <20 HOLD

卖出比例：

| 状态 | MSTR | FNGU/SOXL |
|---|---:|---:|
| TRIM | 25% | 35% |
| REDUCE | 50% | 60% |
| DEFENSIVE_EXIT | 75% | 85% |
| EXIT | 100% | 100% |

**升级规则**：红灯≥4 / C≥18 / (B≥18 且 C≥12) / 杠杆标的遇 QQQ 破 EMA20 / (估值+RSI+EMA 组合) / 缺失>30 / SOXL 龙头背离。
**行动稳定器**：非硬阀门升级需第二个收盘确认；否则保留上一已确认级别。硬阀门不等待。

> **v3 修正**：①阈值由分数→概率校准(E2)。②裁决叠加滞回(进/出不同阈值)抑制抖动。③盲区/漂移/分歧拉低 confidence → DEGRADED 保守模式(置信脊柱)。

---

## 6. 硬阀门（触发即 EXIT 100%，优先于总分）

**MSTR**：H-M1 收盘≤MA200 · H-M2 单日≤−15% 且低于 EMA10 · H-M3 两日≤−22% · H-M4 BTC 破 MA50 且 MSTR 连续两日低于 EMA20 · H-M5 总分≥80 且 C≥5 · H-M6 破 Chandelier(22,4.5) 低于 EMA20 且 60日回撤≥18%。
**FNGU**：H-F1 QQQ≤MA200 · H-F2 FNGS/^NYFANG≤MA200 · H-F3 单日≤−15% · H-F4 两日≤−22% · H-F5 QQQ 或 FNGS 连续三日低于 EMA50 · H-F6 破 Chandelier 低于 EMA20 且 60日回撤≥12% · H-F7 QQQ 破 EMA50 + 25日派发≥5 + VIX 曲线压力。
**SOXL**：H-S1 QQQ≤MA200 · H-S2 SOXX/SMH/^SOX≤MA200 · H-S3 单日≤−15% · H-S4 两日≤−22% · H-S5 SOXX/SMH 连续三日低于 EMA50 · H-S6 60日回撤≥25% 且收盘低于 EMA50 · H-S7 破 Chandelier 低于 EMA20 且 60日回撤≥12% · H-S8 QQQ 破 EMA50 + 25日派发≥5 + VIX 曲线压力。

> **v3 安全护栏**：硬阀门为纯函数（histories 注入，无隐式 IO）；触发它的 K 线若被数据净化标 `suspect`，降为"待确认"防假摔（E1）；必须有"历史已知暴跌全触发 + 干净上行 0 误触发"测试。

---

## 7. 资金路由（REDUCE/DEFENSIVE_EXIT/EXIT 或任一硬阀门触发后）

匹配 `DEFCON 1 → 2 → 3`，命中即止：
- **DEFCON 1 宏观核爆 → BOXX**：A≥12 且 QQQ 破 EMA20/EMA50/MA200 之一；或 A1+A5+A7+A8≥8；或 A1/A5/A7/A8 单项≥4 且 QQQ 趋势确认。
- **DEFCON 2 内部破位/高低切 → BRK.B**：A≥12 但 QQQ 未破位；或 D≥10；或任一硬阀门；或 C8≥3；或 C6≥3。
- **DEFCON 3 常规降维 → 1x**：SOXL→SOXX、FNGU→QQQ、MSTR→QQQ。

> **v3 修正**：DEFCON1 加趋势/管理期货腿(危机 alpha)；DEFCON2 的 BRK.B 加自 beta 监测（跌破自身 MA200 或与大盘高相关→降级 BOXX/短债）；输出 routing_explain。

---

## 8. 3-3-4 再建仓审计

**Phase 0 三锁（须同时满足）**：时间锁(距上次卖出≥11 交易日) + 情绪锁(逃顶总分<19) + 结构锁(C<5 且背离解除)。有卖出信号或硬阀门则强制锁定。
- **T1 侦察 30%**：雷达收盘>EMA20 + MACD 零轴附近金叉；止损参考突破前平台低点。
- **T2 确认 30%**：T1 浮盈 + 雷达突破近 20 日最高收盘 + 价在 EMA20 上方；止损上移 T1 成本/EMA20。
- **T3 主力 40%**：T1/T2 浮盈 + QQQ 或 SPY 创 252 日新高；否则 T3 留 BOXX/QQQ。

---

## 9. 镜像参考系统（右侧周期参考，无硬阀门，不下单）

数据：yfinance 460 日 + IBKR + SQLite 快照。指标：EMA20/50、MA200、RSI14、MACD、5/10 日收益、量比、连涨、25 日派发、ATR14、Chandelier(22,4.5)、20/60 日回撤、SOXX 相对 SPY。
公式：`portfolio_pct = internal_pct × sleeve_cap`。

- **QQQ/FNGU**：风险预警(VIX>30 或 QQQ<EMA20)→QQQ50/FNGU0/现金50；强趋势→50/50；弱趋势→80/20；震荡→100/0。
- **SOXX/SOXL**：衰退→SOXX30/现金70；震荡→100/0；强繁荣(>MA200 且连涨≥5)→40/60；弱繁荣→50/50。
- **MSTR/QQQ**：风险预警(MSTR<EMA20 或 BTC<EMA50 或 60日回撤≥25%)→QQQ50/MSTR0/现金50；主升浪(检查≥8 且连涨≥3)→QQQ40/MSTR60；右侧上行→QQQ65/MSTR35；高波震荡→QQQ100/MSTR0。

每次刷新写 SQLite 快照（as_of/strategy/cycle/risk/action/target/payload）+ 后验理想盈亏（现金腿 0 波动）。

---

## 10. 后验与理想盈亏

记录所有 TRIM/REDUCE/DEFENSIVE_EXIT/EXIT 信号入 signal journal；统计 5/10/20 日后收益、20 日命中率、理想建仓盈亏（最新/上一交易日重估，现金/BOXX 0 波动）。

> 本节是 v3 元模型(E系列/NEXT-5)的弹药来源：回放 backfill 把历史信号转成带标签训练集。

---

## 11. v3 修正点速查（指向施工文档）

| 修正 | 位置 |
|---|---|
| 资金流 CMF/MFI/AD、净流动性含 RRP、SKEW/VVIX/GEX/BTC 微观 | BUILD_TICKETS NEXT-1/4 |
| 滚动分位自校准、概率校准阈值 | ENHANCEMENTS E2、INTEGRATION FactorLab |
| 相对基线波动率目标 + R3 末位 clamp | INTEGRATION SizingOptimizer |
| 组合层总风险预算(相关/CVaR/风险贡献/因子暴露) | INTEGRATION RiskEngine、ENHANCEMENTS E4/E11/E13/E14 |
| 体制非对称滞回、转换预警 | ENHANCEMENTS E7、MarketContext |
| 硬阀门净化护栏、漂移/分歧/熔断 | ENHANCEMENTS E1/E9/E10、ConfidenceSpine |
| 回测 walk-forward/CPCV/PBO/DSR | BUILD_TICKETS NEXT-2/3、ENHANCEMENTS E21/E22 |
