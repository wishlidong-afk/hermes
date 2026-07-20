# Hermes 逃顶 + 镜像系统

> **只读风控/建议系统 — 永不下单。** 产出建议、理想仓位、订单*预览*；IBKR 连接 `readonly=true`。
> 覆盖标的：MSTR / FNGU / SOXL（逃顶）+ QQQ↔FNGU、SOXX↔SOXL、MSTR↔QQQ（镜像）。

Hermes 在单边上涨的牛市里替你守纪律：每天收盘后跑一条 10 层量化管线，给每个标的打分（A/B/C/D 四模块）、检查硬阀门（触发即 100% EXIT 建议）、按 DEFCON 等级路由资金、用三锁约束再建仓，最后把结论渲染到本地 WebUI。它不替你赚钱，它替你在该跑的时候**有纪律地提示跑**。

---

## 怎么读这个仓库（按角色）

| 你是… | 从这里开始 |
|---|---|
| **第一次接触** | [`docs/SETUP_GUIDE.md`](docs/SETUP_GUIDE.md) → 本文「仓库结构」→ 下方「阅读路线」 |
| **来做 code review** | 本文「仓库结构」+「怎么验证它在正常跑」→ [`docs/01_FUNCTIONAL_SPEC.md`](docs/01_FUNCTIONAL_SPEC.md)（事实源）→ `src/hermes_escape_top/core/` |
| **来改代码 / 接着施工** | [`CONTRIBUTING.md`](CONTRIBUTING.md)（规范）+ [`docs/CODEX_GUIDANCE.md`](docs/CODEX_GUIDANCE.md)（施工优先级） |
| **要给 AI agent 喂上下文** | [`context.md`](context.md)（一份给 agent 的技术总览） |

## 仓库结构

```
hermes/
├── README.md            ← 你在这：项目门面 + 导航
├── CONTRIBUTING.md      ← 开发规范：分支 / 提交 / 测试 / 部署门 / 三条红线
├── CHANGELOG.md         ← 变更流水
├── context.md           ← 给 AI agent 的深入技术总览
├── requirements.txt
│
├── src/hermes_escape_top/        ← 全部代码
│   ├── core/            ── 引擎：data(取数+PIT) / scoring(打分+硬阀门) /
│   │                       decision(裁决+再建仓+信号日志) / factors(因子实验室)
│   ├── web/             ── 本地 WebUI：server.py(loopback HTTP + 受控刷新) + render.py(纯 payload→HTML)
│   ├── scripts/         ── 可运行入口：run_daily_package / predeploy_smoke / check_next5_unlock …
│   ├── tests/           ── pytest 套件
│   └── config/          ── config.json（开关、阈值、provenance）
│
├── docs/                ← 常青参考文档（见下方「阅读路线」）
│   └── history/         ── 只读归档：历史复盘 / 因子尸检 / 校准报告 + code-reviews/
│
├── scripts/             ← 顶层运维脚本（deploy_to_live.sh、各类诊断/回测）
├── ops/                 ← live-only 入口/调度的版本化副本（run_daily.sh/.py、
│                          serve_dashboard.sh、launchd plist）+ verify_live.sh 端到端门
└── building/            ← 施工工件
    ├── reports/         ── 回测 & gate 产物（含全量回测 JSON，校准脚本的输入）
    ├── logs/            ── 施工/构建日志
    └── history/         ── 历史施工日志（FIX_LOG / PLAN，按日期归档）
```

> 运行时产物（`logs/ orders/ reports/ data/`、audit/journal、sqlite、FRED key）已 `.gitignore`，不进仓库。

## 怎么跑 & 怎么验证它在正常跑

系统由 **launchd** 托管，无需手动常驻。四个 job：

| job | 时间 | 作用 |
|---|---|---|
| `com.hermes.daily` | 每日 07:10 | 跑当日官方管线（`run_daily_package`），写 audit / 渲染 UI |
| `com.hermes.watchdog` | 每日 09:00 | 数据新鲜度 / 漂移看门狗 |
| `com.hermes.dashboard` | 常驻 | 本地 WebUI，唯一入口 **http://127.0.0.1:8766** |
| `com.hermes.next5watch` | 常驻 | NEXT-5 元标签解锁累计器 |

```bash
# 看 launchd job 是否在册 / 是否报错（非 0 exit）
launchctl list | grep com.hermes

# 唯一 WebUI（8765 旧台已退役）
open http://127.0.0.1:8766

# 重启 dashboard
launchctl kickstart -k gui/$(id -u)/com.hermes.dashboard
```

部署由 [`scripts/deploy_to_live.sh`](scripts/deploy_to_live.sh) 完成：在同一把 pipeline lock 内构建并验证不可变的 `releases/<hash>_<stamp>/`，再用 `os.replace` 原子切换 `current` 相对软链。失败会恢复 `current/previous`、入口和共享运行态并重启 dashboard；不会直接覆盖正在服务的代码目录。测试与部署细则见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。

## 阅读路线（按顺序）

| # | 文件 | 作用 | 读者 |
|---|---|---|---|
| 0 | [`docs/00_MASTER_OVERVIEW.md`](docs/00_MASTER_OVERVIEW.md) | **终极全貌**：是什么/架构/三层演进/现状/下一步/安全红线 | 先读这个 |
| ★ | [`docs/CODEX_GUIDANCE.md`](docs/CODEX_GUIDANCE.md) | **施工指引**：已完成项 + 当前优先级 | 动手前必读 |
| 1 | [`docs/01_FUNCTIONAL_SPEC.md`](docs/01_FUNCTIONAL_SPEC.md) | **功能规格（事实源）**：A/B/C/D 因子、硬阀门、缺数据、裁决、路由、再建仓、镜像 | 想知道"系统怎么判" |
| 2 | [`docs/SYSTEM_OVERVIEW.md`](docs/SYSTEM_OVERVIEW.md) | **系统全景**：L0–L10 十层架构、数据流、达标标准、成熟度阶梯 | 想看架构 |
| 3 | [`docs/BUILD_TICKETS.md`](docs/BUILD_TICKETS.md) | **基线施工**：NEXT-0~6 函数级工单（到 M3/M4） | 要动手建基线 |
| 4 | [`docs/ENHANCEMENTS.md`](docs/ENHANCEMENTS.md) | **进阶提升**：E1–E30 函数级工单 | 基线之后增强 |
| 5 | [`docs/INTEGRATION_ARCHITECTURE.md`](docs/INTEGRATION_ARCHITECTURE.md) | **整合架构**：1 脊柱 + 4 引擎 + 1 优化器 | 整合落地 |
| 6 | [`docs/ROADMAP.md`](docs/ROADMAP.md) | **统一路线图**：串成一条总时间线 + 当前可开工项 | 决定先做什么 |
| — | [`docs/STATUS.md`](docs/STATUS.md) | **进度账本**：每步状态，与各文档对账 | 持续更新 |

历史复盘、因子尸检、校准报告、逐行 code review 全部归档在 [`docs/history/`](docs/history/)（含 [`code-reviews/`](docs/history/code-reviews/)）。

## 三条不可破的红线

1. **不下单**——只产建议、理想仓位、订单预览。
2. **缺数据 ≠ 安全**——一律走 missing_weight + 盲区惩罚。
3. **硬阀门优先于总分，触发即 EXIT；参数未经回测校准不得上线，开关由人翻。**
