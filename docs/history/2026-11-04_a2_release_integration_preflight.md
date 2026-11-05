# A2 发布前集成预检与下一步计划

日期：2026-11-04，Asia/Shanghai。**本轮完成只读取证与临时三方合并预览，没有整合源码或执行迁移。当前发布前置仍不满足：DEPLOY HOLD；A2 OPEN；Phase B 未启动。** A/B/C的增量外审PASS保持，但不能当作完整发布树已与线上热修整合的证明。

## 1. 新发现的实际发布阻断

A2主目录与10月31日已发布热修是从共同祖先分出的两条代码线，不能直接拿A2目录覆盖live。当前A2的2179全套也没有涵盖缺失的热修测试，不能据此保证这些热修不回退。

| 代码线 | 已确认来源 |
|---|---|
| 共同祖先 | 2db0cdc562309b6222a69aaee8dbdaf51c763b93 |
| A2主目录HEAD | 8d16ad8ba639341a38ca5c29e278d12b81bb8efe，加已审但未提交的A2增量 |
| 已发布热修提交 | c1f4b8fc1df23876fefeccd33bc08e0270627f9e |
| 热修提交所在本地源码仓库 | /Users/liweishi/Documents/New project/hermes-r6-offline-tools-2026-10-30 |
| 本轮只读live版本 | c1f4b8f 20261031_113642 |

主目录本地对象库没有该热修对象；从已存在的独立源码仓库读取，使用进程级GIT_ALTERNATE_OBJECT_DIRECTORIES访问两库对象，求得真正共同祖先。未fetch、修改Git配置/ref/index、创建分支或合并。live的188个非测试Python文件与该热修提交逐字节匹配；这只绑定代码，不是重新验收健康或当前数据。

## 2. 必须保留的12条路径

下表只比较共同祖先到live提交的工具/依赖/包/测试路径，不包含完整文档证据清单，也不是整树迁移完成清单。

| 路径 | A2当前相对live热修的状态 |
|---|---|
| ops/run_daily.py | 仍为共同祖先版本，缺少live改动 |
| ops/verify_live.sh | 同上 |
| requirements.txt | 同上 |
| scripts/deploy_to_live.sh | 同上 |
| src/hermes_escape_top/web/health.py | 同上 |
| src/hermes_escape_top/tests/test_daily_failure_evidence.py | A2中缺失 |
| src/hermes_escape_top/tests/test_deploy_offline_verification.py | A2中缺失 |
| src/hermes_escape_top/tests/test_market_conflict_counts.py | A2中缺失 |
| src/hermes_escape_top/tests/test_deploy_to_live.py | 仍为共同祖先版本 |
| src/hermes_escape_top/tests/test_ops_entrypoints.py | 同上 |
| requirements.lock | 双方均修改；文本预览可无冲突合并为live锁，但尚未实际采用或验证新环境 |
| src/hermes_escape_top/scripts/run_daily_package.py | 双方均修改；三方文本预览有6个冲突区，尚未解决 |

计数为**10条路径缺失live改动、2条双方改动**，不是12个新运行故障。锁差异实际为certifi：A2为2026.4.22，live已为2026.10.19；锁预览SHA为71fc586a3909e80ae3c3fcc600e17d1082f39bae7ececed59a1c32038ba73e62，与已发布锁相同。保留live已审pin不是去解析“最新依赖”，本轮没有改pin或安装包。

六个冲突区需要同时保留：两组import/类型；live离线部署guard与A2 capture-aware签名；失败健康报告需要的payload上下文与A2本次commit observer；准确的run_receipt失败步骤标签与可选commit观测参数；正式FAILED对象/失败健康报告与A2失败观测转交。不能简单取ours/theirs，也不能把文本合并无冲突当作语义正确。

本轮仅在仓库外调用git merge-file -p --diff3生成预览；日报入口返回6表示文本冲突，锁返回0只表示文本合并成功。预览没有被执行、安装、写回任一源码仓库或当作A1证明。

## 3. A1证明必须区分两个独立的版本轴

只读取latest scheduled的身份元数据，未复制评分payload、持仓或账户数据：as_of=2026-11-03，事务协议recoverable-journal-v1，认证外层hermes-decision-certification-v1，**身份schema实际为hermes-decision-identity-v2**，revision=1、FINAL；scorer release=c1f4b8f，逻辑指纹42d207d6...。

因此“live v1”只能在明确上下文中指事务协议，不能据此认定线上仍是旧身份格式。现有verify_decision_identity_migration.py主要验证早期“无identity_schema_version的旧认证”转向身份v2，再检查旧writer拒绝预算重置；不能把它原样跑绿当作本次42d207d6...到ac025f0f...的发布证明。

当前V1_EQUIVALENT_RELEASES仅将25073bb和一个显式旧source指纹映射到42d207d6...，预算仍为2。本轮不加c1f4b8f→ac025f0f...豁免、不改投影/排除集，不因旧工具不适用便放宽验证。真正需要补的是**当前身份v2下的源码发布过渡与真实旧writer回滚**。

