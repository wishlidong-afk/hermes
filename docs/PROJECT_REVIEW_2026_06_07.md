# Hermes 项目复盘与前瞻（2026-06-07）

> 接续 `PROJECT_REVIEW_2026_06_02.md`。本轮复盘聚焦三件事：
> ①把文档对齐到 06-05 的真实代码进度；②修复 WebUI 链接数据的新鲜度与完整性；
> ③记录本次（06-07）落地的全部改动与验证结果。
> 所有数字均为本机实跑（`score_pipeline` + 真起 WebUI）所得，非纸面推断。

---

## 0. 一句话现状

系统已是**可运行、WebUI 端到端打通、R3 安全不变式成立**的状态。06-02 复盘点名的两大阻塞
（110/0.90 人审、canonical 包缺失）**均已解除**；本轮又修掉了数据清单漂移、日历日新鲜度
掩盖缺口、FRED 净流动性陈旧三处真实问题。当前唯一的“硬阻塞”只剩 **AAII 端点被封**
（需人工凭证）与 **M4 生产切换的人工门**。

---

## 1. 文档对齐：06-02 → 06-05 真实进度

`docs/` 下 STATUS/MASTER/PROJECT_REVIEW 此前冻结在 **2026-06-02**，明显落后于代码。
据 git 历史与 `config.json`，06-03 至 06-05 实际完成：

| 日期 | 进展 | 证据 |
|---|---|---|
| 06-02 | **P10 APPROVED：corr 闸 110/0.90**，人工接受 1.85pp 回撤放大 | `config.json` → `portfolio._calibration.note` |
| 06-03 | **重校准 EXIT 80→75 闭环**；T2 模块 A 修 4 个真 bug；B6 估值因子补齐（FNGU gap closed） | commits `d474bd4` `eaa2293` `737586f` |
| 06-04 | **WebUI 按 package payload 重建**；IBKR live 验证；run_daily web 接口修复 | commits `cfb5807` `4d08534` `1705de9` |
| 06-05 | **执行同步 + 状态留存**；镜像看板恢复；“十项可用性升级”；live 置信拉到 high | commits `2a4863c` `7aa9acb` `4cab632` |

**结论**：06-02 自评“72%、唯一阻塞=人审 110/0.90”已显著低估。canonical `src/` 包已落地，
旧 16+ `source_snapshots` 退到 `building/` 归档（06-02 的 §3.2 建议已实现）。

---

## 2. PBO 数字对账（消除文档内部打架）

06-02 复盘 §3.4 把 `train-greedy PBO = 0.6154` 当成“持续警报”，而 `review/CHANGELOG.md`
与 `review/DECISIONS_AND_GOLDEN_AUDIT.md` 写的是 `0.077`。两者**不矛盾，是两个不同的扫描**：

| 扫描对象 | train-greedy PBO | deployment fixed PBO | 判定 |
|---|---|---|---|
| **NEXT-3 评分阈值**（E75/D65/R50 网格） | 0.6154（仅作“勿贪心选参”警报） | **0.1538 PASS** | 固定参数部署安全 |
| **相关闸迁移**（110/0.90 全网格 exact，7×3 场景） | **0.077 PASS（<0.5）** | — | 过拟合门通过 |

`0.6154` 曾被借去描述相关闸，是**全网格跑完前的占位/单场景伪值**；全网格 exact 跑完后
真实值为 `0.077`，**已正式取代**。两个 0.6154 含义不同：评分阈值扫描的 greedy 警报值（正常、
预期、固定部署不受影响）vs 相关闸的旧占位（已废弃）。

> 单一口径：**部署用固定参数；评分阈值固定 PBO=0.1538、相关闸全网格 PBO=0.077，均 < 0.5，过拟合门通过。**
> greedy 选参一律不上线（这正是 0.6154 警报想表达的）。

---

## 3. 单一处置入口（scaler→SizingOptimizer）迁移已完成

`building/reports/SCALER_MIGRATION_GUIDE.md` 描述的“旧乘法链 → SizingOptimizer”迁移，
**在 canonical 包中已经完成**：

- `grep` 残留脆弱 scaler 链（`apply_scalers|vol_target_scaler|target *= scaler`）= **0**。
- 每个标的 `sizing_engine = optimize_targets_v1`；`pipeline.py` 注释即 “Replace the old scaler
  multiplication chain with SizingOptimizer (Gate 2)”。
- 残留的 `gross_scaler` 字段是 optimizer 的**风险界输入**（`w_i ≤ bound × gross_scaler`）与审计回显，
  **非乘法链**。

**R3 不变式实跑校验**（2026-06-04 / 05-29 / 03-16 三日）：每腿 `target_weight ≤ reference_target_weight ≤ sleeve_cap`，**0 违规**。
样例（06-04）：FNGU tgt 0.1776 ≤ ref 0.20；MSTR 0.0 ≤ 0.0（EXIT 归零）；SOXL 0.1066 ≤ 0.12。

