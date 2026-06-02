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

## 复跑命令

```bash
VENV=/Users/liweishi/.hermes/hermes-agent/venv
P=~/.hermes/skills/investment/escape-top
cd $P && PYTHONPATH=$P $VENV/bin/python -m pytest -q          # 期望 1 failed(golden), 315 passed
```
