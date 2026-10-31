# R6 离线工具外审接收与增量修复

日期：2026-10-31。状态：P1 已按反证修复，本地验证完成；未提交、未推送、未部署。

`DEPLOY HOLD; A2 OPEN; Phase B not started`。旧 `2ec779c` 的 R6 授权不覆盖本轮新字节。

## 1. 接收范围与来源

候选仍在 `/Users/liweishi/Documents/New project/hermes-r6-offline-tools-2026-10-30`，分支 `codex/r6-offline-deploy-tools`，HEAD 仍为 `2ec779ce834d5745f9bd4488e3eafa917115de3a`。

收到的外审结论是“受测路径 PASS，但 P1 必须修，提交/推送有条件允许，R6 不具备条件”，不是无条件批准。原文按原字节保存在验证目录的 `external-audit-original.txt`，含原有 CRLF，SHA256：

`740b82a8049f6735f89ee5da7d34c1baa0f0a9830e52d8ff1148b8503c945aac`

本轮验证目录：

`/Users/liweishi/Documents/New project/hermes-r6-offline-validation-2026-10-30/evidence/2026-10-31_external_audit_followup/`

## 2. Findings 处置

| 外审项 | 处置 |
|---|---|
| P1-1 来源参数错位后被忽略 | 修复。先真实复现：`--main --source-repo PATH` 在假根下错误完成默认来源部署。修复后所有残留来源选项（含 `--source-repo=...`）、多余参数、未知模式均提前 exit 64。主模式仅允许无参数或一个 `--main`；内部模式必须恰好四参数。 |
| 内部复核补充：显式空模式 | 修复。仅参数缺省时默认 `--main`，显式空字符串拒收。还补了内部模式恰好四参数时把来源选项藏入 STAMP/BACKUP 的反证；不能只靠参数个数检测。 |
| P2-1 CP 输出去向 | 加固。先复现外置 stdout/stderr、继承 stdout、缺省输出四种情况被错误接受；现只允许 stdout 和 stderr 均为 `subprocess.PIPE`，与真实事务 `capture_output=True` 调用一致。原四种 CP 反证也改为携带合法 PIPE 输出，避免靠“缺输出配置”提前拒收而漏测其他守卫。 |
| P2-2 进程内而非 OS 保护 | 接受既有边界。不新增 OS 沙箱，不声称阻挡同用户恶意代码、ctypes、fork 或所有原生网络调用。 |
| P2-3 列表形式 lscpu | 保留 fail-closed；未为未观察到的跨平台调用新增兼容路径。 |
| P2-4 估值相对路径的 cwd 前提 | 加固。先复现不同 cwd 可进入 guard，再显式要求 cwd 的解析位置等于私有 runtime 根。实际 `run_daily.py` 已设置该 cwd，正常入口不变；不宣称此前正常入口已发生该问题。 |
| P2-5 旧 1550 与最终 1551 证据口径 | 旧文件全部保留，均属上轮时点；本轮最终是 1570，不能用旧日志替代。 |
| P2-6 非 WAL 一致复制 | 接受既有边界。继续依赖无 writer 纪律，不冒称 A2 捕获、断电耐久或完整恢复证明。 |

所有实际代码修复均先观察到相应反证失败，再修复、再验证；没有运行真实部署来复现。

## 3. 精确增量

相对外审已核过的七文件候选，本轮仅四文件改变：

| 文件 | 最终 SHA256 |
|---|---|
| `scripts/deploy_to_live.sh` | `d5cc34022514857a5dbf99b7caaa2af1ccd2b3d055d9356b4671e4b5ff723fad` |
| `src/hermes_escape_top/scripts/run_daily_package.py` | `2831d8cbfd114567656f56fd523e4b2683246f97992fe016c8363f8e2ac3151a` |
| `src/hermes_escape_top/tests/test_deploy_to_live.py` | `9ce333e60845fca5f83ee97fb8820061049b57f2b5495683978f9108aff785c7` |
| `src/hermes_escape_top/tests/test_deploy_offline_verification.py` | `ecdc63e54eee6d224c1edd355ca4b308f5bf7cd721c22efd4f4690e062c30cb4` |

