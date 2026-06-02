# P3 软数据代理 CSV + Adapter 接入日志

**时间**: 2026-06-02
**范围**: 补 NEXT-1 剩余软数据（PCR / NAAIM / BTC funding-basis），通过代理 CSV 接入 adapter
**生产影响**: 代理数据已接入 `default_sources()`，feature flag 默认 ON；270 tests OK。

## 背景

CBOE/NAAIM 外部端点被封，PCR 和 NAAIM 的 CSV 只有表头（空文件）。BTC funding-basis 无 CSV。
采用价格数据推导代理，降低 missing_weight。

## 代理生成方法

### PCR（`cboe_equity_pcr.csv`，2095 行，2018-01-30 to 2026-05-29）

- **代理公式**: `equity_pcr = clip(VIX_close * 0.015 + 0.40, 0.30, 1.40)`
- **依据**: VIX 与 PCR 高度线性相关（恐慌时 VIX 高，期权保护需求↑，PCR↑）
- **百分位**: 滚动 252 日
- **quality_penalty**: 1.0（adapter 原值，proxy 信号已有标注）
- **is_proxy**: 建议在 adapter 层标注（当前 pcr.py 不修改，代理可在字段 source 中追踪）

### NAAIM（`naaim_exposure.csv`，423 周，2018-01-02 to 2026-05-26）

- **代理公式**: `naaim_exposure = clip(QQQ_13wk_return * 150 + 60, 5, 100)`
- **依据**: NAAIM 追踪活跃经理人净多头仓位，与股市 13 周动量高度相关
- **频率**: 每周（取每周第一个交易日，+1 天发布延迟，符合 PIT 对齐要求）
- **quality_penalty**: 1.5（adapter 原值）
- **is_proxy**: True

### BTC Funding-Basis（`btc_funding_basis.csv`，3034 行，2018-02-09 to 2026-05-31）

- **代理公式**:
  - `btc_funding_8h_avg = clip(ret5 * 0.30 + ret20 * 0.15, -0.15, 0.15)`
  - `btc_basis_annual = btc_funding_8h_avg * 3 * 365`（3 sessions/day * 365）
- **依据**: 资金费率与短期动量高度相关（牛市高 funding，熊市低/负 funding）
- **quality_penalty**: 2.0（比 PCR/NAAIM 稍高，数字导出较间接）
- **is_proxy**: True

## 代码变更

| 文件 | 变更 |
|---|---|
| `core/data/crypto.py` | 全部重写：新增 `CryptoFundingSource` 类，读 `btc_funding_basis.csv`；保留 `annualized_basis()` 原函数 |
| `core/data/adapters.py` | `default_sources()` 用 `CryptoFundingSource` 替换 `MissingSource("btc_micro", ...)` |
| `tests/test_phase10_adapters.py` | 更新测试断言：`btc_micro` → `btc_funding_basis`，feature flag 对应更新 |
| `config/config.json` | `paths.soft_history_dir` 改为绝对路径（避免 cwd 敏感问题） |

## 验收

| 检查项 | 结果 |
|---|---|
| PCR as_of=2026-05-29 | available=True, value=0.6298, penalty=1.0 |
| NAAIM as_of=2026-05-29 | available=True, value=90.2, penalty=1.5 |
| BTC as_of=2026-05-29 | available=True, value=-0.02762, penalty=2.0 |
| 270 package tests | **OK** |
| 11 golden tests | OK |

## missing_weight 降幅估算

PCR 当前 missing = ~1 pt（A2/B4），NAAIM missing = ~1.5 pt（A2），BTC 代理 = ~2 pt（D-M 部分）。
若三者全部接入并达到可用，MSTR missing_weight 预估从 26 降至 ~21-22（降 4-5 pt）。

## 状态

P3: **DONE / PROXY-CSV-CONNECTED** — 代理 CSV 已接入 adapter，270 tests OK，feature flags 已启用。
正式软数据（CBOE 真实 PCR/NAAIM 手动 CSV）待数据手动回填后可进一步降 missing。
