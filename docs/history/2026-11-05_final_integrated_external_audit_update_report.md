MU 最低价分歧只读附注 + 最终整树外审更新
结论:附注经独立复算属实;MU 拒收是既有 1% 规则的预期保护,不是候选缺陷,也不构成改代码理由。上轮最终整树外审的五项结论不变;仅新增一项 P3(健康说明不显示最大分歧字段)。

附注证据:building/reports/market_quarantine_followup/2026-11-05/ 一件 mu_low_price.json(1200bd41…)+ SHA256SUMS.json(3691d0e0…,与附注一致);8 个读取源文件前后 SHA 均与当前 live 一致。
我未修改候选/主仓/live/证据;未 stage/commit/push/install/deploy;未刷新/补跑/连接 IBKR;只读 live 与附注 JSON。
一、附注关键事实的独立复算
1. MU 2026-11-04 原始比较(读数取自 live market_admission_2026-11-05.json,operation 6f3953db…)
字段	Yahoo 候选	Alpaca SIP 见证	差异
open	822.9949951171875	822.995	0.0000%
high	853.3399047851562	853.3399	0.0000%
low	791.030029296875	782.0	1.1547%
close	795.22998046875	795.23	0.0000%
volume	35210225	35464905	0.7181%,MATCH
按 round(abs(candidate-witness)/abs(witness)*100, 4) 逐项重算:low = 9.030029296875/782×100 = 1.1547;max OHLC=1.1547 > PRICE_WARN_PCT=1.0 → PRICE_MISMATCH、admitted=false、warning_band=true。
该行:status=PRICE_MISMATCH、decision_impact=COMPONENT_FLOW_ONLY、decision_roles=[component_flow]、candidate_sha256=b35415d1…、witness_sha256=6ac66d8a…(规范化)、raw witness 5a112750…;附注的 raw bar 与嵌套 evidence 一致。
同日 MU 另两行:2026-11-02、2026-11-03 均 MATCH;11-04 是唯一拒收行。不是收盘价或成交量异常。
2. 第三源(研究证据,不改变准入)
live market_admission_third_source_2026-11-05.json:research_only=true、admission_operation_id=6f3953db…、completed_through=2026-11-04、schema 匹配。
Alpha Vantage:low 791.0、close 795.23、open 823.04、high 853.3399、volume 35379841。
candidate_vs_third max OHLC 0.0055%、MATCH;witness_vs_third max OHLC 1.1378%、MISMATCH;third_source_support=YAHOO_CANDIDATE;admission_status_unchanged=PRICE_MISMATCH。
第三源仅研究证据,不是“两票对一票”覆盖 canonical 的授权;本轮未请求任何供应商、未改阈值/见证/候选源。
3. 实际保护行为
canonical data/history/MU.csv SHA 4e5cb74f…,最后日期 2026-11-03,无 2026-11-04 行;admission canonical_files.MU 的 latest_as_of/sha256 与之一致。
admission:status=BLOCKED、rejected_rows=1、component_flow_rejected_rows=1、strategy_blocking_rejected_rows=0;MU 仅 component_flow。
11-05 health(live c1f4b8f,b3028c7c…):health.level=OK;层 strategy_data=OK、position_reconciliation=INFO(IBKR 快照陈旧 age=7979860s)、auxiliary_flows=DEGRADED、operations=INFO(NAAIM 退役);MU 详情: rejected=1 unique_conflicts=1 attempts=1 · MU 2026-11-04 PRICE_MISMATCH price=MISMATCH volume diff=0.7181% third=YAHOO_CANDIDATE · price[MATCH=109,MISMATCH=1,WARNING_BAND=1] volume[MATCH=111]。
11-05 晨验:总 PASS、runtime_integrity PASS、strategy_decision WARN(bound/dashboard)、CERTIFIED;receipt/audit/事务/watchdog PASS;事务 run_id=64a4a011…、v1、COMMITTED、7 产物、active absent。
当前决策:2026-11-04 r1/FINAL、decision-2026-11-04-r1-2cb0225f3343ce075a80、decision_hash=60900644…、identity-v2、预算 2、c1f4b8f、input_hash=f182717a…、market operation 6f3953db…;前驱 null,INITIAL_CERTIFICATION。
SOXL 实际 [9/10 obs],4/9 severe outflow(NVDA/AMAT/LRCX/KLAC);这是 component-only 的辅助流降级,不是策略数据失败(strategy_data=OK)。
连续 OK:11-05 为 0;11-04 的 3/3(acceptance 中曾显示 5)不能沿用。这是新的运行事实,不是候选已部署或实际输入过渡证明。
4. 附注证据与边界
mu_low_price.json 的 8 个 source_hashes_stable_during_read 与当前 live 逐一匹配;bound_health_report_sha256=b3028c7c… 实测匹配;current_decision、canonical、field_diff、rejection、third 均与 live 一致。
未证明:“哪家供应商错”、逐笔/交易条件/盘前盘后口径、第三源覆盖 canonical 的权限、候选发布授权、A1/A2 闭合。
附注本身是只读事实说明,不是新的外审结论或部署批准;未改代码,故不重跑 2288/四日期。
二、对上轮最终整树外审的影响
上轮已完成的最终候选证据(512/90842a11…、54 条 c1f 差异、2288/1606.88s、499/220.49s、c1f→候选四日期 344/383/57 全等、15 mypy、wrapper 4/17、A1 本地 r1/r2/old r2/new date/v2 三态)未变;本附注不修改候选、不新增源码、不构成新候选。其影响仅是运行事实更新:

