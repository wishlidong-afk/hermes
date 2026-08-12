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
PYTHONPATH=src:src/hermes_escape_top/tests python -m pytest src/hermes_escape_top/tests -q
PYTHONPATH=src python scripts/check_governance_consistency.py
```

- **改了行为就要有测试。** 修 bug：先写一个能复现的失败测试（看它因正确的原因失败），再修到它通过。
- 不要写"祝福 bug"的测试（断言错误的当前行为）。本项目栽过：FRED `publish_date` 的两个旧测试断言了有 bug 的取值，修真因时必须连测试一起改正。
- HTML 渲染相关断言注意转义（`<=` 会被渲染成 `&lt;=`）。

## 3. 部署：仓库 → live，强制过门

代码不是改完就生效。live 由 `~/.hermes/skills/investment/escape-top/current` 指向一个不可变 release，必须显式部署：

```bash
bash scripts/deploy_to_live.sh
```

该脚本的纪律（**不要绕过**）——任一步失败都会回滚并非零退出：

1. 停止 dashboard，并用 Python `fcntl` **单次持有**与 daily/refresh 相同的 `.pipeline.lock`；
2. 备份 `current/previous`、入口、共享运行态和 `.hermes` git index；
3. 构建 `releases/<hash>_<stamp>/` staging，挂载 shared `data/reports/orders`，写 `VERSION`；
4. 对 staging 跑 import 与 [`predeploy_smoke.py`](src/hermes_escape_top/scripts/predeploy_smoke.py)，config 差异必须人工回答；
5. 用 `os.replace` 原子切换相对 `current` 软链，随后释放锁并重启 dashboard；
6. `curl 8766` 与 [`ops/verify_live.sh`](ops/verify_live.sh) 在隔离数据副本上跑 `manual_rerun` 验收，不写官方 receipt/audit/state；
7. 全绿才按 allowlist 提交 `.hermes` 的代码、入口、VERSION 和软链；绝不 `git add -A` 运行态。

回滚同样停止 dashboard、重新持有整段 pipeline lock，并恢复软链和备份；回滚失败必须输出 `DOUBLE FAILURE`，不得伪报 `deploy OK`。
> 改了影响每日官方管线的东西，部署后用 8766 WebUI 亲自确认落地，别假设。

## 4. 数据纪律（这个系统的命门）

- **PIT（point-in-time）只认发布日。** `asof_pick` 按 `publish_date` 取数；FRED 的 `publish_date = 数据日 + 1 天`，**不是** `realtime_start`（用查询日会让所有行同值、PIT 失效——A10 real_rate 曾因此被清零）。
- **run_type 标记。** `scheduled`=当日官方；`manual_rerun`=盘中预览。两者在 audit / UI 里必须分得清，不能让盘中重算污染官方记录（SOXL「REDUCE→斩仓→REDUCE」假翻转的根因之一）。
- **不给假数据、不给假建议。** 取数失败就如实标 MISSING + 走盲区惩罚，绝不用 0 / 上一日 / 猜测值顶替。指标前后一致性 > 一切。
- **仓库不是运行数据根。** 从 git checkout 直接启动 `score`、dashboard/Web refresh 或 daily 时必须显式设置 `HERMES_DATA_DIR`；缺失时入口会在加锁、写回执或评分前拒绝运行。测试、回放和研究任务应指向隔离副本；R6 live 入口继续显式指向 shared runtime。
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
