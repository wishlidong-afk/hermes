# CI 完整覆盖分组修复

基线：`81589f3ca67db81d482a00d0123939296237a0f4`。
工作分支：`codex/ci-complete-coverage`。当前仅本地候选，未提交、推送或部署。

## 原因与边界

GitHub run `41954174917` 在单一 verify job 的 20 分钟上限处取消，
pytest 最后显示 12%，无全套汇总；其后的静态、依赖审计、治理和编译被跳过。
既有冻结本地日志为 2288 passed / 1620.79 秒，已超过同一预算。
慢测表主要是 A2 的真实多进程隔离重放，每例约 20 秒。
这证明串行预算与当前套件规模不匹配，不证明 Ubuntu 与本机速度差异的具体成因，
也不证明未执行的云端测试没有缺陷。旧云端失败记录不会被覆盖或改写成 PASS。

## 精确范围

- `.github/workflows/ci.yml`：八组测试；独立 checks；最终 verify 完整性门禁。
- `scripts/ci_shards.py`：pytest 分组、执行阶段记录及只读汇总消费者。
- `src/hermes_escape_top/tests/test_ci_shards.py`：25 项真实子进程及反证测试。
- 本文：交接说明。无生产 Python、配置、依赖 pin、评分、路由、准入或部署脚本改动。

## 契约

1. 每组先收集完整测试，按排序后的 node ID 轮转分组，保留组内原执行顺序。
   原 2288 项均保留，新增 25 项工具测试后为 2313 项，首组 290 项，其余各 289 项。
2. 独立 checks job 另外收集全量清单。最终汇总必须与其相等，不能仅相信各组的总数。
3. 必须收到八份不同索引的报告，清单、版本、运行 ID、attempt 和工具 SHA 必须一致。
   每项须有唯一且完整的 setup/call/teardown 序列；显式 setup/call/teardown skip 保留原 pytest 语义，
   并单独报告 skipped_phases，不冒充测试断言通过。
4. 缺文件、损坏 JSON、错误选择、重复执行、未完成执行或失败退出一律不通过。
   报告摘要是绑定，不是签名或对抗同用户恶意代码的安全边界。
5. matrix `fail-fast: false`；每组、checks、最终 verify 均保留 20 分钟上限。
   静态、依赖审计、治理、编译不依赖测试组；非取消状态下各自执行，仍保留原命令。
6. verify 保留原 job ID，要求 test-shards 与 checks 都是 success，且完整性汇总通过。
   失败、取消、跳过不能变成成功。保留逐项日志、慢测耗时、JUnit 与清单报告。
7. 重试要求 GitHub 的 **Re-run all jobs**，不支持仅重跑失败任务。
   artifact 名称与下载过滤绑定 run_attempt，既不覆盖旧批次，也不混用旧批次结果。

## 验证与诚实口径

- RED：原来不存在分组工具，真实子进程测试失败；新增重复 call 反证曾失败，再修复通过。
- 新工具初版 24 项通过；内部复核追加 teardown skip 的 RED/GREEN，
  最终工具测试与 Web 本地 HTTP 夹具回归合计 55 项通过。
- 最终两文件完整 Ruff、原 severe Ruff、原四模块及两工具 mypy 通过。
- 治理 8/8、pip check、compileall 通过；actionlint 1.7.12 校验工作流通过。
- 最终独立清单再次证明原 2288 项零删除，新增 25 项全部来自 test_ci_shards.py。
- 独立 pytest 9.2.0 小环境中新工具 25 项通过；它不是整套业务在新解释器上的额外全量证明。
- 最终八组全量实际执行：**2313 passed**，每组退出 0；独立清单/并集/阶段记录汇总 PASS，
  skipped_phases=0。JUnit 另核 2313 项，零 error/failure/skip。
- 最慢组 289.94 秒，单组预算仍为 1200 秒；这是本机结果，不承诺云端同耗时。
- 验证前后三个实现文件字节不变，原冻结 512 文件仅 CI 工作流变化，其余 511 文件不变。
- 未改生产字节，复用先前业务等价证据；没有为 CI 配置改动重跑四日期业务比较。
- 现有完整 Ruff/mypy 债未扩大或豁免；未声称全仓静态零债。

本机最终验证根：`/Users/liweishi/Documents/New project/hermes-a2-git-delivery-2026-11-05/ci-repair-final/`。
初轮证据保留在同级 `ci-repair/`，不是最终字节全套结果。
初轮两组因 OS 全禁网而出现五项 HTTP 夹具 bind PermissionError，其余部分通过；
不修改断言或生产代码，修正本地验证规则后相关 55 项已通过。
各组有独立 HOME/TMPDIR；OS 拒外网、拒真实 `.hermes` 读取，只准实验目录写入；
允许回环 HTTP 夹具，显式拒绝 8766、4001/4002、7496/7497 的连接。
该规则不声称覆盖任意未知端口的本机服务，也不是生产配置修改。
本地最多同时运行两组，不把本机耗时承诺为 GitHub 的八组并行完成时间。
依赖审计命令本轮保留但未在拒网络环境重新查询漏洞库，不另行声称获得新的 pip-audit 结果。

## 发布状态与下一步

