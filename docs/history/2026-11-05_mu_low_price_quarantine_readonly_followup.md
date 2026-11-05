# MU 最低价分歧：只读取证附注

日期：2026-11-05，Asia/Shanghai。

**结论：本次拒收由 MU 的 2026-11-04 最低价分歧触发，不是收盘价或成交量异常。隔离与成分观测排除已按既有规则执行；没有据此发现必须修改代码的证据。未修改源码/live/配置，未刷新、补跑或连接 IBKR。**

本文是 `2026-11-05_final_integrated_candidate_external_audit_prompt.md` 的运行事实附注；不修改其冻结正文，也不替代其标明为 11 月 4 日的历史取证。它不是新增独立外审结论或部署批准。

## 1. 原始比较及复算

来源为 live 已落盘的 `data/archive/market_admission_2026-11-05.json`，operation_id=`6f3953db0f7049fc82fe4c7c0871cee1`，completed_through=2026-11-04。

| 字段 | Yahoo 候选 | Alpaca SIP 见证 | 按见证作分母的差异 |
|---|---:|---:|---:|
| open | 822.9949951171875 | 822.995 | 0.0000% |
| high | 853.3399047851562 | 853.3399 | 0.0000% |
| low | 791.030029296875 | 782.0 | **1.1547%** |
| close | 795.22998046875 | 795.23 | 0.0000% |
| volume | 35210225 | 35464905 | 0.7181%，MATCH |

依照当前 `market_witness.py` 的计算方式，逐项复算 `round(abs(candidate-witness)/abs(witness)*100, 4)`，max OHLC=1.1547%，超过 PRICE_WARN_PCT=1.0%，因此 PRICE_MISMATCH、admitted=False。候选与见证的规范化 raw bar 摘要按源码规定的紧凑 JSON 分隔符独立重算，均匹配嵌套 evidence SHA。

这不是判断供应商谁错的充分证据。现有材料是日线比较，不是完整 HTTP 响应或逐笔成交/交易条件记录，无法据此断言 Alpaca 数据错误、Yahoo 数据错误或盘前盘后口径混入。

## 2. 第三源不改变准入

同日 `market_admission_third_source_2026-11-05.json` 的 schema、research_only=True、admission_operation_id、completed_through 与本次准入匹配。

Alpha Vantage 日线最低价 791.00、收盘 795.23；candidate_vs_third max OHLC=0.0055%，MATCH；witness_vs_third max OHLC=1.1378%，MISMATCH。shadow 标注 YAHOO_CANDIDATE，但同时明确 admission_status_unchanged=PRICE_MISMATCH。

**第三源仅为研究证据，不构成“两票对一票”覆盖 canonical 的授权。** 本轮没有请求任何供应商，没有修改准入阈值、见证要求或候选来源。

## 3. 实际保护行为

- MU canonical 最后日期仍为 **2026-11-03**，没有 11 月 4 日行；其 SHA `4e5cb74fb984cee7cc9c706a872550b4b0bf81bb6386e1cbb59577657d8bfc5b` 与准入 canonical_files 绑定一致。
- 全局 admission=BLOCKED，rejected_rows=1、component_flow_rejected_rows=1、strategy_blocking_rejected_rows=0；MU 角色仅 component_flow，影响 COMPONENT_FLOW_ONLY。
- 正式 as_of=2026-11-04 的 SOXL 评分说明实际出现 `[9/10 obs]`，并非拿 MU 旧行情冒充当前观测。这里只确认观测覆盖，不提供交易建议或判断价格应取哪一家。
- 绑定健康报告实际层级：strategy_data=OK、auxiliary_flows=DEGRADED；position_reconciliation 与 operations 为 INFO。
- 今晨总体 PASS、runtime_integrity PASS、strategy_decision WARN、CERTIFIED；1 个独立冲突、1 次尝试。market admission 连续 OK 计数为 0，不能沿用昨天的 3 连 OK。
- 当前正式决策为旧版 c1f4b8f、2026-11-04 r1/FINAL。这是新的运行事实，不是候选已部署或已完成实际输入过渡证明。

## 4. 现在怎么处理

1. 保持当前隔离，等待后续自然预检/正式运行提供更新证据；不人工重复刷新，不改 canonical，不放宽 1% 阈值，不清计数或审计来“消红”。
2. 将本附注随最终整树外审文件交审；它不撤销已完成的合成机制验证，也不把线上观察变成已达标。发布前仍需以当时的实际配置、决策日期、完整清单和 writer 状态重新取证。
3. 当前不新增因子、策略、WebUI 或备用源生产接线。若后续供应商持续不一致，应另以离线证据研究来源/聚合口径，再审是否需要单独修改；本片不先判定源端根因。
4. 一项非紧急诊断改进可单独登记：健康说明除 PRICE_MISMATCH 外，直接列最大分歧字段和值/比例。现有说明显示 volume diff=0.7181%，容易让人误以为是成交量在阻断；这只是提示精度问题，不能作为修改准入或混入冻结候选的理由。

## 5. 证据及边界

`building/reports/market_quarantine_followup/2026-11-05/mu_low_price.json` 保存选定 MU 拒收行、匹配的研究第三源、独立复算、canonical 与健康/正式观测的摘要，不保存完整评分、账户/持仓或 DB。

一件绑定 JSON，加 SHA256SUMS.json 共两件；manifest SHA256：`3691d0e069f6d9745575ad7231af0e6824e090ce80d7183efae9781281e8e0f0`。

八个本次读取的源文件前后摘要一致。未修改原 A2 树实现、冻结候选、外审正文、Git index/config 或旧证据包；仅新增本附注与只读诊断摘要。代码未变，未重复运行全套或四日期比较。

**下一发布动作仍是独立整树外审，而非部署。DEPLOY HOLD；A1 生产证明未闭合；A2 OPEN；Phase B 未启动。**