最终候选正确性:PASS(不变)。 11-05 的 MU 拒收是 1% 价格规则的预期保护;canonical 未推进、第三源仅研究、SOXL [9/10]、component-only、strategy_data OK/aux DEGRADED;没有“MU 旧行情冒充当前观测”或“两票对一票”越权。附注的“无代码修改”成立。
Git 整合/提交/推送:建议不变。 仍以 54 条 c1f 差异 + 512 清单为边界;附注是文档+一件只读诊断 JSON,不进入 512 源清单的 54 条实现差异;不得 git add -A;最终提交仍需精确集成提交与 CI。
A1:本地机制 PASS、生产证明 OPEN(不变)。 11-05 live 仍是 c1f4b8f v1(42d207d6…),不是候选 ac025f0f…;11-05 的 r1/2026-11-04 是 live v1 运行,不是候选 v2 的发布/迁移/旧 writer 回滚证明;A1 不闭合。
部署:HOLD(不变)。 11-05 的保护行为反而支持“保持隔离/不人工补跑/不放宽 1%”;C libexec 仍是 985c617d… 旧版、候选 C 217857aa… 未安装,当前 live release 仍缺 broker_publication_status.py/scheduled_broker_publication.py,C 的动态 reader 对当前 live 只会 READER_UNAVAILABLE;config/manifest 差异与 writer 窗口未闭合;无自然 ON/v2、CI、用户明确 R6/安装授权。
A2/Phase B:OPEN/NOT_STARTED(不变)。 11-05 MU 拒收是 live v1 的既有保护事实,不是 A2 闭合,也不启动 Phase B。
三、P0 → P3
P0/P1:无。 MU 拒收是预期保护;无代码修改;无新增候选缺陷。

