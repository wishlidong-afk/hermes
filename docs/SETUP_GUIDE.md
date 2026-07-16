# Hermes 搭建指南（新人 / 新环境必读）

> **首次接触本项目？从这里开始。** 本文件覆盖：环境准备、目录结构、运行方式、开发规范。
> 更新时间：2026-06-02

---

## 0. 这个项目是什么

Hermes 是一套**只读**投资风控/逃顶系统，覆盖 MSTR / FNGU / SOXL 三个高波动标的。系统产出评分、裁决、理想仓位和资金路由建议，**绝不下单**。

两个子系统：
- **逃顶系统**：百分制评分 + 硬阀门 + 多层裁决 → EXIT/REDUCE/TRIM 建议
- **镜像参考**：右侧周期 + 理想配比（辅助参考，无硬阀门）

---

## 1. 阅读顺序（5 分钟上手）

```
1. docs/SETUP_GUIDE.md          ← 你在这里
2. docs/00_MASTER_OVERVIEW.md   ← 系统全貌（是什么/长什么样）
3. docs/CODEX_GUIDANCE.md       ← 当前优先级与下一步
4. building/STATUS.md           ← 实时进度账本
5. docs/PROJECT_REVIEW_2026_06_02.md ← 最新复盘（进度/问题/建议）
```

如果你是开发者，继续读：
```
6. docs/01_FUNCTIONAL_SPEC.md         ← 评分/硬阀门/路由/再建仓规则
7. docs/INTEGRATION_ARCHITECTURE.md   ← 整合架构（脊柱+引擎+优化器）
8. docs/BUILD_TICKETS.md              ← NEXT-0~6 工单
```

---

## 2. 环境要求

| 项目 | 要求 |
|---|---|
| Python | 3.9+ (3.10+ 推荐) |
| 操作系统 | macOS / Linux |
| 必需依赖 | `numpy`, `pandas` |
| 可选依赖 | `scipy` (优化求解器加速), `sklearn` (Ledoit-Wolf / 保序回归) |
| 数据源 | `yfinance` (价格回填), 本地 CSV 归档 |
| 磁盘 | ~500MB (含 2018+ 历史 CSV) |

### 安装

```bash
# 克隆仓库
git clone https://github.com/wishlidong-afk/hermes.git
cd hermes
git checkout hermes-docs

# 创建虚拟环境（推荐）
python3 -m venv .venv && source .venv/bin/activate

# 安装依赖
pip install numpy pandas yfinance
pip install scipy scikit-learn  # 可选，有 fallback
```

---

## 3. 目录结构

```
hermes/
├── docs/                           # 规格、架构、指南（低频更新）
│   ├── SETUP_GUIDE.md              ← 你在这里
│   ├── 00_MASTER_OVERVIEW.md       # 终极全貌
│   ├── 01_FUNCTIONAL_SPEC.md       # 评分/硬阀门/路由规则
│   ├── SYSTEM_OVERVIEW.md          # 十层架构 + 达标标准
│   ├── BUILD_TICKETS.md            # NEXT-0~6 工单
│   ├── ENHANCEMENTS.md             # E1~E30 增强
│   ├── INTEGRATION_ARCHITECTURE.md # 脊柱+引擎+优化器
│   ├── CODEX_GUIDANCE.md           # 当前优先级（施工指挥中心）
│   ├── ROADMAP.md                  # 总时间线
│   ├── STATUS.md                   # 进度账本
│   └── PROJECT_REVIEW_*.md         # 复盘文档
│
├── building/                       # 施工中枢（高频更新）
│   ├── STATUS.md                   # 施工进度（比 docs/STATUS 更详细）
│   ├── README.md                   # 双 Agent 接续铁律
│   ├── logs/                       # 每个任务的执行日志
│   ├── reports/                    # 阶段报告 + 回测结果 + JSON
│   ├── source_snapshots/           # 代码快照归档（历史版本）
│   │   ├── P0_synth_history/       # 合成杠杆历史
│   │   ├── P4_*/                   # 整合组件骨架（15个）
│   │   ├── P5_phase2_shadow/       # Phase II 生产版（当前基线）
│   │   ├── P6_phase3_dry_run/      # Phase III 比较器
│   │   ├── P7_*/P8_*/P9_*/         # Phase III WARN/sensitivity/exact
│   │   └── ...
│   └── desktop/                    # 用户侧原始规格
│
└── README.md                       # 仓库入口索引
```

### 本地运行环境（不在 repo 中）

实际可运行系统位于：
```
~/.hermes/skills/investment/escape-top/hermes_escape_top/
```

这是通过 P4 source_snapshots 同步到本地的完整包。270 package tests + 11 golden tests 在此目录运行。

