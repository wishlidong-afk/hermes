# R6 发布源选择与离线验收工具修复

日期：2026-10-30。状态：实现及本地验证完成；未提交、未推送、未部署。

本片只修发布工具，不混入主目录冻结的 A2 候选。`A2 OPEN; Phase B not started`。
用户此前对 `2ec779c` 的一次 R6 授权没有被执行，也不自动授权本片的新字节。

## 1. 范围与基线

- 独立目录：`/Users/liweishi/Documents/New project/hermes-r6-offline-tools-2026-10-30`。
- 分支：`codex/r6-offline-deploy-tools`。
- 基线 HEAD：`2ec779ce834d5745f9bd4488e3eafa917115de3a`。
- 候选：本目录 `git diff HEAD` 加新增离线测试；本文件是交接文档。
- 测试环境及证据：`/Users/liweishi/Documents/New project/hermes-r6-offline-validation-2026-10-30/`。

实现与测试仅以下七文件，不包含依赖、配置、flag、评分器、身份/修订、比较器或部署目标的变更：

| 文件 | 最终 SHA256 |
|---|---|
| `scripts/deploy_to_live.sh` | `03ba272da2a55ace3c2e62c3e6f11254babf15e44746e3021f2eed132ee02996` |
| `ops/run_daily.py` | `7d36cd2b437ce4f00292688c435385b860c9be917bc611070e391ca9a4022685` |
| `ops/verify_live.sh` | `8b22844ee3634fa7f701c9edd4256e8483a2f0049baadb4f751a133ce6212f59` |
| `src/hermes_escape_top/scripts/run_daily_package.py` | `261d9717e36afe240e8a4993bb82b950723e45d94bf165142d9666a2e5cf1d49` |
| `src/hermes_escape_top/tests/test_deploy_to_live.py` | `8c389cfcd3f105eef5c6bbb4fe43d29c38cf38790dd0d79a66c2fa035aa19b2f` |
| `src/hermes_escape_top/tests/test_ops_entrypoints.py` | `503c5a15b0b1e7943b7c664b824d526ad8384c4f857132efd1be723b39dc11de` |
| `src/hermes_escape_top/tests/test_deploy_offline_verification.py` | `f9e660209f05d014487859379f73b4c0d43eec0a6acacca26791ba896ba6d731` |

## 2. 已修契约

1. 生产发布源可用前置参数 `--source-repo /absolute/git/root` 显式指定；默认来源不变。拒收缺参、相对路径、非 Git 或非根目录。生产仍忽略测试环境中的路径替换变量。
2. 显式来源的部署脚本必须与执行中的脚本字节一致。保留原有部署源范围的 HEAD/脏文件/未跟踪文件检查，且在准备运行环境、停止仪表盘之前拒收。这里的清洁检查沿用部署源码范围，并非全仓任意文档清洁检查。
3. 参数穿过持锁 swap 和两条 rollback 路径。原配置审批、锁身份、smoke、备份、回滚与提交范围保护没有移除或降级。
4. `--deploy-verify` 进入专用隐藏模式：`--live --skip-refresh --run-type manual_rerun`，禁止 `--commit-state`。普通 scheduled/manual 入口默认行为不变。
5. 验收使用新建的私有容器及 `runtime/` 数据根。默认 `../data/history` 落在同一容器的兄弟目录；不改 live 配置。历史、慢数据、归档、默认 legacy 和估值缓存只复制到临时副本。估值缺失以私有空快照表达，避免回退读取 live 估值文件。
6. 写入前检查模式、私有根标记、目录权限、全部配置路径的实际解析位置和容器内符号链接。无法证明隔离的自定义外置路径拒收，不自动重写配置。
7. 显式 `include_ibkr=False` 同时跳过持仓与成交读取。跳过行情、见证、外部源和辅助刷新；不重新冻结市场 manifest。NEXT5 运行真实模块，但在当前进程内执行，保持其 0/1 业务语义。
8. socket 调用和未许可子进程拒收；即使内部捕获异常，验收仍失败。仅允许固定 `/bin/cp -c` 在私有容器内复制事务备份，禁止 shell、替换 executable/env 或越界目标。NumPy 可选 `lscpu` 探针不执行，返回缺失异常走其原有降级路径。
9. 验收门禁要求本轮非官方 audit、评分及 NEXT5 步骤、离线完成标记；没有离线标记或出现官方 receipt/state 日志均失败。临时容器退出时清理。

## 3. 验证结果

测试解释器：上述验证目录 `.venv/bin/python`，Python 3.11.15。Ruff 0.15.22，mypy 2.3.0。测试中的 FRED key 是合成值。

