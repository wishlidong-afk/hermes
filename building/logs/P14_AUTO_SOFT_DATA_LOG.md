# P14 自动软数据获取 — 真实数据接入

**时间**: 2026-06-02  
**范围**: 把 BTC 微观 + NAAIM 从价格代理升级为真实交易所/调查数据；全自动获取，无需手动操作  
**生产影响**: soft_history CSV 已更新为真实数据；daily scoring 中 quality_penalty 降低；missing_weight 显著下降

---

## 可达性侦察结论

| 数据 | API | 状态 | 历史深度 |
|---|---|---|---|
| Deribit DVOL | `deribit.com/api/v2` | ✅ 完全可达 | 2021-03-24 起 |
| Deribit Funding | `deribit.com/api/v2/public/get_funding_rate_history` | ✅ 完全可达 | 2021+ |
| OKX Funding | `okx.com/api/v5` | ✅ failover 可用 | ~90天 |
| NAAIM xlsx | `naaim.org/wp-content/uploads/...xlsx` | ✅ 直接下载 | 2006-07 起 |
| Binance | `fapi.binance.com` | ❌ 地理封锁 | — |
| Bybit | `api.bybit.com` | ❌ 地理封锁 | — |

---

## 新增脚本

### `scripts/backfill_crypto_micro.py`

- **数据源**: Deribit BTC-PERPETUAL funding history + DVOL
- **Failover**: OKX BTC-USD-SWAP（符合 E30 故障转移模式）
- **输出**: `data/soft_history/btc_funding_basis.csv`（含 `is_proxy` 列）
- **幂等**: 只拉 last_real_date 之后的新数据
- **结果**: 3036 行总（1897 行真实数据 2021-03→2026-06，1139 行代理 2018-2021）

### `scripts/backfill_naaim.py`

- **数据源**: 自动发现 naaim.org 的最新 xlsx URL（页面爬取），直接下载
- **历史**: 1038 行，2006-07-05 → 2026-05-27
- **字段**: `naaim_exposure`（官方 NAAIM Number）、`naaim_pctl`、`is_proxy=False`
- **幂等**: 每次运行拉最新完整历史（覆盖写，xlsx 本身就是全量）

---

## Adapter 升级

### `core/data/crypto.py` — CryptoFundingSource

| 字段 | 变更 |
|---|---|
| `source` | proxy 行 → `BTC_FUNDING_PROXY`；real 行 → `DERIBIT_REAL` |
| `quality_penalty` | proxy → 2.0；real → **0.5** |
| `is_proxy` | 从 CSV 的 `is_proxy` 列读取 |
| `btc_dvol` | 新增字段（real 行才有，2021-03+） |
| `btc_dvol_pctl` | 新增字段 |

### `core/data/sentiment.py` — NaaimSource

| 字段 | 变更 |
|---|---|
| `source` | proxy 行 → `NAAIM_PROXY`；real 行 → `NAAIM` |
| `quality_penalty` | proxy → 1.5；real → **0.0**（官方调查数据） |
| `is_proxy` | 从 CSV 的 `is_proxy` 列读取 |

---

## Missing Weight 改善

| 标的 | 之前（代理） | 之后（真实数据） | 降幅 |
|---|---:|---:|---:|
| MSTR | ~26 | **18** | **-8** |
| FNGU | ~19 | **11** | **-8** |
| SOXL | ~19 | **11** | **-8** |

**MSTR 从26降到18**，已低于 20 pt 优质门限（原先只是低于 30 pt 盲区门）。

---

## 使用方式（全自动，无需手动）

```bash
# 每次更新数据（脚本幂等，只拉增量）
python3 -m hermes_escape_top.scripts.backfill_crypto_micro
python3 -m hermes_escape_top.scripts.backfill_naaim

# 或集成到 run_daily.py 前
python3 hermes_escape_top/scripts/run_daily.py --refresh-soft-data
```

---

## 270 tests OK

## 状态

P14: **DONE** — BTC 微观和 NAAIM 全自动真实数据接入完成，missing_weight 全面下降