→ 系统级总闸②（单一处置入口）**实数据成立**。剩余只是 M4 生产把 `run_daily.py` 从单体翻到包
（WebUI 已有 `m4_golive` 人工门按钮），属人工不可逆动作，不在代码自动化范围。

---

## 4. WebUI 链接数据：新鲜度与完整度（本轮重点）

### 4.1 修复前后对照（today=2026-06-07）

| 数据源 | 修复前 | 修复后 | 手段 |
|---|---|---|---|
| 数据清单 `data_manifest_latest.json` | **漂移**：frozen 06-01、声明 05-29/2113 行，实际 06-04/2117 行 | **一致**：06-07 重冻结，`verify_manifest=True` | 重冻结 + 接入刷新链自动重冻结 |
| FRED 净流动性 | 05-29，WebUI latency **5** | **06-05，latency 0** | 联网 FRED 全量重建（0 历史漂移，纯增 5 行） |
| 历史新鲜度判定 | 日历滞后≤3 天 → 掩盖缺失的周五 06-05 bar | **交易日感知**：如实标 1 个缺失交易日 | `_history_is_fresh` 改交易日口径 |
| AAII 情绪 | 05-21，latency 14 | **仍 14**（端点 HTTP 403 被封） | 已尝试联网；需人工 AAII 凭证或手动 `sentiment.xls` |
| IBKR 对账 | 取决于 TWS | 本机连真实 TWS（account U18122312）；无 TWS 环境可一键加载演示快照 | 安全 demo 快照（不覆盖真实） |

> latency_score 仍 80，瓶颈是 AAII（被封）。FRED 已不再拖分。

### 4.2 WebUI 新增（**布局零改动，仅新增模块/按钮**）

- **数据质量区**：新增「数据清单 一致/漂移」徽章 + `frozen_at` + 「刷新数据清单」按钮。
- **运维控制台**：新增「更新慢软数据(FRED/AAII)」「加载 IBKR 演示快照」按钮 + 数据清单状态。
- **空盘引导**：无评分缓存时显示黄条引导（fresh clone 不再一片空白）。
- 新增只读端点 `GET /api/manifest_status`；新增 `POST /api/refresh_manifest`、
  `/api/refresh_soft_data`、`/api/ibkr_demo_snapshot`。
- 原有 6 大板块（今日操作台 / Escape Decisions / 宏观 A / Mirror / 数据源明细 / M4 控制台）
  实跑确认**结构不变**。

---

## 5. 本轮改动清单（文件级）

| 文件 | 改动 |
|---|---|
| `web/refresh.py` | 接入 `_refresh_manifest`（自动重冻结+漂移自愈）、`manifest_status`、`force_refresh_manifest`；`_history_is_fresh` 改交易日感知；`refresh_status` 增 `trading_days_stale`/`manifest` |
| `web/render.py` | `render_dashboard`/`_render_quality_section`/`_render_ops_panel` 增 `manifest_status`；新增 `_render_cache_hint`、`_manifest_badge`、3 个 JS handler；新增按钮（布局不变） |
| `web/server.py` | 新增 `/api/manifest_status`、`/api/refresh_manifest`、`/api/refresh_soft_data`、`/api/ibkr_demo_snapshot`；GET `/` 注入 manifest 状态 |
| `ibkr/positions.py` | 新增 `write_demo_snapshot`（`DEMO-MOCK` 标记 + 拒绝覆盖真实快照） |
| `scripts/backfill_soft_data.py` | **新增**：FRED/AAII 联网回填，重试+校验+备份，失败只读不污染 |
| `data/archive/data_manifest_latest.json` | 重冻结到 06-04/2117 行 |
| `data/soft_history/fred_net_liquidity.csv` | +5 行至 06-05 |

---

## 6. 剩余缺口与下一步

| 优先级 | 项 | 说明 |
|---|---|---|
| 🟠 | **AAII 回填** | 端点 403 需会员凭证；已支持手动 `config.paths.aaii_sentiment_xls` 落盘路径，建议人工下载后投喂 |
| 🟡 | **M4 生产切换** | `run_daily.py` 单体→包，WebUI `m4_golive` 人工门；建议先连跑 1 周 shadow 对照再翻 |
| 🟡 | **Phase IV 全闸实数据** | PBO/CI/对抗 AUC 端到端跑，产 `Factor_Health.md`，把 7 闸从“骨架+部分实数据”升满 |
| 🟢 | **repo `src/` 与 `.hermes` 已分叉** | 二者代码已不完全一致（如 `web/server.py`）；建议确立一处为真相并单向同步 |
| 🟢 | EXTREME_CORR 非对称化、元模型解锁、gex/valuation 接入或显式标注“不计分” | 见 06-02 复盘 §4 长期项 |

---

## 7. 安全红线复核（未破）

只读不下单（订单恒为 `SIGNAL_ONLY`）；缺数据走 missing_weight+盲区惩罚；硬阀门优先；
feature flags 默认 OFF；IBKR demo 快照带 `DEMO-MOCK` 标记且**拒绝覆盖真实持仓**；
真实持仓/审计/状态文件均已 `.gitignore`（公开 repo 不含账户数据，本轮核实）。
