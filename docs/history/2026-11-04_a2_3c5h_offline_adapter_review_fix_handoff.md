# A2 3C-5h-B 内部复核修正：外层 schema 与 JSON 深度

当前状态：两项内部P2已复现、修正并完成本地验证；待独立外审当前B版与修正的组合候选。**DEPLOY HOLD；A2 OPEN；Phase B未启动。**

## 1. 范围与冻结基线

本片只修改此前新增的 `core/reporting/scheduled_broker_publication.py` 与 `tests/test_scheduled_broker_publication.py`，没有改5g/producer/评分/身份/事务/配置/flag/比较器/依赖/CI/部署/晨验/调度。没有生产调用方或capture启用。

基线是5h-B首版377文件的已封存源码清单 `570da621b80bdf8e4b24af3942d7fc7666efe0a5b51f8d17711be210b281c917`，不是HEAD、不是5h-A的375文件版本，也不是内部早期P2修正前副本。

| 文件 | 修正前 SHA-256 |
|---|---|
| scheduled_broker_publication.py | 252ff92908980dbdae08254ff33a9c3983677b918c6717326f66775fe006b947 |
| test_scheduled_broker_publication.py | 144aeaceb278eec5c7424670ac77ed9ccd6e1e58bace38295e266a8db6337c04 |

旧证据目录 `building/reports/a2_production_capture/2026-11-04/3c5h_offline_adapter/` 的24件与清单原字节保留；其中旧source-binding的这两项不再匹配当前源码是本片显式改变，不是静默证据漂移。旧2132测试结果只归属于旧字节。

| 文件 | 修正后 SHA-256 | 行数 |
|---|---|---|
| scheduled_broker_publication.py | e33a71b585be04a58f502e532cda9ff6c78ccd56a84e80b8b18e9efcaee065fa | 163 |
| test_scheduled_broker_publication.py | 023f2646b026181b7106ec0251880d66aa4b4daa675b5f910c3dad9d74100f45 | 457 |

新证据独立位于 `building/reports/a2_production_capture/2026-11-04/3c5h_offline_adapter_review_fix/`；before副本与slice.patch绑定旧B到新修正的两个文件，不能将整个git diff HEAD当成本片差异。

## 2. Findings 与最小修正

### P2-1：未知外层审计 schema 可产生辅助成功

原实现检查了payload的schema，未检查包含payload的外层审计record schema。内部探针仅将 `escape-top-greenfield-audit-v1` 改成 `future-audit-v999`，其余合成v2链条有效，旧实现仍返回OK/PUBLISHED。

修正：只有含payload的包裹记录才检查外层schema；明确存在时必须为当前audit-v1，无该字段的历史包裹记录仍支持。旧式未包裹score-v1 payload继续按原payload检查，不错误套用外层格式要求。未知字符串/null/数字在v1/v2下均UNKNOWN。

验证先RED：6项错误schema用例失败、2项正常格式控制通过；修正后8项全部通过。正常控制包括已知audit-v1外层及未包裹score-v1，不用“把所有格式都拒绝”冒充修复。

### P2-2：过深JSON会抛出非结构化异常

receipt内未使用字段或历史audit行包含超过解释器递归深度的JSON数组时，标准解析器抛RecursionError，旧边界未处理。它不是UNKNOWN，也不是发布失败证据。

修正：只在既有只读观察边界增加RecursionError→UNKNOWN，不提高递归限制、不忽略坏行后猜唯一run、不修改源文件、不捕获MemoryError/SystemExit等资源或控制异常。两个receipt/历史audit测试均先复现RecursionError，再验证UNKNOWN及原文件字节不变。此修正不是文件大小、内存耗尽或对抗同用户的资源安全保证。

## 3. 测试与证据状态

新增10项：未知外层schema三值×v1/v2共6项，正常格式控制2项，深JSON2项。既有76项保留，当前新测试文件共86项。修正前后的RED/GREEN日志分别保存，不覆盖旧包。

| 修正后最终验证 | 结果 |
|---|---|
| 新文件 | 86 passed / 10.35s |
| 六文件关联 | 243 passed / 83.69s |
| 全套 | 2142 passed / 1420.48s，exit 0 |
| Governance | 8/8 OK，ibkr_readonly=true |
| 新两文件完整Ruff、全仓severe | PASS / PASS |
| 既有14模块加新模块mypy | 15 files PASS，无新增ignore/exclude |
| compile / pip check / diff check | PASS |
| 外部故障演练 | 13场景达到各自预期，顶层PASS、零网络、未触live；不表示各源都OK |
| 四日期OFF strict | all_equal=true，4/4 strict_differences=[]，比较器不变 |
| 评分指纹 | 基线/候选均ac025f0f93d16ee3b97e1aaa8f7e70b49801032d81085453b7e5531eae8e7dad |

