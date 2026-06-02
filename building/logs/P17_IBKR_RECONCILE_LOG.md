# P17 IBKR 只读对账（NEXT-6）

**时间**: 2026-06-02  
**范围**: 接入真实 IBKR TWS，实现持仓读取 + 理想 vs 实际对账 + WebUI 面板  
**生产影响**: 只读；`ib_insync` 以 `readonly=True` 连接；绝不下单；断连自动回退本地快照

---

## 连接确认

| 项目 | 值 |
|---|---|
| 连接方式 | ib_insync → TWS Gateway port 4001 |
| 账户 | U18122312 |
| NetLiquidation | $86,202.96 |
| 只读模式 | `readonly=True`（TWS 拒绝任何订单提交） |

---

## 新增模块

### `ibkr/positions.py` — 持仓读取（N6-T01）

- `read_positions(config)` → `PositionSnapshot`
- 依次尝试所有端口（4001/4002/7496/7497），首个成功连接即用
- 读取：NetLiq / GrossPositionValue / Cash / UnrealizedPnL / RealizedPnL + 所有持仓
- 成功后写 `data/positions_cache.json` 快照
- 断连时自动读快照，标注 `source="snapshot"` 和错误原因

### `ibkr/reconcile.py` — 对账（N6-T02）

- `reconcile(snapshot, pipeline_sizing, pipeline_routing, tolerance=0.01)` → `ReconcileReport`
- 三类分组：
  - **trade_symbols**：MSTR/FNGU/SOXL 理想 vs 实际
  - **route_legs**：BRK.B/SOXX 等路由目标腿
  - **extra_positions**：账户中不属于当前 pipeline 的持仓
- 状态枚举：MATCH / MISSING / OVER / UNDER / EXTRA / ROUTE_LEG
- 自动识别已知路由腿（BOXX/BRK B/SOXX/SMH/QQQ/BIL/SHV/DBMF）

---

## 真实对账结果（2026-05-29 账户状态）

| 类型 | Symbol | 理想 | 实际 | Delta | 状态 |
|---|---|---:|---:|---:|---|
| Trade | FNGU | 18.00% | 0.00% | -18.00% | MISSING |
| Trade | MSTR | 0.00% | 0.00% | 0.00% | ✅ MATCH |
| Trade | SOXL | 10.80% | 0.00% | -10.80% | MISSING |
| Route | BRK.B | 10.80% | 12.76% | +2.00% | OVER |
| Route | SOXX | — | 16.52% | — | ROUTE_LEG |
| Extra | NASA | — | 31.31% | — | EXTRA |
| Extra | XOVR | — | 11.48% | — | EXTRA |
| Extra | URA | — | 15.26% | — | EXTRA |
| Extra | IAU | — | 6.73% | — | EXTRA |

**解读**: 账户当前未持有 FNGU/SOXL（已减仓/路由），而是持有 SOXX（SOXL 的 1x 降维腿）和 BRK.B（DEFCON2 路由腿）。MSTR EXIT 状态对账 MATCH ✓。其余持仓（NASA/XOVR/URA/IAU）为账户中的其他独立头寸，不在 Hermes 管辖范围。

---

## Pipeline 集成

`score_pipeline()` 返回的 payload 新增 `ibkr` 字段：
- `ibkr.enabled=false` → `{"source": "disabled"}`
- `ibkr.enabled=true` 且 TWS 在线 → 完整 `ReconcileReport.to_dict()`
- TWS 断连 → 读快照，标注 error

---

## WebUI 集成

新增 **IBKR Reconciliation** 面板：
- 实时 NetLiq + 同步时间
- 绿色/红色 tolerance badge
- 颜色编码：MATCH（绿）/ MISSING（红）/ OVER（黄）/ ROUTE_LEG（蓝）/ EXTRA（紫）

---

## 12 个 offline 测试（无需 TWS）

| 场景 | 状态 |
|---|---|
| 精确 MATCH | ✅ |
| 零对零 MATCH | ✅ |
| MISSING | ✅ |
| max_delta 计算 | ✅ |
| OVER | ✅ |
| SOXX → route_legs（有 routing） | ✅ |
| SOXX → ROUTE_LEG（无 routing） | ✅ |
| BRK B → ROUTE_LEG | ✅ |
| NASA → EXTRA | ✅ |
| to_dict 可序列化 | ✅ |
| 快照 source 传递 | ✅ |
| 实际总权重 ≤ 100% | ✅ |

305 tests OK

---

## 状态

NEXT-6 IBKR 只读对账: **DONE**
