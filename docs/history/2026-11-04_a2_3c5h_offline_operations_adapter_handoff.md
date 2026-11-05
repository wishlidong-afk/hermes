# A2 3C-5h-B：离线正式运行到辅助发布观测

当前状态：候选实现和本地验证完成，待独立外审。**DEPLOY HOLD；A2 OPEN；Phase B 未启动。**

## 1. 范围与增量基线

本片实现原 `2026-10-21_a2_3c5h_anchor_source_contract.md` 第 5.B 节的离线适配部分，不是晨验/WebUI 接线。3C-5h-A 的外审 PASS 只绑定它的旧字节，不自动覆盖这两个新文件：

- `src/hermes_escape_top/core/reporting/scheduled_broker_publication.py`：唯一公开入口 `read_scheduled_broker_publication(*, archive_dir, acceptance_date)`。
- `src/hermes_escape_top/tests/test_scheduled_broker_publication.py`：正式运行选择、模式与信任边界、路径及只读行为测试。

没有修改已有 producer、receipt writer、5g reader、评分/身份/修订、事务/锁/恢复、晨验、WebUI、配置/flag、依赖/比较器或部署脚本。未新增 CLI、定时调用方、锁、数据库、锚点目录或补发器。本片运行时调用方仍为零；测试中的调用不算生产接线。

HEAD 为 `8d16ad8ba639341a38ca5c29e278d12b81bb8efe`，但增量基线是实施前的当前 3C-5h-A 工作树快照，不是整个 `git diff HEAD`。比较器基线由 HEAD archive 加当时所有当前 Python 文件的原字节覆盖构成，375 文件清单仍精确匹配先前 5h-A 的 `06fcbc1075c200a5703e185dd8bdaed889d38e6920be648d90bb81f5490123af`。未暂存、提交或推送来制造基线。

| 本片源码 | SHA-256 | 行数 |
|---|---|---|
| scheduled_broker_publication.py | 252ff92908980dbdae08254ff33a9c3983677b918c6717326f66775fe006b947 | 160 |
| test_scheduled_broker_publication.py | 144aeaceb278eec5c7424670ac77ed9ccd6e1e58bace38295e266a8db6337c04 | 402 |

比较器源码清单差集为仅新增这两文件、零删除、零共有文件变更；因此也可从当前候选排除两新文件重建375文件的基线清单，不能把未提交快照说成一个已存在的Git commit。

最终证据目录：`building/reports/a2_production_capture/2026-11-04/3c5h_offline_adapter/`。其中 `before_review/` 的两份 Python 副本只是内部P2修正前字节，供复现回归，不是375文件的增量基线，也不算额外生产接线。源码/依赖绑定、精确命令、环境、日志、内部复核与范围保护分开记录；旧5h-A证据不被刷新或覆盖。

## 2. 选择与只读路径

1. 只读给定 archive 下固定的正式 `run_receipt.json` 和 `audit_log.jsonl`，不接受用户自选 journal 路径。
2. receipt 必须为完成的 scheduled `OK/FAILED`，`ok` 必须为对应布尔值，时间带时区、完成日期为北京时间 acceptance_date，开始/结束窗口有效。
3. 沿用晨验“按北京时间执行日唯一 scheduled audit、与正式 receipt 的业务 as_of 一致”的选择语义。由于原选择器位于 ops 私有脚本，本片没有从 reporting 反向导入 ops，也没有抽取/修改已审入口；新模块独立实现该契约，并增加保守拒收。
4. 审计还须位于 receipt 调用时间窗；外层 as_of/input_hash 如存在不能与 payload 冲突，业务日期须为规范 ISO 日期，run_id/input_hash 格式须有效。
5. 对 receipt、audit、journal 使用重复键拒绝的 JSON 解析；遇到损坏行、无法解析的 scheduled 时间、未知 payload schema 等保留 UNKNOWN，而不是跳过后声称唯一。比现有晨验的部分历史行跳过行为更保守，但没有改变晨验本身。
6. 支持当前无 schema 的正式 receipt 和当前/未标注的历史 score payload；新增未知 receipt schema、平铺 protocol 或不支持的 capture 元数据位置保守拒收，不猜未来格式。

receipt 与 writer 时间以秒精度记录结束值，audit/commit 可含微秒；结束边界采用 `< finished_at + 1 second`，不是无条件扩大任意时间窗。不是单调时钟或时钟可信性证明。

## 3. 模式与信任契约

