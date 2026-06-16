# FIX LOG 2026-06-05: Review Gap Full Repair

## 背景

本轮按“最严苛视角”复查后，集中修复新系统逃顶与镜像 WebUI 的模型、数据、IBKR、后验测算、建仓状态和前端刷新链路。目标不是只让测试变绿，而是把“能看、能点、能更新、能参考”的实盘工作流补齐到可验收状态。

## 已修复缺口

1. 资金路由 A 模块核心因子聚合错误
   - 修复 `A1/A5/A7/A8` 只取第一个匹配因子的风险。
   - 改为按前缀取最大分，避免 `A1_QQQ_MA200_BREAK=0` 掩盖 `A1_VIX_COMPLACENCY=4`。
   - C6/C8 也使用同类最大值逻辑。

2. 镜像系统缺 MSTR 桶
   - 新增 `MSTR_QQQ` 镜像腿，桶上限 15%。
   - 判断维度：MSTR EMA20/EMA50/MA200、MACD、RSI、5日涨幅、3日上涨、成交量比、BTC>MA200、VIX。
   - 镜像 WebUI 8768 展示顺序改为 `MSTR_QQQ / FNGU_QQQ / SOXL_SOXX`。

3. 底层资金流 stale 问题
   - `basket_flow` 增加 `component_min_as_of`、`component_max_stale_days`、`stale_components`。
   - `refresh_score_with_market_data` 在核心标的已新鲜但底层持仓 stale 时，只补 stale flow symbols。
   - 修复 MFI 在连续正向资金流时被除零判成 `MISSING` 的问题：负向流为 0 且正向流大于 0 时，MFI=100。

4. flow SQLite 固化增强
   - `flow_reference.sqlite` 增加 `component_min_as_of`、`component_max_stale_days`、`input_hash`、`created_at`。
   - 老库自动 `ALTER TABLE` 迁移。

5. IBKR clientId 冲突处理
   - `read_positions` 支持 `client_id_retry_count`，从配置 clientId 起顺序尝试。
   - 只在明确 clientId in use / 326 冲突时换号重试；普通 timeout 不再连环重试。
   - WebUI/对账 payload 显示实际 `client_id`。

6. 后验/理想持仓本金来源
   - 逃顶与镜像 `posterior_pnl.portfolio_value` 优先使用 IBKR `NetLiq`。
   - IBKR 不可用时才回退到配置本金。

7. 回测/重放边界
   - `score_pipeline(..., include_ibkr=False)` 新增离线开关。
   - 回测/score replay 默认关闭 IBKR，避免历史模拟误读实时券商账户。

8. 3-3-4 再建仓状态库
   - 新增 `core/reentry/store.py`。
   - SQLite 持久化 `reentry_state` 与 `reentry_plans`。
   - 保守设计：系统记录建议和已有状态，不会在无成交确认时擅自把 T1/T2 标记为已执行。

9. Web API 错误返回
   - 8766/8768 的刷新接口捕获异常并返回 JSON `{ok:false,error:...}`。
   - 避免前端收到空响应，看起来像“按钮没反应”。

10. WebUI 刷新体验
    - 逃顶 8766 增加 `refresh-result` 结果框。
    - 8766/8768 的“更新策略数据/更新镜像数据/更新持仓”按钮在自动 reload 后保留最近一次刷新结果。
    - 解决点击后页面重载导致状态文案消失、用户误判为未更新的问题。

## 验收结果

### 自动化测试

```text
PYTHONPATH=src python3 -m unittest discover -s src/hermes_escape_top/tests -p 'test_*.py'
Ran 331 tests in 58.713s
OK
```

### 实盘刷新检查

```text
as_of: 2026-06-04
data_quality: MEDIUM 83.15
IBKR: source=snapshot, net_liq=86005.32, snapshot_stale=True
mirror_keys: FNGU_QQQ, MSTR_QQQ, SOXL_SOXX
flow FNGU: ABNORMAL, component_min_as_of=2026-06-04, max_stale=0, stale_count=0
flow SOXL: NORMAL, component_min_as_of=2026-06-04, max_stale=0, stale_count=0
posterior_value: 86005.32
```

### WebUI 端口验收

```text
8766 /health => {"ok":true}
8768 /health => {"ok":true,"app":"mirror"}
```

Browser 点击验收：

```text
8766 更新策略数据 => strategy refreshed: as_of=2026-06-04
8768 更新镜像数据 => mirror refreshed: {...}
8766 更新持仓 => ibkr refreshed: source=snapshot net_liq=86005.32
8768 更新持仓 => ibkr refreshed: source=snapshot net_liq=86005.32
```

### 运行端同步

- 已同步 package 代码到 `/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/`。
- 已同步配置到 `.hermes` 技能根目录与 package config。
- 已重启：
  - 8766: Hermes 逃顶驾驶舱
  - 8768: Hermes 镜像参考

## 严格剩余风险

1. IBKR 本轮仍未 live 成功
   - 端口可尝试，但 account/positions 请求超时。
   - 当前 WebUI 明确显示 `source=snapshot`、`NetLiq=86005.32`、stale 状态。
   - 这不是模型错误，但属于实盘可靠性风险：Gateway 需要保持 API 会话稳定。

2. Data Quality 仍为 MEDIUM
   - 主要来自软数据 latency/proxy，而不是 OHLCV 或 flow。
   - flow 已刷新到 2026-06-04 且 stale_count=0。
   - 想升到 HIGH，需要继续替换 PCR/GEX/估值等代理源。

3. 再建仓状态仍缺成交确认入口
   - 已有状态库，但没有自动从 IBKR 成交记录确认 T1/T2。
   - 当前保守，不会误把建议当成交。

4. 前端刷新已经可视化，但仍是轻量本地 WebUI
   - 没有做用户级权限、审计登录、WebSocket 实时推送。
   - 当前定位仍是本机参考驾驶舱。

## 结论

本轮 review gap 已从“模型逻辑 + 数据陈旧 + 按钮看似无反应 + 回测误触 IBKR”的层面完整修复。系统现在满足当前验收目标：能看、能点、能更新、能展示最新可得数据，并且在 IBKR 不可用时明确降级到 snapshot 而不是假装 live。
