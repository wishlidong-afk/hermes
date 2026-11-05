# A2 3C-5h-C 外审接收与处置

日期：2026-11-04，Asia/Shanghai。**C片及指定B/5g/producer前置交互独立外审正确性PASS；精确增量具备提交/推送技术许可；未获本轮Git、系统安装或部署授权。DEPLOY HOLD；A2 OPEN；Phase B未启动。**

## 1. 原文与来源

用户附件：`/Users/liweishi/.codex/attachments/f7299070-2ecc-4c7d-8d05-c11ae97e6f81/已粘贴的文本.txt`。原字节归档为 `2026-11-04_a2_3c5h_c_external_audit_report.md`，12146 bytes；两者SHA-256均为 `f1d564d344bbecf08bd3315e7f3e8345de64dace5db80bd0b5d67c217aa57793`。包括附件原有空行与用量文字，不改写审计员原文；本接收不是第二次外审。

## 2. 接收核验与执行归属

本轮作者重新计算25项源码/依赖与51件C证据：全部匹配，清单自身仍为 `a74e9de973493a6763026a33a4eadb8d6f54df3ae0f6bc0ff8505f9c63ec4d8e`。ops仍为217857aa.../1484行，新测试仍为e42644e8.../329行，未修改源码、测试或冻结证据。

旧A22、旧B24、review_fix33件及三清单均匹配；A的13源码绑定仍匹配。review_fix仅ops一项被C有意改变，余19项仍匹配；旧B则保留B修正前两源码以及旧ops三处已声明差异，不伪称旧包全都匹配当前源码，不刷新旧清单。

| 本次外审员独立执行 | 结果 |
|---|---|
| C新测试 | 37 passed / 7.03s |
| 明确四文件关联 | 182 passed / 16.46s |
| 全套 | 2179 passed / 1416.34s |
| Governance | 8/8 OK，ibkr_readonly=true |
| 指定15文件mypy | PASS |
| 扩大ops检查 | 前后4条，消息相同、仅行号移动 |
| 两文件完整Ruff / 全仓severe | PASS / PASS |
| compile / pip check / diff check | PASS |
| 重建与四日期OFF strict | 377/24f37156...，378/3389d65d...，57/8557342f...，4/4空差异，输入哈希与冻结结果一致 |
| 故障演练 | 13场景达到各自预期，顶层PASS、零网络、未触live；不是13个源全部OK |

上述执行归属外审员；作者本轮只读核对绑定、源代码及解释器/任务配置，没有再次运行未变化代码的全套、晨验、strict或故障演练。作者原2179/1421.17s和外审2179/1416.34s是不同次运行，均按原值保留。

## 3. P2/P3处置

外审无P0/P1，没有提出本片必须修改的实现缺陷。以下门槛/限制继续保留，不通过无关源码修改、忽略项或增加预算去消除它们。

| 外审项 | 处置 |
|---|---|
| P2-1 A1候选证明 | OPEN。ac025f0f...与live报告中的42d207d6...分列；发布/迁移/旧writer回滚及scheduled certification证明另做。OFF strict、2179测试或live v1的3/3不能代替，不新增等价豁免。 |
| P2-2 本机信任 | 保留LOCAL_PRODUCER_RECEIPT非签名限制；前后快照只检测可见变化，不证明对抗同用户/ABA/敌对OS。 |
| P2-3 静态债 | producer15类型/19Ruff与ops4类型消息分别登记。15文件门禁不含C新测试，不写成全部修改文件类型清零；新测试完整Ruff已覆盖。 |
| P2-4 证据范围 | 明确保留：src-only strict不覆盖ops，ops由source-binding/before/patch和专门集成测试单独证明，不给比较器扩大忽略或覆盖声明。 |
| P3-1 内联12组对照 | 仅补充内部复核证言，无单独保存探针/日志SHA；不把它当包内可独立复算的门禁。19定点与作者/外审37、182、2179分列。 |
| P3-2 RED/GREEN历史 | 保留夹具错误与修正日志，不能将其改称生产缺陷或一次全绿；不改原主检查期望。 |
| P3-3 异常可观测性 | 接受当前非阻断UNKNOWN及不泄露堆栈的取舍；异常类型/位置诊断是后续可选改进，不为此改变刚获批准的字节。 |
| P3-4 解释器范围 | 按第4节澄清；保留系统安装件/真实ON运行未验证的限制，不把3.9的tmp-v1测试扩大为生产证明。 |
| P3-5 CI预算 | OPEN。本地23分36秒与CI20分钟分列；候选级CI未执行，不先声称超时或云端绿，不删测试或擅改预算。 |
| P3-6 旧依赖 | 旧ops985c617d...到C217857aa...是显式增量，历史包保留。 |
| P3-7 I/O样本 | 保留本机夹具/非冷缓存/未测长期增长的限制，不据此跳过validator或缓存最近成功。 |

