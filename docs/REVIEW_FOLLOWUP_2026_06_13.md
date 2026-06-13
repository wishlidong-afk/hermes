# 20 维评审收口 — 2026-06-13

对 2026-06-13 fresh-clone 20 维评审每条建议的最终处置。全部已落地并推送到 `hermes-docs`。

## P0
| 项 | 状态 | commit / 说明 |
|---|---|---|
| 提交并推送未提交的 6 个完整性接线文件（远端 HEAD 红） | ✅ DONE | `2a4d85b` — fresh clone 现 444 绿 |

## P1
| 项 | 状态 | 说明 |
|---|---|---|
| 指标帧缓存（回测提速一个量级） | ✅ DONE | `use_indicator_cache`（`market.py`），byte-identical 4/4 证明（`building/reports/indicator_cache_byte_identical_2026_06_13.json`），full backtest 52min→15.6min。**生产保持 OFF**：单次评分仅省 ~3s（OFF 8.7s/ON 5.8s），价值全在回测且回测态已开；生产翻 true = 零收益 + 多一条缓存路径，故不翻。回滚/启用：`features.use_indicator_cache`。 |
| DEFCON 解释与实现对齐 | ✅ DONE | `2a4d85b` — `routing_context` 规则串改为镜像 `capital_routing.py`（DEFCON1 纯 OR 链、DEFCON2 无 A≥12），并注释"文案必须镜像代码"。 |

## P2
| 项 | 状态 | 说明 |
|---|---|---|
| FRED publish_date → realtime_start | ✅ DONE | `risk_signals.py` 用 API `realtime_start`；无 API 元数据时 fallback date+1。 |
| 8766 写端点鉴权 | ✅ DONE | `server.py` fail-secure：写端点要求 loopback Host/Origin + `HERMES_CONFIRM_TOKEN`（`hmac.compare_digest`）。运维收口（本次）：token 存 `~/.hermes/hermes_confirm_token.txt`（chmod 600，gitignored 位置），`serve_dashboard.sh` 注入 env。**token 不注入页面 HTML**（否则 DNS-rebinding 读响应即破防）；浏览器一次性 `localStorage.setItem('hermes_confirm_token', '<token>')` 带外提供。8765 `/refresh` 只触发数据刷新（无金钱/下单路径），加 loopback-only 守卫而不强制 token（低危端点降摩擦）。 |
| 日报接真实 locks 块 | ✅ DONE | `1567b56` — `_build_reentry_plan` 读 `payload.reentry[sym].locks`，不再硬编码 False 三元组。 |

## P3
| 项 | 状态 | 说明 |
|---|---|---|
| 锚定守卫多数票（防污染锚死锁） | ✅ DONE | `1567b56` — 取 3 个最旧重叠日 2/3 通过即可。 |
| yfinance MultiIndex ticker 名识别串线 | ✅ DONE | `1567b56` — `_normalize_download(expected_symbol=)`，level-1 ticker 名不符即拒（确定性，优于跳变启发式）。 |
| score_pipeline 历史截断（PIT 统一） | ✅ DONE | `1567b56` — 回溯日期运行截断到 as_of，与 `run_full` 同语义。 |
| critical 缺失 → NO_ADVICE | ✅ DONE（flag OFF） | `1567b56` — `use_no_advice_state`：critical 缺失输出 NO_ADVICE + sell 0 持仓，不再伪装 100 分 EXIT。翻闸前需 gate。 |
| 运行时数据移出 git 跟踪 | ✅ DONE（已实质解决） | `1567b56` — shadow 输出物退 git + gitignore。**评审"81 文件全退"不正确**：`data/archive` 的 sqlite/snapshots 是 conftest 隔离种子 + fresh-clone 测试依赖，退了会让 fresh-clone 变红。且 T8（`HERMES_DATA_DIR` 隔离）已实质消解"每跑必变"——测试在 tmp 跑、serve 从 live 跑，repo 的 `flow_reference.sqlite`（唯一残留跟踪 sqlite）不再被日常运行改写（当前 git 干净）。保留为稳定 fixture。 |

## P4
| 项 | 状态 | 说明 |
|---|---|---|
| status_from_score 非数值阈值过滤 | ✅ DONE | `1567b56` — 过滤 `_note` 等注解键（曾踩的地雷）。 |
| run_validation PBO 恒 1.0 | ✅ DONE | `1d519a0` — 单配置改为 `pbo=None/pbo_pass=None`，不再伪造 1.0；多配置向量仍计算。 |
| context.md 按代码再生 | ✅ DONE | `1d519a0` — IAU、DEFCON OR 链、C 模块真实表、444 tests、live flags、三层数据守卫、8765/8766 架构。 |
| requirements.txt | ✅ DONE | `1567b56`。 |

## 评审外补获 bug
| 项 | 状态 | 说明 |
|---|---|---|
| 在线软数据源 OHLCV 依赖漏出刷新链路 | ✅ DONE | `9a54394` — A15 defensive_rotation（live）的 XLP/XLU/XLV/XLY/XLI/XLF 不在 market_symbols、藏在 in-line ratio，从未进刷新链路 → 该 live 因子用陈旧 ETF 打分。`ONLINE_SOFT_HISTORY_SYMBOLS_BY_FLAG` 把每个 risk flag 映射到 ETF 依赖，`all_backfill_symbols`/`refresh._flow_symbols` 纳入每个 ON flag 的依赖；回归测试守卫。运行态已补到 06-12、latency 0。 |

## 残留（非代码，无需收口）
- **IBKR 快照陈旧**（8766 health 唯一 DEGRADED）：TWS/Gateway 未在本机开 readonly API 端口，非代码问题；启动后自消。
- **Pandas4Warning**（`wso_index.py` Timestamp.utcnow）：唯一测试 warning，无害，下次碰该文件时顺手改。

## 操作者一次性动作（恢复 8766 写按钮）
浏览器 console 跑一次（token 在 `~/.hermes/hermes_confirm_token.txt`）：
```js
localStorage.setItem('hermes_confirm_token', '<paste token>')
```
此后 8766 的"更新数据/上线/确认执行"按钮自动带 `X-Hermes-Token`。8765 工作台的"更新数据"无需 token（loopback-only）。
