# Hermes 逃顶与镜像 v3 逐条搭建追踪

更新时间：2026-06-01

规格源：`/Users/liweishi/Desktop/逃顶与镜像系统逻辑说明.md`

## 本轮已补齐

- 重读桌面规格文件，并新增逐条追踪报告：`/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/reports/SPEC_TRACE_REPORT.md`
- 指标层补齐价格类核心字段：
  - `vwap20`
  - `avwap_60d`
  - `support_60d_low`
  - `support_distance_60d_pct`
  - `cmf20`
  - `mfi14`
  - `ad_line`
  - `ad_slope20`
- A 模块补齐 `A6_FUND_FLOW`：改为用 QQQ 的 CMF/MFI/AD 资金流评分。
- C 模块补齐 `C7_AVWAP_PLATFORM_SUPPORT`：改为用 60 日 AVWAP 与平台支撑评分。
- D 模块补齐 FNGU/SOXL 成分股资金流：
  - FNGU：NVDA、AAPL、MSFT、AMZN、META、GOOGL、TSLA、NFLX、AVGO
  - SOXL：NVDA、AVGO、AMD、TSM、ASML、AMAT、LRCX、KLAC、QCOM、MU
- 主流水线接入当前市场体制 `regime`：
  - QQQ 趋势栈
  - VIX 252 日分位
  - VIX/VIX3M 期限结构
- WebUI 补齐：
  - Current Regime
  - A/B/C/D 模块分
  - Vol scaler
  - Missing weight / blind spot / data quality
  - Route explain

## 当前验证结果

- 全量测试：68 个 unittest 全部通过。
- `2026-05-29` 本地回放：
  - regime = `LOW_VOL_TREND`
  - A6/C7/D-F4/D-S4 均已从本地字段读取，不再是缺数据占位。
- 只读 WebUI：
  - `http://127.0.0.1:8777/`
  - 浏览器核验通过，页面可见 `Current Regime`、`LOW_VOL_TREND`、`Audit Detail`、模块分。

## 仍受外部数据约束

- GEX、SKEW/VVIX、净流动性、BTC 微观结构仍是软数据契约已完成但真实源未配置。
- Phase 11 的完整规则回放优化/参数放行报告还未完成，目前已有 deterministic replay、transaction simulator、param sweep、purged CV、DSR 框架。
- Phase 13 元模型保持 LOCKED，等待标签数量与正样本数量达标。
- 系统仍然只输出建议、理想仓位、路由和审计，不会下单。
