# A2 3C-5h-A 外审接收与处置

日期：2026-11-04，Asia/Shanghai。当前候选独立外审 **正确性 PASS，精确范围具备提交/推送资格；DEPLOY HOLD；A2 OPEN；Phase B 未启动。** 技术许可不等于本轮用户授权 Git 写操作或部署。

## 1. 原文与来源

用户提供的附件：`/Users/liweishi/.codex/attachments/0c652b9e-740c-405b-8c54-2b9f79889dd6/已粘贴的文本.txt`。

原文已逐字节归档为同目录 `2026-11-04_a2_3c5h_external_audit_report.md`，保留附件的 CRLF 等原始字节，不改写外审结论。附件与归档文件 SHA-256 均为 `4153f47a48065a38541d0ba023b23752c78ed0632741723af46bd9cac02a9433`，13539 bytes。本记录不是第二次外审，不把作者接收复核写成外审员再次执行。

外审范围为 3C-5h-A 的三个生产文件加两个新测试，增量基线是三份 before 和 slice.patch，不是整棵 dirty tree。候选 HEAD 仍为 `8d16ad8ba639341a38ca5c29e278d12b81bb8efe`。

## 2. 本轮接收复核

- 重新计算 source-binding.json 的 5 个实现/测试与 8 个依赖：13/13 匹配。
- 重新计算 SHA256SUMS.json 中的 22 项：22/22 匹配；该清单自身 SHA-256 为 `984f8b246304240af6eaffa1336a5bbfffc971d9d2902402c928cbadec2312bd`。
- 定点对照了原子写入字节与摘要出口、COMMITTED 后 observer/lease/回滚边界、capture-only 转发、receipt 九字段及时间校验、生产入口默认 OFF，未发现与本次反馈冲突。
- 本轮不修改源码、测试、配置、依赖、比较器或冻结 JSON/log/patch；不重新执行未变化代码的全套、静态或历史等价性检查。
- 40 新测试、234 关联、2056 全套、8/8 治理、四日期 OFF strict 与故障演练的本次独立执行均归属外审员，执行时间按原报告保留，不冒称作者本轮重跑。

一处表述精度补充：原文把 as_of 与 decision_id 合称“非空”，实际 helper 对 as_of 做的是与调用者传入的本次日期精确相等，对 decision_id 才显式检查非空字符串；helper 本身不是对任意 as_of 参数的独立日期格式/非空校验器。原文原样保留，接收结论按实际调用绑定契约理解，不扩大该 helper 的承诺；本轮不为此添加未请求的实现校验。

| 本次外审员报告的独立执行 | 结果 |
|---|---|
| 新测试 | 40 passed / 94.85s |
| 八文件关联 | 234 passed / 90.97s |
| 全套 | 2056 passed / 1525.18s |
| Governance | 8/8 OK，ibkr_readonly=true |
| 静态门禁 | 指定 Ruff/severe、14 模块 mypy、compile/diff 检查通过 |
| 扩大范围技术债 | mypy 16→15，无新增归一化消息；Ruff 19→19，消息集合不变 |
| 四日期 OFF strict | 4/4 空差异，候选 375/06fcbc10...，比较器未变 |
| 故障演练 | 13/13 达到各自预期状态，零网络、未触 live；不是十三个源都返回 OK |

## 3. Findings 处置

外审未发现 P0/P1，没有提出本片必须修改的实现缺陷。以下限制接受并保留，不用无关重构、忽略项或配置豁免消除记录。