| 条件 | 输出与执行 |
|---|---|
| 已选 v1/OFF，且 receipt/persistence/payload 无已知 capture 混合标记 | INFO / NOT_APPLICABLE / CAPTURE_DISABLED；不查 journal、不调用5g |
| 已选 v2 但 receipt 无 commit_observation | UNKNOWN / ANCHOR_UNAVAILABLE；不现场计算 journal SHA 兜底 |
| 重复/错日期/损坏审计、非正式/未完成 receipt、未知协议或不一致模式 | UNKNOWN；不猜最近 run |
| 观测九字段、schema、协议、run/capture/decision/input/as_of、格式或时窗不符 | UNKNOWN / ANCHOR_INVALID |
| 观测与已选 journal 的 as_of/capture_id/committed_at 不符 | UNKNOWN，即便测试给换后的 journal 重新算了摘要也不能替换所选身份 |
| 本机 producer receipt 观测与所选身份匹配 | 使用观测原 journal_sha256 调用未修改的5g；不以重新计算的值作为新信任根 |
| 5g 返回 UNKNOWN/WARN/INFO/OK | 原样传递辅助状态、原因、cache 声明；不升级成整体健康或真实缓存核验 |

适配层在读 journal 元数据后，由 5g 核对原始摘要、COMMITTED v2、完整身份/清单与冻结材料。两次读取沿用既有本机串行纪律，不宣称文件快照隔离或抵抗同用户并发换文件。

`anchor_source=LOCAL_PRODUCER_RECEIPT` 标记摘要来源，不是签名，也不是 journal/缓存一定已通过验证的替代物；若 5g 返回 UNKNOWN，仍是 UNKNOWN。新报告 schema 为 `hermes-scheduled-broker-publication-v1`，且始终 scope=OPERATIONS、strategy_blocking=false、cache_contents_verified=false。

`official_receipt_status` 独立保留原 OK/FAILED。即便辅助声明 status=OK，原正式 receipt 仍可为 FAILED：这不是总体 PASS。本片不接受/修改总体 runtime/strategy 结果，也不重写 receipt；未来接线仍须保留主链 FAIL。

## 4. 测试口径与内部修正

- 一例真实评分事务/正式 receipt 端到端使用已审 producer 路径，include_ibkr=False；周围报告/行情/健康依赖由既有 fixture 隔离。删除临时当前缓存后仍读取成功；没有运行真实 official daily。
- 其余选择矩阵复用真实最小 v2 提交/冻结 tape 的 fixture，但正式 receipt/audit 是明确的合成选择材料。它们不冒充 producer 签发或自然运行；PUBLISHED/WARN/INFO 的子读取器语义由未改动5g实际执行。
- 检查当前文件字节、mtime、模式不被 observer 改写；定点禁止 socket.connect 与 sqlite3.connect。拒收符号链接、目录、FIFO，已知 capture 标记跨层混入，极端时区时间溢出，重复审计，旧同日同 decision 但不同 run 的回执。
- 两次内部复核不是独立外审。最初发现 v1 平铺 capture 标记漏判和时区 OverflowError 泄漏；先用回归用例复现，再仅修改新模块，增加20个相关边界用例。复核42项选定测试通过，不把这当作正式外审批准。
- 修正前56新/213关联和首轮strict输出另留私有 intermediate 目录；首轮全套在开始后被主动停止以修复新源码，不作为通过结果。最终证据必须绑定修正后字节。

## 5. 当前验证

| 检查 | 当前结果 |
|---|---|
| 新文件 | 76 passed / 9.77s |
| 六文件关联 | 233 passed / 88.36s |
| Governance | 8/8 OK，ibkr_readonly=true |
| 新两文件完整 Ruff / 全仓 severe | PASS / PASS |
| 既有14模块加新模块 mypy | 15 files，PASS，无新增ignore/exclude |
| compile / pip check / diff check | PASS |
| 外部故障演练 | 顶层PASS，13场景达到各自预期，零网络、未触live；不是全部源OK |
| 四日期默认OFF strict | all_equal=true，4/4 strict_differences=[]，比较器未改 |
| 评分指纹 | 基线/候选均 ac025f0f93d16ee3b97e1aaa8f7e70b49801032d81085453b7e5531eae8e7dad |
| 全套 | 2132 passed / 1434.09s，exit 0；最终源码SHA前后一致 |

候选源码清单为377文件、`570da621b80bdf8e4b24af3942d7fc7666efe0a5b51f8d17711be210b281c917`。四日期为2022-01-03、2022-01-25、2026-05-29、2026-06-04；同一解释器、同一57文件公开种子，严格比较评分与七业务，不增加忽略项。该比较不验证新 observer 的运行输出，由专属测试覆盖，亦不替代自然ON观察。

扩大生产范围已有15条mypy/19条Ruff债未在此片清零；已有文件未改，因此沿用5h-A的明确债务记录，不能宣称全仓静态干净。新模块/test 的完整检查独立通过。

本地全套约24分钟；现有CI job的timeout-minutes为20，CI机器速度与本地不同，不能直接推定一定超时，也不能据本地PASS声称CI已绿。新提交CI尚未运行，后续须单独核实运行预算/分组；本片未修改CI或放宽超时。