## 4. P3-4的解释器事实澄清

原报告中“生产安装件运行时是3.11.15”不能直接用于主晨验安装脚本。作者本轮只读查看实际 `com.hermes.morning-acceptance.plist`：ProgramArguments明确为 `/usr/bin/python3 -B /Users/liweishi/.local/libexec/hermes-morning-acceptance/morning_acceptance.py --home /Users/liweishi`；`/usr/bin/python3 --version`实际为3.9.6。3.11.15是本次策略/测试venv记录的解释器，不能混同两个运行入口，也不能仅据测试venv推定live各进程版本。

已装libexec脚本SHA仍为 `985c617d739b7e45dd9b77d4af3ada440f10e7c6cae6f27c87cbbd283660029d`，不同于C候选217857aa...；只读计算摘要不等于执行/安装该脚本。本轮未运行已装晨验。

测试 `test_system_python_without_site_packages_uses_only_pinned_readers` 的子进程实际调用的是完整 `collect_acceptance`，使用tmp home、v1数据及stub dashboard，不只是解析/导入三个模块。因此准确边界为：**3.9.6下tmp-v1收集已验证；已安装新版C、真实主晨验/HTTP、真实producer或完整ON/v2系统运行尚未验证。** 原报告原样保留，本处以实际代码/任务配置澄清范围，不据此放宽安装或部署门槛。

## 5. 文档冻结与授权

本轮仅新增外审原文、本接收记录，并向总接线计划追加当前状态。C交接、合同、外审入口和所有冻结JSON/log/patch都不修改，避免将外审入口已登记的交接SHA变成过期值。C交接仍为 `23e2916dd873b710c2a71b5ab5e50c27c1d3b27ed21d35511f20b6acbe036b54`；其“待外审”为当时记录，当前状态由本接收与总计划追加更新。

技术许可只覆盖本片精确增量及指定前置交互，不是整树总批准。未来实际提交须明确A/B/review_fix前置与C的来源/顺序，不能机械只stage两个路径就忽略未提交依赖；不得git add -A，不混入三份九月计划、其他未登记字节或私有capture。技术许可不等于用户本轮已要求Git操作。

## 6. 后续顺序

C的代码外审已完成，不需要为相同字节再开一轮重复审查。下一可执行工作是离线梳理已审前置的集成/CI顺序及候选A1发布、迁移、旧writer回滚证明；不是继续扩大C功能、安装libexec或启用capture。

发布前的代码/CI/A1证明、首次受控发布与安装授权、发布后的自然ON/v2观察和A2闭合要分阶段登记。自然样本不能由沙箱制造，也不能用live v1代替；其后置观察门槛未满足不能写作A2闭合。本次不授予首次发布或缩减任何原门槛，现有A1/CI/明确授权仍不足，**DEPLOY HOLD；A2 OPEN；Phase B not started。**

未stage/commit/push/install/deploy，未执行正式daily/晨验、刷新行情/外部源或连接IBKR，未修改live/系统任务/调度/配置。接收核验与前后清点在仓库外 `/Users/liweishi/Documents/New project/hermes-a2-5hc-external-reception-2026-11-04/`，不另建或重写发布证据包。