| 检查 | 结果与范围 |
|---|---|
| 原部署/入口基线 | 66 passed，修改前实际运行 |
| 发布源与原部署回滚 | 43 项，包含显式来源、持锁递归、两条回滚及原保护；全部包含在最终全套中 |
| 最终离线专测 | 26 passed，包括完整真实入口链路及绝对路径 `..` 反证 |
| 最终全套 | **1551 passed in 156.68s**；不是此前的 1550 日志 |
| Governance | 8/8 OK，`ibkr_readonly=true`；本片没有配置改动 |
| 四日期严格等价 | `all_equal=true`；2022-01-03、2022-01-25、2026-05-29、2026-06-04，七业务产物及 payload 严格一致，比较器原字节不变 |
| 外部故障演练 | 13 场景契约通过，零网络、未触 live；不表示每个场景返回 OK |
| CI 同款静态检查 | 全仓 E9/F63/F7/F82 通过；CI 指定四模块 mypy 通过 |
| 扩大静态范围 | wrapper 原有 17 条 Ruff、5 条 mypy 与基线相同；其他变更 Python 文件完整 Ruff 通过；没有新增 ignore/exclude |
| 其余 | shell 语法、编译、`git diff --check` 通过；验证环境 62 个已安装包兼容，生产依赖 pin 未变 |

完整链路测试在假 HOME/假安装目录执行生产分支：`verify_live.sh -> run_daily.sh -> run_daily.py -> package main`。未替换评分、认证或持久化逻辑；观察钩子只在入口返回后复制私有结果供断言。实际确认七产物 COMMITTED、无 active、manual audit、IBKR disabled、成交 SKIPPED、原 receipt 未改、未提交 state.json、NEXT5 落盘，以及源文件字节和 mtime 不变。不是自然 scheduled 样本或实际 R6 服务切换。

本片为未提交候选，尚无对应的新 GitHub CI；旧 `2ec779c` 的 CI 不替本片背书。依赖锁未变，本轮不宣称重新做过漏洞扫描。

## 4. 内部复核与证据

内部只读复核发现 P2：`resolve_path()` 对绝对路径保留 `..`，直接 `is_relative_to()` 只是词法判断。新增 `absolute_parent` 用例先失败，再补 `.resolve()`；最终 26 专测及 1551 全套通过。复核者另用真实临时锁探针确认：拒收发生在锁入口之前，无越界目录生成。P2 已闭合。此为内部复核，不是独立外审或部署授权。

可复用教训：包含性检查必须先规范化路径，再比较容器边界；“隔离写入”不等于“没有刷新/网络”，“manual_rerun”也不等于离线。

验证目录的 `evidence/`：

- `full-suite.log`：最终 1551，SHA256 `efb4a28709740095c474720f97d0fe9eb9c9f7921f42190f67da0bfc75da49e3`。
- `equivalence.json`：最终严格比较，SHA256 `bf323b149532b58f34d0becb7cf2d743cc11e8522e5f45bccc860da39cf03335`。
- `external-drill.json`：故障演练。
- `preservation.json`：七文件绑定、指纹与保护对象复核。由验证目录的 `verify_preservation.py` 生成，只读核对保护对象。
- `before-review-fix-*`：P2 修复前的 1550 测试与比较记录，保留原字节；不能冒充最终候选证明。

基线/候选评分指纹同为 `42d207d6b6c84001bf85324ea6af84b5947c7748b7217d72f0d715b21232ad8a`，排除集未改。严格比较直接调用评分管道，不替代新增入口/锁/网络边界测试，也不覆盖 `ops/` 和仓库根 `scripts/` 的来源绑定；这些由本节七文件 SHA 单独登记。

## 5. 保护边界与下一步

- 主目录 A2 的 13 项源码绑定、22 件冻结证据全部匹配。没有把三份九月计划、私有捕获或本机验证环境加入本片。
- 已审热修目录仍干净且 HEAD 为 `2ec779c`。live 仍是 `2db0cdc 20260922_233427`，配置 SHA256 仍为 `5cff823ecaec5a5e9b8595f102e7f25d888ab9d1b2f7efb5dc856ec832d67d09`。
- 没有执行真实 morning acceptance、官方 daily、行情/外部源刷新或 IBKR 连接；没有改调度或 live。
- 网络限制是当前受审 Python 验收入口的进程内保护，不是 OS 网络沙箱、同用户恶意代码边界或完整 A2 hermetic 归档。数据复制仍依赖既有无 writer 纪律，不宣称提供 WAL 一致捕获、断电耐久性或完整系统恢复证明。
- 下一步只对本片七文件做窄范围外审，重点攻击来源递归/回滚、绝对路径与链接越界、网络错误吞没、CP 白名单、IBKR 双读取禁用和真实入口产物；不要重审冻结的 A2 整树。
- 外审接收后才显式提交/推送本片并检查新 CI，确定包含本工具修复的新精确发布提交，再另行确认一次 R6。此前授权不能被解释为对未知新提交的授权。不得借发布补跑官方日报来消红。
- 部署前仍需无 writer、避开北京时间 07:00–07:20、保留 live 配置及标准服务/回滚预检；部署后等待自然运行验证。本文不关闭行情冲突、A1/A2 观察或 Phase B 门槛。

## 6. 2026-10-31 外审接收注记

以上正文与 SHA 表保留 2026-10-30 时点，不冒充当前候选。后续外审发现来源参数错位 P1；本轮已修复，并补紧 CP 输出与 cwd 两处边界。最终 1570 全套、132 定点及四日期 strict 的新证据，见同目录 `2026-10-31_r6_offline_tools_external_audit_followup.md`。旧 1551/1550 证据与原正文前缀保留；未提交、未推送、未部署，仍 `DEPLOY HOLD; A2 OPEN`。