## 6. 独立外审要求

请先重算两新文件与依赖/证据SHA，再逐行审选择、模式、锚点到5g的传递，不用作者PASS标签替代实证。重点独立验证：

1. v1无混合元数据才不适用；v2缺锚/未知模式不猜成功。
2. receipt日期、唯一audit、同次窗口及全部身份匹配；同as_of/decision不允许借旧run回执。
3. 原producer摘要被传递，journal改变不能自动重锚；元数据与重锚反证要真正触达身份分支。
4. 5g状态原样传递；FAILED正式receipt不被辅助OK覆盖；未知不是“发布失败”或“缓存陈旧”的证明。
5. 路径、JSON重复键、畸形、FIFO和时区溢出都拒收且不留写入副作用；原数据根为可信调用方参数，不能扩大成全机安全边界。
6. 一例真实producer整合与合成选择矩阵的边界如实；只读测试不冒充真实broker或自然样本。
7. 两新文件以外已审源码/配置/比较器/依赖/九月计划/冻结证据不变，无生产调用方、晨验/WebUI/flag/调度接线。
8. 分别给正确性、精确范围commit/push资格、部署/阶段闭合判定。旧5h-A外审不能自动批准本片新字节。

## 7. 未完成范围与权限

本片未提交、推送或部署；没有读取真实 IBKR 缓存、刷新数据、修改live或现有系统晨验任务。下一步独立外审本片，再另行评估晨验字段/适用性接线和I/O频率，不直接上WebUI或自动补发。

自动T1→T2完整生命周期、hermetic运行环境、更广故障/耐久性、候选ac025f0f...的A1发布/迁移/旧writer回滚证明、CI与明确发布授权、自然ON样本继续保留。已发布c1f4b8f/v1/42d207d6...的自然3/3或五日观察不能替代这些门槛。**DEPLOY HOLD；A2 OPEN；Phase B未启动。**

## 8. 最终封存

最终全套于本轮完成，2132 passed / 1434.09s；验证调度器退出0，运行前后两新源码SHA一致。76新/233关联、四日期OFF strict、治理/静态/故障演练均绑定同一最终字节；不把修正前结果沿用为最终证明。

source-binding.json 绑定两新源码加18个保留依赖；SHA256SUMS.json 绑定24件证据（含明确标记的两份内部修正前副本），清单自身SHA-256为 `b9d8515b9b3d37f3d62fd0928fe451b9b6115e1bd4e00a7537b0bbda1b759cc9`。正文交接不在该清单内，以免循环绑定。旧5h-A的13源码/22证据保持匹配，旧清单未被重生成。

开始时1228个已列举仓库文件中1226个原字节不变；仅原契约与总计划两个旧文档追加本片进度，旧字节前缀SHA匹配。实现为两新源码，另有本交接和新证据目录；三份九月计划未动。主仓库未stage/commit/push/deploy；测试夹具的临时目录不等于生产运行或发布授权。

封存后的下一动作是独立外审当前两新文件及其证据，非直接接线或部署。本片独立外审仍待执行；5h-A的外审PASS与内部复核都不自动覆盖本片。**DEPLOY HOLD；A2 OPEN；Phase B未启动。**

## 9. 2026-11-04 后续内部复核发现

继续任务时，新的内部只读复核发现两项P2：未知audit外层schema仍可能被当作已知格式；过深JSON的RecursionError没有转成UNKNOWN。两项均已用测试先复现再修复，只修改本片新模块及测试，新增10项回归/兼容控制用例。旧76/233/2132、旧两源码SHA和24件冻结证据保持原样，只证明修正前字节；不得将本节后的当前源码与旧清单默认为一致，也不以本次内部复核冒充独立外审。

当前修正候选及验证进度改见 `2026-11-04_a2_3c5h_offline_adapter_review_fix_handoff.md`；修正结果和新证据另存，旧正文前缀/日志/清单不刷新。修正后仍须完成对应验证和独立外审，不提前晨验/WebUI接线或Git/部署。**DEPLOY HOLD；A2 OPEN；Phase B未启动。**

## 10. 2026-11-04 组合外审接收注记

当前B加两项P2修正组合已独立外审PASS，见 `2026-11-04_a2_3c5h_b_external_audit_{report,followup}.md`。本文件旧76/233/2132及24件证据继续只绑定旧B；本次外审批准的是修正后86/2142的当前字节，不是追认旧B单独已审。243关联摘要缺完整命令的限制已在followup明确，外审的七文件247不能冒充其精确复现。原待审文字保留为时点记录；当前候选具备精确范围提交/推送技术许可，仍无本轮Git/部署授权或生产接线。**DEPLOY HOLD；A2 OPEN；Phase B未启动。**
