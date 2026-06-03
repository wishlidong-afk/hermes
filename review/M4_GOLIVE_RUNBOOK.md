# M4 上线 Runbook —— 为什么现在不能直接翻闸 + 安全上线步骤

> **日期：2026-06-02** ｜ 你已授权"接受包的画像并上线"。但核查后:**直接把 `run_daily.py`
> 指向包会让每日生产跑崩,不是上线、是停产。** 本文说清阻塞点 + 安全上线步骤。

## 🔴 为什么不能现在翻闸(已核实)

| 事实 | 证据 |
|---|---|
| 生产是**有计划调度**的 | launchd: `ai.hermes.gateway.plist`、`com.hermes.next5watch.plist` |
| `run_daily.py` → 单体 `escape_top_system.main(["run-daily"])` | 文件首行 import |
| 单体 `run-daily` = `collect()`(下载 OHLCV/CBOE/IBKR/enrichment)+ `score()` | 源码 3004-3007 |
| 单体每日写 4 个下游依赖产物 | `daily_score_precheck_{date}.json`、`orders_preview_{date}.json`、`daily_report_{date}.md`、更新 `state.json` |
| **包没有 `run-daily` 命令** | 包 CLI 只有 score/backfill-history/soft-data/replay/backtest/dashboard/serve |
| **包不产出上述任何日产物** | score_pipeline 返回 payload,但不写 precheck/orders/report/state |

→ 把 `run_daily.py` 指向包 = 调一个**不存在的 run-daily** → 报错 → **计划任务每天跑崩,WebUI/LLM 拿不到日报,state.json 不更新(再建仓追踪断)**。这不是上线。

## ✅ 安全上线步骤(真正的 M4)

**M4-1 建包的 `run-daily` 操作壳**(缺的核心件)
让包能完成完整日循环并产出**与单体同名同结构**的产物:
- collect:`backfill-history`(OHLCV)+ `collect_soft_data`(软数据)+ enrichment/valuation/CBOE 归档
- score:`score_pipeline(as_of)`
- 写产物:`daily_score_precheck_{date}.json` / `orders_preview_{date}.json` / `daily_report_{date}.md` / 更新 `state.json`
- **验收**:对同一 as_of,包产物的 schema 与单体一致(字段齐全,WebUI/LLM 能读)。

**M4-2 影子并行(不碰 run_daily)**
让包的 run-daily 写到**影子目录**(如 `data/shadow/`),与单体的真实产物**逐日 diff**:
- 跑 N 个交易日(建议 ≥10),每日比对 status/sell/route/hard_valves。
- 硬阀门必须 100% 一致;status 差异即你已接受的"包新画像",记录备查。
- 包侧零崩溃、产物 schema 完整。

**M4-3 人工翻闸(你来按)**
影子期通过后,**由你**改 `run_daily.py`:
```python
# from: from escape_top_system import main
from hermes_escape_top.cli import main   # 或新建 run_daily 入口
```
+ 保留单体一行回滚:改回 import 即秒级回退。

**M4-4 切后监控**:头几日盯产物完整性 + 与影子期一致。

## 回滚
任何异常 → `run_daily.py` import 改回单体 → 下个调度周期恢复。单体代码全程不动,随时可退。

## 当前就绪度(M4 地基已稳,只差操作壳)

- ✅ 处置层(RiskEngine+optimizer)已验证:CAGR 21.5%/MaxDD −25.6%/Sharpe 1.01/PBO 0.077/R3=0
- ✅ 硬阀门 100% 对齐(安全门)
- ✅ 特征口径对齐(B1/C6/C7 + 软命名空间)
- ✅ 置信脊柱接回、Kelly/mu/CVaR 修好、数值稳健、322/0 测试绿
- ⏳ **缺**:包的 `run-daily` 操作壳(M4-1)+ 影子期(M4-2)

## 我的建议 / 下一步

我**不替你翻闸**(红线 + 当前会停产)。但我可以**现在建 M4-1(包的 run-daily 操作壳)**——
这是非破坏性的(只新增命令,不动 run_daily.py),建完做一次影子 dry-run 验证产物完整,
再进入 M4-2 影子期。影子期通过后,翻闸那一下由你按。

要我开始建 M4-1 吗?