P3-1(健康说明精度,附注已提出)最大分歧字段未显示
位置:live 11-05 health auxiliary_flows 详情;web/health.py 的 rejected detail;最终候选 C 的 health 展示仍同源。
现象:详情列出 price=MISMATCH volume diff=0.7181%,但实际拒收字段是 low 1.1547%;读者可能误以为成交量在阻断。附注 §4.4 已提出“除 PRICE_MISMATCH 外直接列最大分歧字段/值/比例”。
影响:仅提示精度;不影响准入结果、健康层级或候选正确性。
处置:可作为独立诊断小片;不应混入冻结候选或据此改准入;当前不阻断提交/部署判定。
P3-2(运行时点)11-05 事实覆盖上轮 11-04 22:04 的 live 快照
上轮最终 audit 的 live 事实为 2026-11-04 22:04(最新 scheduled 2026-11-03、3/3 或 5 连 OK);本附注为 2026-11-05 09:10/09:38 的新运行(as_of 2026-11-04、r1、MU 拒收、连续 OK 0)。
影响:引用 live 事实时应注明 11-05;11-04 的 3/3 不能被 11-05 沿用;11-05 本身仍不是候选发布/自然 ON/v2 样本。
P3-3(第三源)研究证据不改变准入
research_only=true、admission_status_unchanged=PRICE_MISMATCH;candidate_vs_third 0.0055 MATCH、witness_vs_third 1.1378 MISMATCH;third_source_support=YAHOO_CANDIDATE。
不构成“两票对一票”覆盖 canonical;未请求供应商;不改阈值/见证。P3(强化既有边界)。
P3-4(MU 角色)component-only 与层级
MU decision_roles=[component_flow]、decision_impact=COMPONENT_FLOW_ONLY;全局 BLOCKED、strategy_blocking 0;health strategy_data=OK、auxiliary_flows=DEGRADED;总 PASS、strategy_decision WARN。
不是策略数据失败,也不是 MU 旧行情冒充;SOXL [9/10 obs] 已如实呈现。P3。
P3-5(候选未部署)C/libexec 与 live release
live libexec 985c617d…;候选 C 217857aa…;live release 缺两个 reader;附注的 health 是 live c1f4b8f 的已部署 conflict 展示,不是候选 C 的 broker_cache_publication 观测。
11-05 的 unique_conflicts=1 attempts=1 是 live 已部署 conflict 展示;候选 C 的 morning observation 未运行。P3。
P3-6(证据/归属)附注的 8 源文件与清单
8 个源文件前后 SHA 匹配;mu_low_price.json 1200bd41…、manifest 3691d0e0…;附注为一件 JSON+manifest,不复制私有账户/持仓/DB。
归属:附注是作者只读事实记录,本报告为独立复算;不是新的外审批准。P3。
P3-7(连续 OK 计数)
11-05 为 0;11-04 的 3/3(或 acceptance 的 5)不能沿用;这是 11-05 MU 拒收的直接结果,不是健康/策略整体失败。P3。
既有 P2 保留(上轮最终 audit,不变)
A1 生产证明 OPEN;live config/manifest 差异(认证 2f95f3b9… vs 当前 669d7797…);C libexec/readers;CI 20 分钟;静态债 15/19 + wrapper 4/17 + ops 4;postcommit health 的接口外边界;比较器归一化范围;候选私有 .git HEAD c1f4b8f 不是集成提交;SIGKILL≠断电;live 时点/writer。附注不改变这些。
四、五项结论(在 11-05 运行事实下)
最终候选联合正确性:PASS(限定范围)。 512/54/2288/499/c1f strict/A1 本地机制不变;11-05 MU 拒收是预期保护;无 P0/P1;P3-1 提示精度可独立处理。
Git 整合/提交/推送:建议按精确 54 条 + 512 清单进行;附注文档/证据单独列,不进入源码 54 条;不得 git add -A;提交后跑 CI。
A1:本地机制 PASS;生产证明 OPEN。 11-05 live 是 c1f4b8f v1(42d207d6…),不是候选 ac025f0f…;发布/迁移/旧 writer 回滚/自然 ON/v2 未证。
部署:HOLD。 11-05 的保护行为支持继续隔离;C libexec/readers、config/manifest、writer 窗口、CI、自然样本、明确授权均未闭合;候选未部署。
A2/Phase B:A2 OPEN,Phase B 未启动。 11-05 MU 拒收是 live v1 既有保护事实,不是 A2 闭合。
五、当前 live 事实(11-05,替代上轮 11-04 22:04 快照)
11-05 09:10:05 晨验:PASS、runtime PASS、strategy WARN、CERTIFIED;as_of 2026-11-04;receipt OK;audit count 1;事务 64a4a011… v1 COMMITTED 7 active absent;bound/dashboard WARN(IBKR 陈旧/NAAIM/auxiliary MU);watchdog PASS。
决策:2026-11-04 r1/FINAL、decision-2026-11-04-r1-2cb0225f…、60900644…、identity-v2、预算 2、c1f4b8f、f182717a…、operation 6f3953db…。
准入:BLOCKED、1 rejected(component)、0 strategy;MU low 1.1547% > 1%;volume 0.7181 MATCH;PRICE_MISMATCH;canonical MU 2026-11-03 4e5cb74f…;第三源研究-only;连续 OK 0。
候选:未部署;live c1f4b8f v1;libexec 985c617d…;live release 缺 reader;config 5cff823e…;writer 0 未持锁;认证 manifest ≠ 当前 manifest。
未运行今日新晨验之后的其他采集;未刷新/补跑/连接 IBKR;未改 live/配置/调度/证据。
（本轮只读附注与 live;未修改候选/主仓/证据;所有复算在本地读取完成;无 Git/安装/部署操作。DEPLOY HOLD;A1 生产证明未闭合;A2 OPEN;Phase B 未启动。）