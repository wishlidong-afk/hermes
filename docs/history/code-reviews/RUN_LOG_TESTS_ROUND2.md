# Run Log — 应用修复 + 跑测试（Round 2 落地）

> **日期：2026-06-02**
> **目标（你定的范围）：** 把 round-2 修复落到「能跑的包」、**只跑测试、不跑回测**、三份代码同步为一份。
> **环境：** venv `/Users/liweishi/.hermes/hermes-agent/venv`（pytest 9.0.2 / numpy 2.4.3 / pandas 2.x / scipy）

---

## 1. 关键发现：代码有"双树"

跑测试时发现本地有**两棵包树**：

| 树 | import 前缀 | 谁用 | 角色 |
|---|---|---|---|
| `escape-top/hermes_escape_top/` | `from hermes_escape_top...` | ~112 处测试 import | **canonical 运行真相** |
| `escape-top/core/` | `from core...` | 仅 `test_portfolio_risk_budget.py` | 遗留重复树 |

我的修复落在 canonical 的 `hermes_escape_top/` 树（正确）。

---

## 2. 落地的修复（在 `.hermes` runnable 包）

逐文件备份后（`.review_backup_<ts>/`），把 round-2 修复落到 canonical 树：

- `core/portfolio/risk_engine.py` ← 整文件替换为修复版（本地是 pristine 原始版，无本地改动，安全替换）
- `core/portfolio/sizing_optimizer.py` ← 同上整文件替换
- `pipeline.py` ← **逻辑合并**（本地是 P18 版，含 IBKR 等 P13–P18 代码，不能整文件覆盖）：
  - 接回 `compute_confidence`（真实 6 分量),替换原"手搓单 gross"
  - 新增 `_data_confidence`(由 missing_weight 推导,落实「缺数据≠安全」)
  - 新增 `_max_staleness_days`(最新 bar 距 as_of)
  - failover/drift 传健康默认值,fragility/disagreement=0.0 占位
  - `_optimize_sizing` 增 `as_of` 参数 + 调用处传入
  - `_SizingProxy` 的 gross 上报改用 `risk_state.gross_scaler`(Gate ①)
  - 删冗余 `size_portfolio` 顶层 import + 死 `import math`

---

## 3. 测试结果

```
首次全量(仅落地 round-2 修复):   6 failed, 310 passed
```
逐一甄别 6 个失败 → **全部是预先存在、与本次修复无关**(把原始备份换回去跑,同样这 6 个红)：

| 失败 | 根因 | 是否我引入 | 处理 |
|---|---|---|---|
| `test_portfolio_risk_budget`(×5) | 遗留 `core/` 树里 `np.fill_diagonal(df.values,1.0)`——pandas 2.x CoW 下 `.values` 只读 → 抛错 | 否(原始码同样失败) | **已修**:改为在 `to_numpy(copy=True)` 上 fill 再写回(4 处) |
| `test_v25_parity`(golden,×1) | golden fixture 里 module B 评分 `weekly=78.70` vs 现码 `79.80`——**评分漂移**,与 sizing/confidence 无关 | 否(原始码同样失败) | **不动**(见 §4) |

修完遗留 numpy-2.4 bug 后的最终结果：

```
最终全量:   1 failed, 315 passed, 15 subtests passed
            ↑ 唯一的红 = 预先存在的 golden 评分漂移
```

**结论:round-2 修复 0 回归;新增修复了 5 个预先存在的 numpy-2.4 失败;唯一剩下的红是一处与本次工作无关的预存评分漂移。**

---

## 4. 为什么不直接重生成 golden

`test_v25_parity` 的 diff 出现在 `results.2026-05-26.FNGU.modules.B.items[0].reason`
(`weekly` 评分值),这是**评分层(module B)的改动**,不是我改的 risk/confidence/sizing;
而且在我动手之前就已经红了。直接 `generate_v25_golden.py` 重生成会:
1. 把这处**来路不明的评分漂移**一起"祝福"进 golden;
2. 同时把我的行为改动在**没跑回测验证**(你已明确推迟)的情况下固化。

