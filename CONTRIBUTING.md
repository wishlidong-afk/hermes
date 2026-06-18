# 开发规范 CONTRIBUTING

这是一个**只读投资防守系统**——它的可信度建立在「数据真实、指标前后一致、永不下单」上。下面的规范不是形式，每一条都对应一个曾经踩过的坑。

## 0. 三条不可破的红线（PR 触碰即拒）

1. **永不下单。** 系统只产建议 / 理想仓位 / 订单*预览*。IBKR 连接 `readonly=true`，任何写单路径都不允许出现。
2. **缺数据 ≠ 安全。** 缺指标一律走 `missing_weight` + 盲区惩罚，绝不当作"正常/无风险"。
3. **硬阀门优先于总分，触发即 EXIT。** 阀门参数未经回测校准不得上线；开关由人翻，代码不得自动开启未验证的因子。

## 1. 分支与提交

- **工作分支：`hermes-docs`**（不是 `main`）。所有改动在此分支上做。
- 一个改动一个主题，diff 收敛——只动任务要求的行，不顺手重排/改风格/删别人的死代码（发现了在 PR 里说，交给人定）。
- 提交信息：祈使句标题 + 必要的「为什么」。AI 协作提交结尾加：
  ```
  Co-Authored-By: Claude <noreply@anthropic.com>
  ```

## 2. 测试——先证明，再说完成

```bash
cd src && python -m pytest            # 全量套件，必须全绿
python -m pytest tests/test_xxx.py    # 单文件
```

- **改了行为就要有测试。** 修 bug：先写一个能复现的失败测试（看它因正确的原因失败），再修到它通过。
- 不要写"祝福 bug"的测试（断言错误的当前行为）。本项目栽过：FRED `publish_date` 的两个旧测试断言了有 bug 的取值，修真因时必须连测试一起改正。
- HTML 渲染相关断言注意转义（`<=` 会被渲染成 `&lt;=`）。

## 3. 部署：仓库 → live，强制过门

代码不是改完就生效——live 在 `~/.hermes/skills/investment/escape-top/hermes_escape_top/`，要显式部署：

```bash
bash scripts/deploy_to_live.sh
```

该脚本的纪律（**不要绕过**）——**任一步失败即自动回滚(解 tar + 重启)并退非零**，不是只提示：

1. **并发守卫**：`pgrep run_daily` 检测到 daily/刷新在跑就中止——不在运行上叠部署；
2. **备份**：tar live 代码（排除 `data/`，一键可回滚）；
3. **`rsync --delete` 仓库 → live = 真 0 drift**（repo 删/改名的文件 live 也清），写 `VERSION=<hash>`；并从 [`ops/`](ops/) 同步 live 入口脚本（`run_daily.sh` / `run_daily.py` / `serve_dashboard.sh`）；
4. **smoke gate**（[`predeploy_smoke.py`](src/hermes_escape_top/scripts/predeploy_smoke.py)）：FRED publish_date、常驻日频源、无源回归、证据链无 NA、manifest 不漂移、（WARN）无法解释的翻转。**FAIL → 自动回滚**；
5. **重启** dashboard：`launchctl kickstart -k gui/$(id -u)/com.hermes.dashboard`；
6. **端到端验收**：curl 8766 == 200 + [`ops/verify_live.sh`](ops/verify_live.sh)（真入口走 `manual_rerun`，断言回执/manifest/NEXT5 效果落地）。**FAIL → 自动回滚**；
7. 全绿才 commit `.hermes` git。

> 真原子切换（软链 release）是 Phase 2，按触发器延后（多机 / 撞出过不一致 / 自动化常态敲刷新端点时再上）。跨进程锁已随 #3（`2beea7d`，`core/safe_io.py` 的 `pipeline_lock`）完成。
> 改了影响每日官方管线的东西，部署后用 8766 WebUI 亲自确认落地，别假设。

## 4. 数据纪律（这个系统的命门）

- **PIT（point-in-time）只认发布日。** `asof_pick` 按 `publish_date` 取数；FRED 的 `publish_date = 数据日 + 1 天`，**不是** `realtime_start`（用查询日会让所有行同值、PIT 失效——A10 real_rate 曾因此被清零）。
- **run_type 标记。** `scheduled`=当日官方；`manual_rerun`=盘中预览。两者在 audit / UI 里必须分得清，不能让盘中重算污染官方记录（SOXL「REDUCE→斩仓→REDUCE」假翻转的根因之一）。
- **不给假数据、不给假建议。** 取数失败就如实标 MISSING + 走盲区惩罚，绝不用 0 / 上一日 / 猜测值顶替。指标前后一致性 > 一切。
- 大型 append-only 文件（`audit_log.jsonl` 100MB+）用 tail-read，别整文件读；由 `rotate_audit_log` 无损归档后压缩保留。

## 5. 文件该放哪

| 类型 | 位置 | 进 git？ |
|---|---|---|
| 代码 | `src/hermes_escape_top/` | ✅ |
| 常青文档 | `docs/` | ✅ |
| 历史复盘 / 校准 / code-review | `docs/history/` | ✅（归档，不再改） |
| 回测 / gate 产物（校准脚本输入） | `building/reports/` | ✅ |
| 历史施工日志 | `building/history/` | ✅ |
| **运行时产物**（logs/orders/reports/data、audit、journal、sqlite） | 同名目录 | ❌ 已 gitignore |
| **密钥**（`fred_api_key.txt`） | — | ❌ 永不提交 |

新增"某次跑出来的东西"前先问：这是**别人 clone 后需要的输入**，还是**本机跑出来的产物**？后者一律 gitignore。
