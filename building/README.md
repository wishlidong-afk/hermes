# Hermes Building Progress

本目录是 Codex（Claude Code CLI）与 Cowork（Claude Cowork mode）**双 Agent 并行搭建**的进度中枢。
所有施工状态以本目录的 GitHub 版本为唯一权威——本地副本、对话记忆均不可信。

---

## ⚠️ 接续施工铁律（每次开工前必读，两个 Agent 同等约束）

### 铁律 0 · 开工三步曲（任何施工前执行）

```
1. 读 GitHub 上的 building/STATUS.md 确认当前状态（不是本地副本，不是记忆）
2. 读 docs/CODEX_GUIDANCE.md 确认当前优先级与阻塞项
3. 把自己要做的任务标为 IN-PROGRESS 并推送，再动手
```

> 跳过任何一步 → 可能在错误任务上做了正确的工作。

---

### 铁律 1 · 认领锁定（防双写冲突）

- 开始一个 NEXT 工单前，**必须先把 STATUS.md 对应行改为 `IN-PROGRESS` 并推送到 GitHub**，再动手写代码或报告。
- 如果 STATUS 显示某任务已是 `IN-PROGRESS`，**停下来，读对应的 `building/logs/` 执行日志，再决定是接手还是等待**。不得静默覆盖。
- 若接手另一个 Agent 的未完成任务，在日志里注明"接续自 [上一 Agent]，补完内容：..."。

---

### 铁律 2 · 完成即闭环（防状态悬空）

完成一个可验收单元后，**必须在同一次推送中完成以下四件事**，缺一不可：

| # | 动作 | 文件 |
|---|---|---|
| ① | 更新任务行为 DONE + 验收数字 | `building/STATUS.md` |
| ② | 写执行日志（做了什么/关键数字/置信度/下一步） | `building/logs/NEXTX_xxx_LOG.md` |
| ③ | 同步进度账本 | `docs/STATUS.md` |
| ④ | 如有新代码快照，放入 | `building/source_snapshots/NEXTX_*/` |

> 只更新 STATUS 不写日志 = 别人不知道你怎么做到的，等于没做。

---

### 铁律 3 · 职责分区（防重叠、发挥各自优势）

| 职责域 | 归属 Agent | 对方不主动触碰 |
|---|---|---|
| `.py` 代码实现、重构、测试运行 | **Codex** | Cowork 只读代码，不改 |
| `building/` 报告、日志、STATUS 更新 | **Cowork** | Codex 可写，但 Cowork 负责最终整合 |
| `docs/` 文档（CODEX_GUIDANCE / STATUS / BUILD_TICKETS） | **协作**：Codex 提供数字，Cowork 执笔 | 改前读最新版 |
| `config/artifacts/calibration_*.json` | **Codex 生成，Cowork 不改** | 人工审核后才生效 |
| `state.json` / `signal_journal.json` | **只读**，两者均不写入生产状态 | 绝对不碰 |

---

### 铁律 4 · 不干净不移交

一个任务宣告 DONE 前，必须满足：

- [ ] `python3 -m unittest discover` 全绿（数字写入日志）
- [ ] 报告里没有 "TODO" 或 "待补" 占位符
- [ ] 所有合成/代理数据段标 `is_proxy=True`，来源可溯
- [ ] `data_manifest_id` 写入回测报告头部
- [ ] 新增 `config/` 参数已与 `calibration_v1.json` 对齐或注明偏差原因

> 测试数字不写进日志 = 无法验证，默认未过。

---

### 铁律 5 · 参数冻结（防配置漂移）

- 校准产出的参数（`config/artifacts/calibration_v1.json` 的 `chosen.status_thresholds`）是当前基准。
- **任何人改 `status_thresholds`，必须有新的 `calibration_vX.json` 支撑**，不得凭感觉调整。
- 激活 `use_portfolio_risk_budget=true` 前，必须重跑含 vol_budget 网格的 NEXT-3 校准。

---

### 铁律 6 · 合成段诚实原则

- FNGU/FNGS 在 2025-02-20 之前的数据全部是合成代理段（接缝调整 TE 4.67%，corr 0.9986）。
- 任何报告、日志、分析中引用 2018 年起数据时，**必须注明"含合成段"与"仅真实段"两套数字**，不得混报。
- 合成段信号的置信度评级为 **Medium**，不得上升为 High。