源码清单仍377文件，候选manifest变为 `24f37156178f8e5953e2534f7502b21af8a7a588cd8bc3c9fd1da5eda5356806`；与旧B相比零新增/删除、仅两文件修改，其他375个共有源码原字节不变。比较器仍 `19540147b21004355d0f54eb14c0455301bddb870b47a370b0a753178d5bd76d`，种子与解释器绑定随JSON提供，不增加忽略项。

本轮初次strict运行的人工显示标签继承了旧脚本A阶段的文字，但实际基线文件数/摘要从一开始就是旧B的377/570da621...。随后单独以正确B→修正标签重跑，另存权威 `equivalence-final.json`；初次 `equivalence.json`、原命令和修正记录均保留，两个报告源/种子绑定与4/4全等结果一致，不手改旧JSON冒充新执行。

内部复核另有12项独立定点探针通过，覆盖原10项加无schema历史包裹v1/v2控制；文件字节/mtime/权限不变。这是内部定点核验，不是外部审计或全套执行归属。原探针在/tmp、只记录摘要，不复制临时材料或私有capture。

完整日志/源码快照另存私有工作区 `/Users/liweishi/Documents/New project/hermes-a2-5b-review-fix-2026-11-04/`；公开证据只包含源码、合成诊断及门禁日志，不复制实际broker数据/数据库。旧B、旧A证据及九月计划保留。现有扩大范围15条mypy/19条Ruff债未修改，不能用新模块PASS宣称全仓清零。全套本地约24分钟，CI当前20分钟预算仍须后续实际核验，未改CI或声称新提交CI已绿。

## 4. 审查与后续边界

本轮审查是新的内部复核，不是用户提供的独立外审。后续请针对本片新字节与旧B版差异独立审查，重点复现未知schema不可产出OK/NOT_APPLICABLE、已知/legacy格式仍可用、深JSON不抛出且不写文件；再核对完整86项、关联/全套、治理/静态/四日期严格比较及原摘要转交路径。

5h-A独立外审结论不自动覆盖本片，旧B本就尚未独立外审。需要外审当前B+本修正的最终候选，不是先接晨验/直接部署。原本机信任、秒精度时间窗、串行读取、合成选择矩阵与真实producer整合的边界均未扩大。**DEPLOY HOLD；A2 OPEN；Phase B未启动。**

本轮未stage/commit/push/deploy、未生成或重跑官方日报/晨验、未刷新数据、未连接或刷新IBKR、未更改live/主系统任务。下一步将本文件与原B交接一起送独立外审；无需再为同字节重复全套或把内部复核当额外正式审批。

## 5. 封存核对

source-binding.json绑定两修改源码与18个未变依赖；before两源码和slice.patch可在完整旧B基线上dry-run，退出0。SHA256SUMS.json绑定33件证据，清单自身SHA-256为 `fb66f8ebbf6fb53045a1912b3f7dc9b7b9d65fb8dc86f9889c226ecb2e7df338`；本交接不在清单内，避免循环绑定。权威四日期报告为 `equivalence-final.json`，原人工标签不准确的第一次输出仍保留并由label-correction记录解释。

开始的1256个已列举仓库文件中1251个原字节不变。变动为本片两源码与三份旧文档追加（原B交接、契约、总计划），三文档旧字节前缀均匹配；本新交接及新证据单列。旧B的24件证据原样、旧A的13源码/22证据仍匹配。源码在最终全套开始/结束之间无漂移；20项源码/依赖和33项新证据最终重算后才可视为本片封存完成。

当前结论仅为本地验证完成，两项内部发现已解决，**不等于独立外审通过、CI通过或任何Git/部署授权。DEPLOY HOLD；A2 OPEN；Phase B未启动。**

## 6. 2026-11-04 独立外审接收注记

当前B版与本修正组合已独立外审正确性PASS，两项内部P2闭合；原文与处置见 `2026-11-04_a2_3c5h_b_external_audit_{report,followup}.md`。20源码/依赖与33证据无漂移，旧B24件及旧A13/22保留。以上“待外审”为历史时点，不再代表本组合现状。

证据精度更正：第3节的243关联结果只有历史摘要，未记录完整六文件命令，不能当作可独立逐项复算的门禁。外审另用七文件分组247通过，不是精确复现243；本片以独立复现的86新测试、2142全套、治理/静态/四日期OFF strict为主要验证。保留旧日志/清单，不猜补命令或覆盖证据。未来关联执行须记录完整文件列表与参数。本轮仅文档接收，未重跑代码、未Git/live操作。A1候选证明、CI与自然ON样本等仍OPEN；**DEPLOY HOLD；A2 OPEN；Phase B未启动。**