待本地验证及审查完成后，另按明确范围提交/推送，观察新的实际云端 CI。
新配置尚未在 GitHub 执行；本地通过不等于云端已修复。
PR #11 仍为 draft/unmerged；live 仍为 c1f4b8f。
DEPLOY HOLD；A1 生产证明 OPEN；A2 OPEN；Phase B 不启动。
不得通过跳测、扩大修订预算、调整准入阈值、补跑 daily 或改 live 来使 CI/晨验变绿。

额外只读发现：GitHub 对 `hermes-docs` 的 required_status_checks API 返回
`Branch not protected (HTTP 404)`，仓库规则集 API 返回空列表。
因此本候选保留 verify 名称，但不能声称 GitHub 已强制要求它通过才能合并。
后续应单独授权设置分支保护；本轮没有修改仓库权限或保护设置。

## 当前实现绑定与外审重点

新增两个源文件后，完整绑定为 514 个源文件；清单在最终验证根 candidate-binding.json。
其 files 字典按 UTF-8、sort_keys=True、separators=(逗号,冒号)、无末尾 LF 序列化后 SHA256 为
`66bce38cf6230d86fc29cbe4f84446fc8dae76c6c4e97af26f702cdcc20b324d`。
这不是旧 512 文件清单的 SHA，也不冒称原候选全部字节零变化。

| 文件 | 行数 | SHA256 |
|---|---:|---|
| `.github/workflows/ci.yml` | 122 | `19613e1295e3e0afd95fa928d1d355ffb4dcb832ea60f3d70f61d20a3666037c` |
| `scripts/ci_shards.py` | 124 | `f26df486d102def2cdcd4325e23f2e3cbe2892630255c4f00a8db5dc04fcc594` |
| `src/hermes_escape_top/tests/test_ci_shards.py` | 185 | `09db72379c14fcd3425bcec21826fc91af7ce81a3244a45d9eeebeb0078b8f70` |

内部复核曾发现两项 P2：teardown skip 兼容性及部分重跑的批次边界。
前者由真实失败回归修复；后者明确收窄为必须重跑全部任务，并按 attempt 隔离证据。
最终内部复核未发现剩余 P1/P2；不冒充外审批准。记录在最终验证根 internal-review.md。

建议独立复核：

1. 核对本表字节、三份实现及本文；范围外生产文件是否仍与冻结候选一致。
2. 读取原云端超时日志及既有本地慢测记录，不把速度差异推定为具体库版本缺陷。
3. 实际收集原/新清单，确认原 2288 node ID 全保留，新增仅 25 项工具测试。
4. 检查八组选择集合、独立 inventory、执行阶段和最终并集，不仅核算总数。
5. 对缺组、重复组、清单/版本/运行/attempt 冲突、坏 JSON、非零退出及重复 call 做反证。
6. 确认 setup/call/teardown 的合法 skip 保留 pytest 语义，失败与未完成不能伪装通过。
7. 检查检查任务与测试独立、四条原门禁命令保留、verify 不接受任何非 success 上游。
8. 检查取消/超时报告缺失、artifact 按 attempt 隔离；部分重跑必须 fail closed。
9. 复现新工具小测试与必要的真实分组；已有未变化业务证据可复用但必须标明来源。
10. 分别判定候选正确性、提交/推送及云端结果；不得据此批准部署或关闭 A1/A2。

参考：[GitHub 工作流语法](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)、
[pytest hook 接口](https://docs.pytest.org/en/stable/reference/reference.html)。

## 外审接收：提交前时点

2026-11-05 收到《CI 完整覆盖分组修复外审报告》。原文在最终验证根
`external-audit-report.txt` 按原字节归档，附件与归档 SHA256 均为
`ccb9a08dc9875f93c03dcf4f096135a694bee49acf0463c0ae796d279276513a`。
外审判定本地正确性 PASS，允许本表三份实现及本文按精确路径提交/推送；
云端 NOT YET，DEPLOY HOLD，A1 生产证明与 A2 仍 OPEN，Phase B 未启动。

接收时逐项重算 514 项源绑定，全部匹配，三份实现没有外审后漂移。
复用同字节的本地 2313 及各自静态证据，没有为纯文档接收重复跑全套。
以下处置只接收已审结论，不把外审、后续云端运行及部署授权混为一件事：

- P2-1 分支保护：记录为待单独授权的仓库设置，本轮不修改保护或权限。
- P2-2 云端未复跑：精确提交/推送后观察新的实际 run；未结束前不标为 PASS。
- P3-1 JUnit 未被 CI verify 消费：保留为后续加固，不改已审三份实现。
- P3-2 依赖审计：等待新云端 checks 执行原命令；本地 pip check 不是漏洞审计。
- P3-3 静态债：本片本地精确验证为原四模块加两工具 mypy；既有十五文件证据
  仍按原范围引用，不等同于当前 CI 命令，也不宣称全仓零债。
- P3-4 至 P3-8：并行度、初轮夹具限制、小环境范围、语法校验及本地绑定的
  既有边界继续保留，不用它们替代实际云端结论。

本节中的 NOT YET / 未提交状态属于提交前记录。后续提交、PR、云端 run 与
最终 conclusions 另在独立交付记录中保存，不重写旧超时日志或冻结本地证据。