`ops/run_daily.py`、`ops/verify_live.sh`、`test_ops_entrypoints.py` 仍与外审 SHA 完全相同。原交接只追加时点注记，新增本接收文档；没有修改配置、flag、依赖锁、评分/路由、身份/修订、比较器或排除集。

验证目录 `before/` 的四份副本均匹配外审的原 SHA。两份是修改前直接复制；部署脚本与部署测试是在首次 P1 修改后反向删除明确增量重建，再验证原 SHA，不冒称它们是在最初时点冻结的副本。外审候选本身未提交，`before/` 不冒充独立 Git 基线。

## 4. 最终验证

| 检查 | 结果 |
|---|---|
| 定点组合 | **132 passed / 33.91s**，含发布源 57、离线 31、ops 入口 35、失败日报 9；同一次组合运行 |
| 全套 | **1570 passed / 176.61s**，比外审的 1551 增加 19 项 |
| Governance | 8/8 OK，`ibkr_readonly=true` |
| 四日期 strict | `all_equal=true`，2022-01-03、2022-01-25、2026-05-29、2026-06-04 全等；七业务工件、payload、input_hash 未变 |
| 全仓 severe Ruff | E9/F63/F7/F82 PASS |
| 其他变更 Python 完整 Ruff | PASS |
| wrapper 扩大 mypy | 仍为原五条、同消息同行号；没有新增 ignore/exclude，不宣称扩大 mypy 全绿 |
| 其余 | shell 语法、编译、diff whitespace 检查通过 |

CI 指定四模块与其上轮通过的字节相同，复用既有通过结果；外部故障演练实现与依赖也未改，复用原 13 场景证据。本轮没有重复运行这些不受改动影响的检查，也不声称产生了新的 GitHub CI。

内部增量复核另做了 48 种非法参数和 8 种合法调用的只读解析探针，全部符合契约；还确认真实事务复制及输出拒收、cwd 拒收。本条是内部复核者执行，不是作者又独立运行一轮，更不是独立外审批准。

## 5. 证据分层

- 本轮只引用同名新目录中的 `focused.log`、`full-suite.log`、`equivalence.json`、`governance.json` 和 `source-binding.json` 作为最终证明。
- `before/` 用于四文件逐行增量复核；`handoff-before.md` 用于原交接正文前缀校验。
- `interim-*` 是最终参数补全前的工作记录，其中包含 1567/129 时点；不作为最终候选证明。
- 2026-10-30 原 `preservation.json`、1551/1550 日志、两份比较 JSON、故障演练全部保持原字节，未覆盖更新。新 `source-binding.json` 同时核对原证据、四份 before、七文件当前 SHA、比较器与评分指纹。
- 新目录由验证目录 `verify_followup.py` 只读核验保护对象并生成绑定；脚本只写自己的验证证据。哈希是绑定，不是签名。

评分指纹仍为 `42d207d6b6c84001bf85324ea6af84b5947c7748b7217d72f0d715b21232ad8a`；比较器仍为 `19540147b21004355d0f54eb14c0455301bddb870b47a370b0a753178d5bd76d`。

## 6. 授权与下一步

主目录 A2 的 13 项源码绑定、22 件冻结证据匹配；已审热修目录仍干净且为 `2ec779c`。live 仍为 `releases/2db0cdc_20260922_233427`，配置 SHA 仍为 `5cff823ecaec5a5e9b8595f102e7f25d888ab9d1b2f7efb5dc856ec832d67d09`。

本轮没有 stage/commit/push/deploy，没有运行真实 morning acceptance、official daily、行情/外部源刷新或 IBKR，没有修改 live 或调度。假 HOME/临时根内的部署与回滚是测试，不是线上发布。

P1 与两处边界的作者验证已完成；旧外审 PASS 不转借给这四份新字节。后续只需针对四文件增量与最终绑定做接收核验，不必重复审冻结的 A2 整树。提交时仍须显式列出原七文件及本批交接路径，排除主目录 A2、三份九月计划、验证环境与私有 capture；不得 `git add -A`。

提交/推送与部署分开：取得相应 Git 操作授权、确定新精确提交并检查新 CI 后，才讨论一次明确授权的 R6。仍须无 writer、避开北京时间 07:00–07:20、保留 live 配置及标准服务/回滚预检；不得补跑 official 来造通过证据。安装后自然运行观察、A1/A2 与 Phase B 门槛均未关闭。
