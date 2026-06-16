# Hermes 逃顶与镜像系统十项优化总纲

日期：2026-06-05  
分支：`hermes-docs`  
目标：把当前“能看、能点、能刷新”的本地驾驶舱，继续推进成“数据可信、动作唯一、错误透明、可后验校准”的实盘参考系统。

## 总体原则

1. 不再盲目堆指标。优先修“事实源统一、数据可信度、刷新闭环、动作清晰度”。
2. 所有新增能力必须有代码入口、数据库记录、WebUI 可见面或测试覆盖。
3. 任何数据缺失不能默认为安全；必须显示来源、时间、代理状态和置信影响。
4. IBKR 仍保持只读，绝不下单；所有“建议订单”仅作为参考草稿。

## 十项优化清单

### 1. 统一主数据库 `hermes_state.sqlite`

现状：CSV、SQLite、JSONL、单文件 cache 分散，WebUI 可能读到不同层的“最新”。  
优化：新增主状态库，集中写入：

- `score_runs`
- `decisions`
- `factor_values`
- `data_sources`
- `refresh_runs`
- `ibkr_snapshots`
- `posterior_pnl`
- `reentry_state`
- `calibration_logs`

验收：每次刷新后，WebUI 能显示本轮 `state_db_path` 与最新 `score_run_id`。

### 2. 数据质量从单一 MEDIUM/HIGH 改成可解释质量面板

现状：Data Quality 是整体分，用户不知道是哪一类数据拖后腿。  
优化：把质量拆成：

- 价格数据 freshness
- 软数据 latency
- proxy 数据占比
- 底层资金流 freshness
- IBKR live/snapshot 状态
- 缺失指标的动作影响

验收：WebUI 显示“为什么是 MEDIUM”，并列出升级到 HIGH 的具体缺口。

### 3. 全链路刷新审计

现状：刷新按钮能更新，但刷新过程缺少结构化审计。  
优化：一次点击必须记录完整步骤：

1. 行情拉取
2. 软数据拉取
3. IBKR 持仓拉取
4. 评分计算
5. flow 写库
6. audit 写入
7. Web payload 生成

验收：`refresh_runs` 记录每一步状态、耗时、成功/失败原因。

### 4. IBKR 快照机制升级

现状：有单文件 snapshot，但历史快照不可追溯。  
优化：

- 每次 read-only 拉取都写入主库 `ibkr_snapshots`。
- WebUI 显示最近快照时间、年龄、stale 阈值、clientId。
- Gateway 超时时明确降级，不隐藏风险。

验收：即使 live 失败，也能看到最近 N 次 IBKR 快照状态。

### 5. 评分、硬阀门、置信度三权分离

现状：用户容易把总分当成唯一裁决。  
优化：输出三层判断：

- `risk_temperature`：分数温度
- `hard_valve_state`：物理斩仓阀门
- `action_confidence`：数据置信度/是否允许参考动作

验收：每个标的卡片显示这三层，而不是只显示一个 final score。

### 6. 每个标的输出唯一处置指令

现状：有建议但还可以更“实盘执行化”。  
优化：每个标的固定输出：

- 当前状态
- 唯一建议动作
- 卖出比例
- 买入/路由标的
- 目标金额
- 市价参考股数
- 核心触发原因
- 失效条件

验收：WebUI 顶部有“今日操作台”，不用下钻也能知道今天要不要动。

### 7. 再建仓 T1/T2/T3 与成交确认解耦

现状：已有 reentry 状态库，但没有成交确认入口。  
优化：

- 状态库继续保守记录建议。
- 新增 `execution_confirmations` 表/接口骨架。
- 未来可从 IBKR executions 确认 T1/T2 是否真实成交。

验收：WebUI 能显示“建议阶段”和“已确认阶段”两套状态。

### 8. 后验校准自动化

现状：已有上一交易日理想 P/L，但还未系统化归档。  
优化：

- 每次刷新写入 `calibration_logs`。
- 记录如果按昨日建议执行，今天理论盈亏。
- 每周可统计因子贡献与误报/漏报。

验收：WebUI 有“模型校准/后验记录”摘要；数据库有历史可查。

### 9. WebUI 今日操作台

现状：信息量很大，但用户还要自己拼判断。  
优化：首页最上方加：

- 今日是否需要操作
- 最重要三条原因
- 建议资金去向
- 数据是否可信
- IBKR 是否 live

验收：用户打开 8766/8768 的第一屏即可知道“今天要不要动”。

### 10. 指标框 drilldown 解释

现状：部分指标有细节，但解释还不够统一。  
优化：

- 每个核心框有专业解释 + 通俗解释 + 数据来源 + 更新时间。
- 使用轻量 HTML details，不引入复杂前端框架。

验收：宏观、资金流、硬阀门、建仓审计、镜像周期判断都能点开看解释。

## 第一阶段实施顺序

1. 建 `state_store.py` 和主库 schema。
2. 在 `score_pipeline` 写入 score/decision/factor/posterior/reentry 主库记录。
3. 在 `refresh_score_with_market_data` 写入 refresh audit。
4. 在 IBKR 读取后写入 `ibkr_snapshots`。
5. 增加 `decision_intents` 与 WebUI 今日操作台。
6. 增加 data quality breakdown。
7. 增加 calibration log。
8. 增加 reentry confirmation 骨架。
9. 增加 drilldown 解释。
10. 补测试、同步 `.hermes`、重启 8766/8768。

## 严格风险提示

- 当前能显著提升易用性和透明度，但不能自动解决 IBKR Gateway 掉线。
- PE/GEX/PCR 等外部高质量源若无稳定数据供应，只能被标记为代理或缺失。
- 所有建议仍是参考，不应自动下单。
