# P4 E27 税务/洗售感知模块执行日志

更新时间：2026-06-01

## 目标

补完 E1–E30 最后一个缺口（E27），从"接口预留"升级为完整骨架。实现洗售检测、税务批次优化和税后收益估算，供 SizingOptimizer 的 execution_plan 做 tie-break。

## 已完成

### `core/portfolio/tax.py`

| 函数 | 功能 |
|---|---|
| `wash_sale_check(symbol, sell_date, recent_trades, substantially_identical)` | IRS 30 天洗售规则检测：向前+向后 30 天窗口内是否买入相同/实质相同证券 |
| `tax_lot_optimize(lots, shares_to_sell, current_price, method)` | 税务批次选择：HIFO（最高成本优先，最大化损失抵扣）/ FIFO / SPECIFIC |
| `after_tax_return(pretax_gain, short_term_rate, long_term_rate, is_short_term)` | 税后收益估算，供执行计划 tie-break |

### 数据类

- `TaxLot`：symbol / shares / cost_basis / acquired / is_short_term
- `WashSaleCheck`：is_wash_sale / reason / blocked_loss / lookback_sells
- `TaxLotRecommendation`：lots_to_sell / realized_gain / short/long_term_portion / method

### 测试（13 个）

| 测试 | 覆盖 |
|---|---|
| 无近期买入 → 不触发 | 正常 |
| 30 天内买入 → 触发 | 洗售检测 |
| 窗口外买入 → 不触发 | 边界 |
| 实质相同证券 → 触发 | 洗售扩展 |
| 卖出操作不触发 | 逻辑 |
| HIFO 选最高成本 | 批次优化 |
| FIFO 选最早 | 批次优化 |
| HIFO 最大化损失 | 核心价值 |
| 空批次 | 边界 |
| 短期/长期分拆 | 税务分类 |
| 收益被征税 | 税后计算 |
| 损失不征税 | 税后计算 |
| 长期税率更低 | 税后计算 |

## 设计决策

1. **纯 advisory**：所有输出仅供参考，不下单、不操作持仓
2. **IRS 规则简化**：只检测 30 天窗口内的买入行为；不处理期权/期货等复杂场景
3. **HIFO 默认**：税务优化默认 HIFO（最大化损失抵扣），符合 tax-loss harvesting 最佳实践
4. **与 SizingOptimizer 接入点**：execution_plan 中减仓时，调用 tax_lot_optimize 选择批次，after_tax_return 做 tie-break

## 状态

E27 从"接口预留"升级为 **✅ DONE**。E1–E30 **30/30 全部有完整骨架实现**。