---

## 4. 运行方式

### 4.1 运行测试

```bash
cd ~/.hermes/skills/investment/escape-top
python3 -m unittest discover -s hermes_escape_top/tests  # 270 tests
python3 -m unittest discover -s tests                     # 11 golden tests
```

### 4.2 每日评分（现有链路）

```bash
cd ~/.hermes/skills/investment/escape-top
python3 hermes_escape_top/scripts/run_daily.py
```

输出：评分/裁决/路由/审计报告 → `hermes_escape_top/reports/`

### 4.3 Phase II Shadow 回放

该命令使用 `core/research/integration_pipeline.py` 的研究 harness；生产 daily 始终使用 package 根 `pipeline.py`。

```bash
python3 hermes_escape_top/scripts/phase2_shadow_compare.py --days 20
```

输出：shadow 对照报告 → `reports/PhaseII_Shadow_Compare.md/json`

### 4.4 Phase III Dry-run 比较

```bash
python3 hermes_escape_top/scripts/phase3_dry_run_compare.py --days 252 --threshold 110 --penalty 0.90
```

输出：新旧对照 → `reports/PhaseIII_Dry_Run_Comparator.md/json`

---

## 5. 开发规范

### 5.1 铁律（不可违反）

1. **绝不下单** — 所有输出仅为建议/预览
2. **缺数据 ≠ 安全** — 缺失走 missing_weight/盲区，不补 0
3. **硬阀门优先于总分** — 触发即 EXIT 100%
4. **R3 不变式** — `w_i ≤ rule_target_weight` 任何时候
5. **确定性** — 同输入两次逐位一致
6. **live 开关由人翻** — features.use_* 默认全 OFF

### 5.2 代码风格

- Python 3.9+ 类型注解
- dataclass 作为契约（frozen=True 优先）
- 纯函数优先（无隐式 IO）
- 每模块行覆盖 ≥85%
- scipy/sklearn 可选，必须有手写 fallback

### 5.3 提交规范

```
[NEXT-X] 动词 + 关键结果（一行）
[P4] 动词 + 关键结果
[docs] 动词 + 内容

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

### 5.4 施工流程

```
1. 读 building/STATUS.md + docs/CODEX_GUIDANCE.md 确认优先级
2. 认领任务（改 STATUS 为 IN-PROGRESS 并推送）
3. 实现 + 单测
4. 写 building/logs/Px_*_LOG.md
5. 更新 building/STATUS.md + docs/STATUS.md
6. 推送（一次推送 = 一个完整可验收单元）
```

---

## 6. 关键数字速查

| 指标 | 当前值 |
|---|---|
| 成熟度 | M3 校得准 |
| missing_weight | MSTR 26 / FNGU 19 / SOXL 19 |
| 校准参数 | EXIT=75 / DEF_EXIT=65 / REDUCE=50 / TRIM=35 / WATCH=20 |
| 回测 (real-only) | CAGR 44.39% / MaxDD -10.43% / Sharpe 1.79 / DSR 1.66 |
| 回测 (full-proxy) | CAGR 18.13% / MaxDD -27.60% |
| PBO (deployment fixed) | 0.1538 PASS |
| 候选参数 (P9) | corr_threshold=110 / penalty=0.90 |
| P9 全窗口 | CAGR 20.37% / MaxDD -24.32% / Sharpe 1.0171 |
| 测试 | 270 package + 11 golden |
| 整合组件 | 15 个 + E1-E30 全覆盖 |
| Phase 进度 | P0-P9 全 DONE；Phase III REVIEW-GATED |

---

## 7. 常见问题

**Q: 为什么 repo 里没有可运行的 Python 包？**
A: 实际可运行代码在本地 `~/.hermes/` 中。repo 的 `building/source_snapshots/` 是快照归档，用于版本追溯和多 Agent 协作同步。

**Q: feature flags 在哪里？**
A: `hermes_escape_top/integration_config.py` 的 `default_integration_config()["features"]`。全部默认 OFF。

**Q: 怎么判断一个 Phase 是否已通过？**
A: 看 `building/STATUS.md` 的状态列。DONE = 代码+测试完成；REVIEW-GATED = 需要人工审阅才能上线。

**Q: 我能直接翻 live 开关吗？**
A: 不能。所有 `features.use_*` 由人决定，且必须有对应的 dry-run 达标报告支撑。

---

## 8. 联系与贡献

- 主仓库：https://github.com/wishlidong-afk/hermes
- 分支：`hermes-docs`（当前活跃）
- 施工指挥中心：`docs/CODEX_GUIDANCE.md`
- 进度看板：`building/STATUS.md`