以上r1/FINAL是读取时的live元数据，不是重算结果，不证明现在发布会安全消耗一个r2；实际数据、最终集成源码和发布时决策日期都必须重新绑定。

## 4. 按依赖执行的更新顺序

### 第一步：单独构建离线集成候选

从已发布c1f4b8f来源与共同祖先出发，在新的隔离源码副本中带入全部已审A2前置，而不是只带C两个文件。两边原源码及C的25/51绑定保持冻结。先补齐上述10条路径和已审锁，再人工解决日报入口6区；同时保留默认capture OFF、原producer摘要、COMMITTED后的失败语义和live无刷新/无IBKR的部署guard。

验证：live热修对应失败步骤/新鲜失败健康报告、独立冲突计数、离线部署保护/参数位置、R6回滚测试与A2 producer/receipt/晨验测试共同通过。先做各交叉点RED/GREEN，再跑组合；新字节单独绑定/复审，不借A/B/C旧PASS或2179计数。未获Git授权前，不在原树cherry-pick、merge、stage或commit。

### 第二步：绑定最终候选与私有测试环境

重新生成最终集成源码清单、运行时锁SHA和评分指纹，核查所有已发布工具/依赖/测试都保留。旧A2的2da2dfa2...锁与C证据不是新锁71fc586a...环境的兼容证明。隔离环境按最终lock安装，再editable安装后pip check；不向live补装开发依赖。严格比较不得新增忽略项，ops仍须单独绑定。

验证：最终源上相关定点、全套、治理、静态、依赖和四日期OFF strict；新告警修复或明确登记，不通过删测试/加ignore过关。完整记录命令/解释器/源前后摘要，不预先把旧2179加上新测试数当成运行结果。

### 第三步：当前身份v2的A1过渡与回滚证明

复用现有scheduled worker、R6布局、恢复消费者及沙箱保护，另设明确的本次过渡矩阵。基线必须是已绑定的真实c1f4b8f代码，候选必须是第二步最终集成源码；合成种子/日期必须明示，不冒充live重算或自然样本。

- 同一as_of的旧r1/FINAL：验证候选如何消耗修订、重复是否稳定，列出全部认证变化和决策输出差异，不承诺scheduled完整字节相等。
- 合成旧r2场景：证据不足继续拒绝，七业务产物/审计身份保持，不能清audit/state或扩预算。
- 新决策as_of：保留旧链、建立新链并跨release稳定；不能把墙钟跨日当作业务日期变化。
- 真实旧writer回滚：验证读到新认证后的预算/身份守卫，不能重置为legacy；区分v2事务PENDING/COMMITTED对旧恢复器的影响，不把默认OFF测试当ON恢复证明。

测试必须同时隔离数据根和两个broker缓存路径、阻断socket，并绑定七产物与原失败原因；include_ibkr=False本身不足以证明缓存路径隔离。此步骤才产生候选级A1机制证据，本轮没有执行或完成它。

### 第四步：精确集成、CI与发布前审核

得到用户Git授权后，按审查来源与依赖顺序处理精确路径/增量，排除三份九月计划、私有capture和无关新字节；不能git add -A。云端必须针对最终提交/树验证，而不是引用c1f4b8f旧CI或8d16ad8旧CI。

本地原全套约24分钟，CI现有20分钟预算尚未实测最终候选：先测真实CI与用例分组耗时，再决定是否另片优化/调整，不擅自砍用例、改变断言或直接声称云端一定超时。本轮未运行CI、修改workflow或创建提交。

### 第五步：受控发布与后置观察

代码/CI/A1机制证据具备后，仍需用户对精确提交的单次R6与libexec安装分别明确批准，保留live config、无writer、避开07:00–07:20；capture启用是另一项明确决策，不由“部署”暗中启用。不借发布补跑official。

自然ON/v2样本、周末/周一身份序列及A2闭合是后置观察，不能用沙箱或live v1事务的既有3/3代替；也不能为了拿自然样本跳过发布前置。完整自动T1→T2、hermetic、更广故障/断电耐久性等既有开放项仍单列。Phase B不启动。

## 5. 证据与本轮完成边界

五件只读摘要独立保存于 `building/reports/a2_release_preflight/2026-11-04/`：integration-gap、conflict-responsibilities、live-source-binding、identity-axes、a1-proof-gap。没有复制真实账户/持仓/评分payload、私有数据集或三方预览源码入Git。预览、原始操作记录及Git index/config/HEAD前后核对保存在仓库外 `/Users/liweishi/Documents/New project/hermes-a2-release-preflight-2026-11-04/`。

本轮不重跑未变代码的2179全套，不把只读发现写成已经整合/迁移成功；不修改A/B/C源码或冻结证据、不stage/commit/push/install/deploy、不运行daily/晨验或刷新/连接IBKR。**已完成的是发布集成风险定位与执行顺序；下一可执行工程是第一步隔离集成候选，而非直接发布现有A2主目录。**