| Finding | 处置及后续要求 |
|---|---|
| P2-1 候选 A1 指纹门槛 | 保留 OPEN。候选 ac025f0f... 与 live 42d207d6... 不同；独立补候选发布/迁移/旧 writer 回滚证明，不能由 OFF strict、2056 测试或 live 的自然 PASS 推定，不新增等价豁免。 |
| P2-2 本机信任边界 | 保留。receipt 观测是本机 producer 声明，不是签名；下一片先唯一选择正式 run/audit，再精确核对身份并把原观测摘要交给未改动的 5g，禁止事后自算 journal 摘要兜底。 |
| P2-3 静态债 | 如实保留 15 条类型债和 19 条 Ruff 消息，另片处理。14 模块门禁 PASS 不改写成全部生产文件静态清零，不加 ignore/exclude。 |
| P3-1 时间窗 | 保留 started <= committed <= now 的保守时区/窗口检查，不宣称单调时钟保证。没有本轮时钟机制修改。 |
| P3-2 SIGKILL 范围 | 保留两例仅最小事务边界的口径，不扩张为完整 daily/broker/断电或 SQLite 耐久性证明。 |
| P3-3 提交后 active/backups | 保留由后续持锁恢复清除的契约；observer/cleanup 失败不能倒滚已 COMMITTED 的业务，也不自动签发 finished receipt。 |
| P3-4 默认 OFF | 按设计继续关闭，无 CLI/config/flag/scheduler 启用，不借接收外审接入生产。 |
| P3-5 自然样本分离 | 11-04 的 live c1f4b8f/v1/42d207d6...、最低 3/3 仅属已发布热修观察，不是 A2 v2/ac025f0f... 的 ON 样本；五日目标及 A2 门槛独立。 |

## 4. 本轮文档改动

只新增本接收记录、原文归档，并对以下三文档末尾追加状态注记，原文字节前缀保留：

- `2026-10-21_a2_3c5h_commit_observation_handoff.md`。
- `2026-10-21_a2_3c5h_anchor_source_contract.md`。
- `2026-10-03_a2_production_capture_wiring_plan.md`。

旧正文的 pending 是当时的状态，现由本次追加更新为 **3C-5h-A 当前冻结候选外审 PASS**；不是整树无条件批准，也不意味着后续适配实现已完成。旧证据清单不为新增文档重新生成。

本轮前后文件清点、三份原文前缀及归档 SHA 复核保存于工作区外私有目录 `/Users/liweishi/Documents/New project/hermes-a2-5h-audit-reception-2026-11-04/`，不混入本片提交范围。

## 5. 后续 Git 范围与授权边界

本轮未 stage/commit/push/deploy。外审允许的技术范围是本片 slice.patch 绑定的三处生产增量、两个测试及其证据/交接，不是整棵主目录累积变更获批。特别是 pipeline.py、run_transaction.py、run_daily_package.py 均有本片以前的累积内容，**即便只按这三个文件路径 stage，也不能保证增量范围正确**；应按 before/slice.patch 识别前置来源和组合范围，不能把路径窄误当成内容窄。

后续如获 Git 授权，提交说明须分列本片及已审前置，不混入三份九月计划、其他未经相应审查的新字节、私有 capture 或 live 数据；不得 git add -A。新提交须再检查对应 CI，不以本轮接收记录替代。

## 6. 下一工程片

按原契约第 5.B 节实施离线只读运维适配，单独增量、单独验证/外审：

1. 唯一选择正式 receipt/scheduled audit/run，匹配全部身份，重复/错日期/旧 run 不猜测。
2. 明确 v1/OFF 且无混合元数据：INFO / NOT_APPLICABLE；不调用 v2/5g。
3. v2 缺锚、未知协议、混合元数据或错绑定：UNKNOWN；不能把缺失说成成功。
4. 使用本机 producer receipt 的原 journal 摘要，不自行重锚；5g 的 UNKNOWN/WARN/INFO/OK 原样分层传递，不覆盖主 runtime/strategy FAIL。
5. 不读当前缓存，不联网或连接 broker，不加锁/恢复/补发，不先改 WebUI/晨验或启用 capture。

本轮只接收外审，未实施上述适配。完整自动 T1→T2、hermetic 环境、更广故障/耐久性、候选 A1 证明、CI、明确授权与自然 ON 观察继续各自保留。**DEPLOY HOLD；A2 OPEN；Phase B not started。**
