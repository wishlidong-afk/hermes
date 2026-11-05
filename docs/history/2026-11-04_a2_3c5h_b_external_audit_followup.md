# A2 3C-5h-B 组合候选外审接收

日期：2026-11-04，Asia/Shanghai。独立外审结论：**当前 B 版及两项内部 P2 修正的正确性 PASS；精确范围具备提交/推送技术许可；DEPLOY HOLD；A2 OPEN；Phase B 未启动。** 本轮接收不授予 Git 写操作、生产接线或部署权限。

## 1. 原文与冻结绑定

用户附件为 `/Users/liweishi/.codex/attachments/86ccbb48-4bcb-414d-b1e5-042b099f3244/已粘贴的文本.txt`。已原字节归档为 `2026-11-04_a2_3c5h_b_external_audit_report.md`，保留 CRLF，不改写审计员原文；两者均为 10757 bytes，SHA-256 为 `d35e79946395beede4a879fc62f7e76a507a11b398bad3ee5ff74b7a435a8ee2`。

本轮作者只做接收核验，没有重新执行外审或未变化代码的测试：

| 对象 | 接收时独立重算 |
|---|---|
| 当前两个实现/测试及 18 个依赖 | 20/20 匹配 |
| review_fix 证据 | 33/33 匹配，清单 SHA `fb66f8ebbf6fb53045a1912b3f7dc9b7b9d65fb8dc86f9889c226ecb2e7df338` |
| 旧 B 冻结证据 | 24/24 匹配，清单 SHA `b9d8515b9b3d37f3d62fd0928fe451b9b6115e1bd4e00a7537b0bbda1b759cc9` |
| 旧 A 源码/依赖与证据 | 13/13、22/22 匹配，清单 SHA `984f8b246304240af6eaffa1336a5bbfffc971d9d2902402c928cbadec2312bd` |

当前源码仍为 scheduled_broker_publication.py 163 行 / `e33a71b585be04a58f502e532cda9ff6c78ccd56a84e80b8b18e9efcaee065fa`，测试 457 行 / `023f2646b026181b7106ec0251880d66aa4b4daa675b5f910c3dad9d74100f45`。旧 B 的两个旧源摘要只作为修正前对照，不要求它们匹配当前文件；不刷新旧清单来掩盖增量。

## 2. 两项内部 P2 的外审闭合

- 未知外层 audit schema：外审复现修正前错误接受，确认当前仅对 payload 包裹检查外层格式；显式未知/null/数字拒收，缺 schema 的历史包裹和旧未包裹 payload 保留支持。原 RED/GREEN 与当前 86 项测试固定行为。
- 深 JSON：外审确认解析 RecursionError 在只读观察边界转为 UNKNOWN，不跳过坏行猜 run、不提高递归深度、不修改文件；不扩大为内存/文件大小或同用户资源防护。

两项实现缺陷均闭合，没有本轮必须修改的源码。外审当前组合 PASS 不等于旧 B 单独曾获审，也不把 A 的旧批准转借给 B。

## 3. 验证归属与证据精度更正

外审员独立执行：新文件 **86 passed / 12.09s**、全套 **2142 passed / 1525.79s**、治理 **8/8 OK**、两文件 Ruff / 全仓 severe / 15 文件 mypy / compile / pip check / diff check 均通过，四日期 OFF strict 全等，故障演练 13 场景达到各自预期、零网络、未触 live。这些是外审员执行，不冒称作者本轮重跑。

**P3-1 接受：原 243 项关联测试只保存摘要，没有完整六文件命令。** 作者原日志确实记为 243，但当前证据包不能逐项重建该子集；本轮不补写猜测的历史命令，不把它继续列为独立可复算门禁。原交接/日志作为时点记录保留。外审员另用七文件分组得到 **247 passed**，不是对 243 的精确复现：adapter 86 + A 两文件 40 + 5g 70 + anchor 7 + transaction_v2_acceptance 19 + run_receipt_writer 25。可靠的本片测试结论以精确复现的 86 与 2142 为主。后续新的关联执行必须同时记录完整参数、文件列表、退出码与日志，不能只有数量摘要；无需为同字节再造一轮全套。

P3-2 标签修正按既有记录接受：引用 `equivalence-final.json`，保留首次人工标签错误的 `equivalence.json` 与 label-correction.json，不改写冻结 JSON。实际源/种子绑定与比较结果从未因标签变化改变。

## 4. 仍开放的限制

| 外审项 | 处置 |
|---|---|
| P2-1 A1 发布门槛 | 候选 ac025f0f... 与 live 42d207d6... 不同。候选发布/迁移/旧 writer 回滚及 scheduled certification 证明仍 OPEN；不以 OFF strict 或 live v1 自然 3/3 替代。 |
| P2-2 本机信任 | LOCAL_PRODUCER_RECEIPT 不是签名，不能防同用户同时改 receipt/audit/journal；接线必须保留来源说明，不加 JSON 包装假装外部锚。 |
| P2-3 静态债 | 扩大范围 15 条 mypy / 19 条 Ruff 仍在；指定 15 模块 PASS 不等于全仓清零。另片治理，不新增 ignore/exclude。 |
| P3-3 资源边界 | 仅闭合 RecursionError，不声明超大文件/MemoryError 防护。 |
| P3-4 辅助与主链状态 | 辅助 OK 可与正式 FAILED 并存；未来调用必须保留 official_receipt_status，不覆盖主 runtime/strategy FAIL。 |
| P3-5 时间 | 秒精度窗口不是单调时钟证明，继续保留限制。 |
| P3-6 审查范围 | 本次批准当前 B + 修正字节，不是旧 B 单独审批或整个 dirty tree 总批准。 |

CI 尚未实测新提交。本地全套约 24 分钟、外审约 25 分钟，现有 CI 20 分钟预算存在待核验风险；不据此声称云端必然超时，不擅改超时或拆分门禁。完整自动 T1→T2、hermetic 环境、广故障/耐久性与自然 ON/v2 样本仍未完成。

## 5. 本轮范围与后续

本轮仅新增外审原文、本接收记录，对修正交接、原 B 交接、总计划末尾追加时点注记，旧字节前缀保留。不改源码、测试、配置、flag、依赖、比较器、CI、冻结证据或九月计划；不运行 official daily/晨验主程序，不刷新行情/外部源或连接 IBKR，不改 live/系统任务。

技术允许的 B 范围为两个新源文件、review_fix 证据目录及本片交接；其他片、旧 A/B 包和私有 capture 不混入。旧 B/旧 A 仍是前置对照材料，不删除；实际 Git 提交还须识别未提交前置依赖并获得用户授权，不能把本报告当作孤立两文件已可安全集成或 git add -A 的授权。本轮没有 stage/commit/push/deploy。

下一工程片先确定晨验只读接线合同与测试边界，保留 OFF/v1 不适用、v2 缺锚 UNKNOWN、本机来源及主/辅助状态分离；本轮未实施接线，也不接 WebUI/轮询/自动补发。当前不需要对相同字节再开第四道重复审批。**DEPLOY HOLD；A2 OPEN；Phase B not started。**

接收时绑定核验与前后清点保存在仓库外 `/Users/liweishi/Documents/New project/hermes-a2-5hb-external-reception-2026-11-04/`；不是新发布证据包，不覆盖已有封存清单。
