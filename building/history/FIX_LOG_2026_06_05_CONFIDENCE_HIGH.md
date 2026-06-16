# FIX LOG 2026-06-05 — 数据置信度升级到 HIGH

## 目标

把 8766 逃顶 WebUI 的数据/动作置信度从 MEDIUM 升级到真实可解释的 HIGH，不通过伪造阈值或隐藏缺项完成。

## 根因

1. IBKR Gateway 一度无监听端口，系统只能读取过期 `positions_cache`，行动置信度被 stale snapshot 压到 70。
2. `missing_weight` 同时包含真实计分缺项和 `max_score=0` 的占位缺项，导致 CNN Fear & Greed、social、MSTR D-M4/D-M5 这类未启用占位项也扣动作置信度。
3. AAII/NAAIM/FRED 等周频或天然发布滞后数据，被按日频行情数据线性重罚。
4. CBOE PCR 公开端点不可用时，旧回填脚本会把本地 PCR CSV 覆盖成空表；同时 PCR 代理没有随最新 VIX 历史动态补齐。
5. 跑测试会写入旧日期 audit payload，WebUI `latest` 若取尾部记录，会被旧测试缓存污染。

## 修复内容

- `ScoreResult` 新增：
  - `confidence_missing_weight`
  - `confidence_missing_fields`
  - `non_scoring_missing_weight`
  - `non_scoring_missing_fields`
- 打分层仅把 `max_score > 0` 的缺项纳入动作置信度扣分；占位缺项继续展示和审计。
- 行动层继续保留 HIGH/MEDIUM/LOW/BLOCKED 阈值，HIGH 仍为 `>=85`，没有放宽阈值。
- WebUI 增加“实质缺项扣分 / 占位缺项”展示。
- `quality_from_snapshots` 改为按数据源发布节奏计算 latency penalty：
  - AAII/NAAIM/FRED：7 天宽限。
  - PCR / BTC funding / component flow：2 天宽限。
- PCR 数据源新增 `PCR_VIX_LIVE_PROXY`：
  - 当真实 PCR CSV 缺失或旧 `vix_derived_proxy` 超过 2 天时，用最新 `^VIX` 历史生成同日代理。
  - 明确标注 `is_proxy=True` 和 `quality_penalty=1.5`。
- PCR 回填脚本失败时保留旧缓存，避免覆盖为空表。
- NAAIM 自动回填至 `2026-06-03`。
- Web server `latest` 选择改为取 audit_log 中日期最大的 payload，避免旧测试记录污染最新页面。

## 当前验收结果

刷新时间：2026-06-05

| 项目 | 结果 |
|---|---:|
| Score as_of | 2026-06-04 |
| Refresh status | OK |
| Data Quality | HIGH |
| Data Quality Score | 93.75 |
| IBKR source | tws |
| IBKR stale | false |
| FNGU action confidence | HIGH 88.75 |
| MSTR action confidence | HIGH 88.75 |
| SOXL action confidence | HIGH 88.75 |

## 剩余缺口

- B6 valuation 仍是实质缺项，每个标的扣 5 分；后续需要接入 FNGS/SOXX 估值分位与 MSTR mNAV premium。
- AAII 仍停在 2026-05-21，虽然不阻塞 HIGH，但建议补自动源或更新 `sentiment.xls`。
- PCR 仍为 VIX 代理，不是真实 CBOE Equity PCR；真实源端点当前 403，需要寻找稳定替代源。
- `flow_reference.sqlite` 是运行时数据库，本次未纳入提交。

## 验证

- `PYTHONPATH=src python3 -m unittest discover -s src/hermes_escape_top/tests`
  - 346 tests OK
- 8766 `/api/score`
  - `2026-06-04 tws HIGH HIGH`
- In-app Browser
  - 页面显示 `Data HIGH`
  - 页面显示 `IBKR tws`
  - 页面显示 `动作置信度 HIGH · 88.75`
  - 页面显示 `实质缺项扣分` 与 `占位缺项`