---

### 铁律 7 · 绝不下单（最高优先级，任何条件不得例外）

- 两个 Agent 均只能输出 `orders_preview`，不得调用任何真实交易接口。
- 报告中发现任何"买入""卖出"描述，必须加注"仅预览，需人工确认"。
- 遇到"接近 IBKR 真实交易"的需求，直接拒绝并记录在日志里。

---

### 铁律 8 · 推送节律（防碎片化历史）

- **每次推送必须是一个完整的可验收单元**，不推半成品。
- 提交消息格式：`[NEXT-X] 动词 + 关键结果（一行）`。例：`[NEXT-3] DONE — Calmar=4.02 PBO=0.556 chosen DEF_EXIT=60 REDUCE=55`。
- 同一天多次推送：追加 `(2/2)` 等序号。
- 大型 JSON 报告（>5MB）放 `building/reports/`，源码快照放 `building/source_snapshots/`。

---

### 铁律 9 · 接续读取顺序

每次新 session 开工，**按此顺序读**：

```
1. building/STATUS.md          ← 当前任务状态（谁在做什么）
2. docs/CODEX_GUIDANCE.md      ← 当前优先级与阻塞（唯一指挥中心）
3. building/logs/最新LOG.md    ← 上一个 Agent 留下了什么
4. 对应 NEXT*_REPORT.md        ← 前序工作的技术细节
```

> 不读就动手 = 在错误的地方用力。

---

### 铁律 10 · 冲突解决规则（人工仲裁优先）

- 两个 Agent 对同一问题得出不同结论（参数、架构、数据处理）：**写进日志，标注分歧，不得静默覆盖，等待人工决策**。
- STATUS 显示冲突（同一任务两行状态不一致）：**停止施工，在 building/logs/ 写一条 CONFLICT_YYYY-MM-DD.md，等待人工确认**。
- 任何 Agent 均不得以"我认为更好"为由覆盖另一个 Agent 的已验收产出。

---

## 当前验收快照（2026-06-01）

| 里程碑 | 状态 | 关键数字 |
|---|---|---|
| M0 能跑 | ✅ | 86 单测绿（本地最新） |
| M1 看得清 | ✅ | missing: MSTR 26 / FNGU 19 / SOXL 19，均 <30 |
| M2 验得过 | ✅ | real-only CAGR 44.39% MaxDD -10.43% Sharpe 1.79 DSR 1.66 |
| **M3 校得准** | **✅ 实质达成** | Calmar 4.02（3.7× SPY）；chosen: DEF_EXIT=60 REDUCE=55 |
| M4 可上线 | ⬜ | 待人工 dry-run |
| M5 会学习 | ⬜ | 标签解锁门未达 |

**当前最高优先任务**：NEXT-4（向前软数据）或 NEXT-6（IBKR 只读对账），可并行。

---

## 同步范围

- `STATUS.md`：任务状态账本（最高频更新）
- `logs/`：每个可验收任务的执行日志
- `reports/`：阶段报告、回测结果、校准产出
- `source_snapshots/`：关键代码快照（代码未进主仓库时）
- `desktop/`：用户侧总指导与原始规格文件
- `docs/`：功能规格、架构、施工指引、路线图（低频，经过审核再改）

---

## 文件写入权限速查

| 文件 | Codex | Cowork | 备注 |
|---|---|---|---|
| `building/STATUS.md` | ✅ 写 | ✅ 写 | 改前读最新版；改后立即推 |
| `building/logs/*.md` | ✅ 写 | ✅ 写 | 追加，不覆盖他人已有日志 |
| `building/reports/*.md` | ✅ 写 | ✅ 写（负责整合） | |
| `building/source_snapshots/` | ✅ 写 | 只读 | |
| `docs/STATUS.md` | ✅ 写数字 | ✅ 执笔 | 协作 |
| `docs/CODEX_GUIDANCE.md` | ✅ 提需求 | ✅ 执笔 | 协作 |
| `.py` 代码 | ✅ 主责 | ❌ 不改 | |
| `config/artifacts/calibration_*.json` | ✅ 生成 | ❌ 不改 | 人工审核后才引用 |
| `state.json` / `signal_journal.json` | ❌ | ❌ | 任何 Agent 均不写 |