二者都违反"不掩盖、不替未验证的改动背书"。所以**留红、交人工**:先查清 module B 评分为何漂移,
连同推迟的 Phase II–IV 回测一起,再有意识地重生成 golden。

---

## 5. 三份同步为一份

- canonical 运行真相 = `.hermes/.../hermes_escape_top/`(已修、315/316 绿)。
- 把**经测试的** `pipeline.py` / `risk_engine.py` / `sizing_optimizer.py` 同步回 repo `src/`,
  使仓库 `src/` 反映真实运行的代码(纯源码,**未**把 config/ibkr/web/data 推上公开仓库——避免泄密)。
- 遗留 `core/` 树的 numpy-2.4 修复只落在本地(该树是重复件,不进仓库;长期应删)。

---

## 6. 仍未做(诚实声明)

| 项目 | 状态 |
|---|---|
| **Phase II–IV 回测重跑** | **未做**(你本轮只要测试)。sizing 数学已变,旧 Sharpe/MaxDD/PBO 仍失效,须重跑后才能再称"已验证" |
| golden 重生成 | 未做(待查清 module B 漂移 + 回测后人工重生成) |
| 真实 failover/drift、E7/E22 | 仍占位 |
| 删遗留 `core/` 重复树 + 旧 `compute_portfolio_risk` | 未做(迁移任务) |

---

## 7. 真实数据 smoke test（端到端验证置信修复）

单元测试之外,又在 runnable 包里跑了一次**真实 `score_pipeline`**(`as_of=2026-05-29`,
真实历史数据;跑前备份 `signal_journal.jsonl`、跑后还原,无状态污染)。结果直接验证了
最关键的 🔴 修复在真实数据上成立:

| 指标 | 结果 | 说明 |
|---|---|---|
| `optimizer_confidence` | **0.696**(三腿一致) | 真实 spine 输出,**不是修复前的恒 0.5 永久 DEGRADED** → Fix #1 真数据验证 ✓ |
| `target_weight` | FNGU 0.20→0.139, SOXL 0.12→0.084 | ≈ reference × 0.696,**无双 gross、无 Kelly 砍仓** → Fix #2/#3 ✓ |
| MSTR | 0.0 | 其 rule target 本就为 0(裁决层决定),R3 行为正确 |
| `sizing_engine` | `optimize_targets_v1` | 单一处置入口生效 |

(运行时的 `IBKR ConnectionRefused` 是被禁用的 NEXT-6 只读对账在探测端口,与评分/仓位无关。)

**结论:置信脊柱接回 + 去双 gross + Kelly 默认关,在真实数据上产出 confidence=0.696 /
sane 仓位,修复确实生效。**

## 8. golden 根因定论(为何不重生成)

深挖 `test_v25_parity` 后定论:它测的是**独立的 standalone 单体脚本**
`scripts/escape_top_system.py`(v25 monolith,line 1484 的 `daily=/weekly=` RSI reason),
**与我修的 `hermes_escape_top` 包是完全不同的代码路径**。把 golden 非破坏性重生成后与现存版本 diff:
**798 行差异**,涉及 reason(95)/points(54)/flag(44)/raw_score(26)/calibrated_score(13)/
**status(6)/sell_pct(3)** 等决策相关字段,来源是三件事——

1. **numpy-2.x 浮点漂移**(如 `693.6088524588347 → 693.608852459202`,~1e-9)级联进评分取整;
2. 生成器**采样滑动日期窗口**(现在多了 2026-05-27 / 06-01)→ 随数据时钟推进本身不可复现;
3. 下游 `status`/`sell_pct` 变化(改变实际决策)。

直接重生成会把这些**未经审阅的决策变化**一并"祝福"进 golden,违反"不替未验证改动背书"。
故**已还原原 golden、不动**。该项需 owner:① 定 numpy-2.x 浮点基线;② 修生成器滑动窗口
不可复现问题;③ 审阅 status/sell_pct 变化——均与本次 review/修复无关。

---

## 复跑命令

```bash
VENV=/Users/liweishi/.hermes/hermes-agent/venv
P=~/.hermes/skills/investment/escape-top
cd $P && PYTHONPATH=$P $VENV/bin/python -m pytest -q          # 期望 1 failed(golden), 315 passed
```
